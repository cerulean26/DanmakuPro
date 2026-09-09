"""弹幕压制核心引擎

DanmakuBurner 是弹幕压制的编排器，负责组合各子模块完成完整的处理管线。
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable

from loguru import logger
from tqdm import tqdm

from ..config.models import DanmakuConfig, DEFAULT_CONFIG, EncodeMode
from ..errors import EncodeError, DanmakuProError
from ..input.parser import parse_xml
from ..layout.engine import LayoutEngine, LayoutContext
from ..layout.params import LayoutParams, LayerParams
from ..render.renderer import DanmakuRenderer
from ..render.assets import AssetLoader
from ..render.layout_builder import DanmakuLayoutBuilder
from ..encode.ffmpeg import FFmpegManager
from ..utils.validation import validate_video_input, validate_xml_input, validate_output_path




class DanmakuBurner:
    """弹幕压制引擎"""

    def __init__(
        self,
        video_in: str,
        xml_in: str,
        video_out: str | None = None,
        encode_mode: str = EncodeMode.AUTO,
        config: DanmakuConfig = DEFAULT_CONFIG,
        force: bool = False,
    ):
        """初始化弹幕压制引擎
        Args:
            video_in: 输入视频路径
            xml_in: 输入弹幕 XML 文件路径
            video_out: 输出视频路径
            encode_mode: 编码模式
            config: 弹幕配置
            force: 是否强制覆盖输出文件
        """
        validate_video_input(video_in)
        validate_xml_input(xml_in)

        self.video_in = video_in
        self.xml_in = xml_in
        self._config = config

        if video_out:
            self.video_out = video_out
        else:
            video_path = Path(video_in)
            self.video_out = str(video_path.parent / f"{video_path.stem}-弹幕版.mp4")

        self.video_out = Path(self.video_out).as_posix()

        validate_output_path(self.video_out, force)

        self._asset_provider = AssetLoader(
            font_size=self._config.style.font_size,
            assets_dir=self._config.system.assets_dir,
        )
        self._frame_encoder = FFmpegManager(
            video_in, self.video_out, encode_mode,
            self._config.encode, self._config.system,
        )

    def run(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
        speed_callback: Callable[[float], None] | None = None,
        log_callback: Callable[[str], None] | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> None:
        """执行完整的弹幕压制流程。

        按顺序执行 4 个步骤：
        1. 解析弹幕 XML
        2. 加载资源文件
        3. 获取视频元数据
        4. 启动 FFmpeg 编码器 + 压制渲染

        Args:
            progress_callback: GUI 进度回调 (current, total)
            speed_callback: GUI 编码速度回调 (speed)
            log_callback: GUI 日志回调 (message)
            stop_check: 停止检查回调，返回 True 时中断压制

        KeyboardInterrupt 会被捕获并输出警告，其他异常按策略处理。
        无论成功或失败，finally 块都会执行资源清理。

        Raises:
            DanmakuProError: 弹幕压制相关的已知错误
            RuntimeError: 不可恢复的致命错误
        """
        cfg = self._config
        style = cfg.style
        syscfg = cfg.system

        # Step 1
        events = parse_xml(self.xml_in, min_gift_price=cfg.animation.min_gift_price)
        text_count = sum(1 for e in events if not e.is_gift)
        t_min = events[0].time if events else 0.0
        t_max = events[-1].time if events else 0.0
        msg = (
            f"[1] 解析 XML → {len(events)} 事件"
            f" (文本 {text_count}+礼物 {len(events) - text_count}),"
            f" {t_min:.1f}~{t_max:.1f}s"
        )
        logger.info(msg)
        if log_callback:
            log_callback(msg)

        # Step 2
        self._asset_provider.load_assets(events)
        msg = (
            f"[2] 加载资源 → "
            f"Emoji {len(self._asset_provider.emoji_cache)}, "
            f"礼物 {len(self._asset_provider.gift_cache)}"
        )
        logger.info(msg)
        if log_callback:
            log_callback(msg)

        # Step 3
        v_info = self._frame_encoder.get_video_info()
        raw_w: int = int(v_info['w'])
        raw_h: int = int(v_info['h'])
        fps: float = float(v_info['fps'])
        total_frames: int = int(v_info['frames'])

        align = syscfg.video_alignment
        w = int(((raw_w + align - 1) // align) * align)
        h = int(((raw_h + align - 1) // align) * align)

        msg = (
            f"[3] 视频信息 → {raw_w}x{raw_h}, {fps:.0f}fps, "
            f"{total_frames} 帧 ({total_frames / fps:.0f}s)"
        )
        logger.info(msg)
        if log_callback:
            log_callback(msg)

        layout_params, layer_params = LayoutEngine.calculate_params(
            w, h, style, cfg.ratio, self._asset_provider.line_height,
        )

        layout_builder = DanmakuLayoutBuilder(
            fm=self._asset_provider.fm,
            emoji_cache=self._asset_provider.emoji_cache,
            gift_cache=self._asset_provider.gift_cache,
            max_content_width=layout_params.text_w,
            line_height=self._asset_provider.line_height,
            style=style,
        )

        ffmpeg_cmd = self._frame_encoder.build_command(fps, w, h, layer_params)

        # Step 4
        try:
            self._frame_encoder.start(ffmpeg_cmd)
            msg = "[4] 准备就绪 → 启动 FFmpeg"
            logger.info(msg)
            if log_callback:
                log_callback(msg)
            self._render_loop(
                fps, total_frames, events, layout_builder,
                layout_params, layer_params,
                progress_callback, speed_callback, log_callback, stop_check,
            )
        except KeyboardInterrupt:
            logger.warning("用户中断压制")
            self._frame_encoder.abort()
        except DanmakuProError:
            raise
        except Exception as e:
            raise RuntimeError(f"压制失败: {e}") from e
        finally:
            self._frame_encoder.cleanup()

    def force_stop(self) -> None:
        """强制中断：关闭 FFmpeg stdin，解除阻塞的写入"""
        self._frame_encoder.close_stdin()

    def _encode_frame(
        self,
        frame_encoder: FFmpegManager,
        renderer: DanmakuRenderer,
        pbar: tqdm,
        frame_idx: int,
        total_frames: int,
    ) -> None:
        """提交单帧编码，处理编码错误。

        Args:
            frame_encoder: 帧编码器
            renderer: 渲染器
            pbar: 终端进度条
            frame_idx: 当前帧索引
            total_frames: 总帧数

        Raises:
            EncodeError: 编码器错误且策略为中止
        """
        try:
            frame_encoder.submit_frame(renderer.get_frame_data())
            pbar.update(1)
        except (BrokenPipeError, OSError, RuntimeError) as e:
            raise EncodeError(f"编码器错误 [帧 {frame_idx}]: {e}") from e

    @staticmethod
    def _warn_unspawned(
        events: list[Any],
        start_idx: int,
        video_duration: float,
        label: str,
        spawned: int,
        total: int,
    ) -> None:
        unspawned: list[Any] = []
        is_gift = label == "礼物弹幕"
        for i in range(start_idx, len(events)):
            if events[i].is_gift == is_gift:
                unspawned.append(events[i])

        beyond = sum(1 for e in unspawned if e.time > video_duration)
        blocked = len(unspawned) - beyond

        parts = [f"{label}未完全发射: {spawned}/{total}"]
        if beyond > 0:
            parts.append(f"{beyond}条超出视频时长({video_duration:.1f}s)")
        if blocked > 0:
            parts.append(f"{blocked}条被批次限制阻塞")

        logger.warning("; ".join(parts))

    def _render_loop(
        self,
        fps: float,
        total_frames: int,
        events: list[Any],
        layout_builder: Any,
        layout_params: LayoutParams,
        layer_params: LayerParams,
        progress_callback: Callable[[int, int], None] | None = None,
        speed_callback: Callable[[float], None] | None = None,
        log_callback: Callable[[str], None] | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> None:
        """渲染主循环（单线程）
        Args:
            fps: 视频帧率
            total_frames: 总帧数
            events: 弹幕事件列表（按需惰性构建 ActiveDanmaku）
            layout_builder: 弹幕布局构建器
            layout_params: 布局参数
            layer_params: 层参数
            progress_callback: GUI 进度回调 (current, total)
            speed_callback: GUI 编码速度回调 (speed)
            log_callback: GUI 日志回调 (message)
            stop_check: 停止检查回调，返回 True 时中断
        Raises:
            DanmakuProError: 弹幕压制过程中发生错误
        """
        frame_encoder = self._frame_encoder
        anim = self._config.animation

        active_text: list[Any] = []
        active_gift: list[Any] = []

        layout_ctx = LayoutContext(animation=anim)

        renderer = DanmakuRenderer(layer_params)

        total_text_danmaku = sum(1 for e in events if not e.is_gift)
        total_gift_danmaku = len(events) - total_text_danmaku

        use_gui = progress_callback is not None

        logger.complete()
        pbar = tqdm(
            total=total_frames, desc="压制进度", unit="帧",
            bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}{postfix}]",
        )
        if use_gui:
            progress_callback(0, total_frames)

        SPEED_UPDATE_INTERVAL = 30
        PROGRESS_UPDATE_INTERVAL = 30
        fade_out_zone = self._config.style.fade_out_zone
        total_text_spawned = 0
        total_gift_spawned = 0

        t_start = time.perf_counter()
        try:
            for frame_idx in range(total_frames):
                current_time = frame_idx / fps

                # 弹幕逻辑
                text_has_new, gift_has_new, text_emitted, gift_emitted = (
                    LayoutEngine.spawn_new_danmakus(
                        layout_ctx, current_time, events, active_text, active_gift,
                        layout_builder, self._asset_provider, self._config.style,
                    )
                )
                total_text_spawned += text_emitted
                total_gift_spawned += gift_emitted

                LayoutEngine.update_danmaku_layer(
                    active_text, text_has_new,
                    layout_params.bottom, layout_params.text_top,
                    layout_params.gap, anim.text_damping_factor,
                )
                LayoutEngine.update_danmaku_layer(
                    active_gift, gift_has_new,
                    layout_params.text_top, layout_params.gift_top,
                    layout_params.gap, anim.gift_damping_factor,
                    current_time, anim.gift_dwell_time,
                )

                # 渲染当前帧
                renderer.render_frame(
                    active_text, active_gift,
                    layout_params,
                    fade_out_zone,
                )

                # 编码
                if stop_check and stop_check():
                    raise KeyboardInterrupt
                self._encode_frame(
                    frame_encoder, renderer, pbar, frame_idx, total_frames,
                )

                if use_gui:
                    if frame_idx % PROGRESS_UPDATE_INTERVAL == 0:
                        progress_callback(frame_idx + 1, total_frames)
                    if frame_idx % SPEED_UPDATE_INTERVAL == 0:
                        if speed_callback:
                            speed_callback(frame_encoder.current_speed)
                if frame_idx % SPEED_UPDATE_INTERVAL == 0:
                    speed = frame_encoder.current_speed
                    pbar.set_postfix(
                        {"speed": f"{speed:.1f}x" if speed > 0 else "--"}
                    )
                if stop_check and stop_check():
                    raise KeyboardInterrupt
        finally:
            renderer.end()
            pbar.close()

        # 仅在正常完成时输出统计（异常时不会执行到这里）
        elapsed = time.perf_counter() - t_start
        video_duration = total_frames / fps
        msg = (
            f"完成: {total_frames} 帧, {elapsed:.1f}s, "
            f"弹幕 {total_text_spawned}/{total_text_danmaku} + 礼物 {total_gift_spawned}/{total_gift_danmaku}"
        )
        logger.info(msg)
        if log_callback:
            log_callback(msg)
        if total_text_spawned < total_text_danmaku:
            DanmakuBurner._warn_unspawned(
                events, layout_ctx.text_event_idx, video_duration,
                "文本弹幕", total_text_spawned, total_text_danmaku,
            )
        if total_gift_spawned < total_gift_danmaku:
            DanmakuBurner._warn_unspawned(
                events, layout_ctx.gift_event_idx, video_duration,
                "礼物弹幕", total_gift_spawned, total_gift_danmaku,
            )