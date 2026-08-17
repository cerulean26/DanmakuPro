"""弹幕压制核心引擎

DanmakuBurner 是弹幕压制的编排器，负责组合各子模块完成完整的处理管线。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger
from tqdm import tqdm

from ..config.models import DanmakuConfig, DEFAULT_CONFIG, EncodeMode
from ..errors import (
    RecoveryAction, EncodeError, DanmakuProError, handle_error,
)
from ..input.parser import parse_xml
from ..layout.engine import LayoutEngine, LayoutContext
from ..layout.params import LayoutParams, LayerParams
from ..render.renderer import DanmakuRenderer
from ..render.assets import AssetLoader
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

        validate_output_path(self.video_out, force)

        self._asset_provider = AssetLoader(font_size=self._config.style.font_size)
        self._frame_encoder = FFmpegManager(
            video_in, self.video_out, encode_mode,
            self._config.encode, self._config.system,
        )

    def run(self) -> None:
        """执行完整的弹幕压制流程。

        按顺序执行 8 个步骤：
        1. 解析弹幕 XML — 将 Bilibili 弹幕 XML 解析为事件列表
        2. 加载资源文件 — 预加载字体、Emoji 和礼物图片
        3. 获取视频元数据 — 读取分辨率、帧率、总帧数
        4. 计算布局参数 — 根据视频尺寸计算弹幕显示区域
        5. 预创建弹幕对象 — 构建弹幕气泡并缓存渲染结果
        6. 构建 FFmpeg 编码命令 — 根据编码模式和参数生成命令
        7. 启动 FFmpeg 编码器 — 启动子进程，建立管道
        8. 压制渲染 — 逐帧发射弹幕、渲染、编码输出

        KeyboardInterrupt 会被捕获并输出警告，其他异常按策略处理。
        无论成功或失败，finally 块都会执行资源清理。

        Raises:
            DanmakuProError: 弹幕压制相关的已知错误
            RuntimeError: 不可恢复的致命错误
        """
        cfg = self._config
        style = cfg.style
        syscfg = cfg.system

        total_steps = 8

        step = 0
        step += 1; logger.info(f"[{step}/{total_steps}] 解析弹幕 XML")
        events = parse_xml(self.xml_in, min_gift_price=cfg.animation.min_gift_price)

        step += 1; logger.info(f"[{step}/{total_steps}] 加载资源文件")
        self._asset_provider.load_assets(events)

        step += 1; logger.info(f"[{step}/{total_steps}] 获取视频元数据")
        v_info = self._frame_encoder.get_video_info()
        raw_w: int = int(v_info['w'])
        raw_h: int = int(v_info['h'])
        fps: float = float(v_info['fps'])
        total_frames: int = int(v_info['frames'])

        align = syscfg.h264_alignment
        w = int(((raw_w + align - 1) // align) * align)
        h = int(((raw_h + align - 1) // align) * align)

        step += 1; logger.info(f"[{step}/{total_steps}] 计算布局参数")
        layout_params, layer_params = LayoutEngine.calculate_params(w, h, style, cfg.ratio)

        step += 1; logger.info(f"[{step}/{total_steps}] 预创建弹幕对象")
        danmaku_pool = LayoutEngine.preload_danmaku_objects(
            events, layout_params, self._asset_provider, style,
        )

        step += 1; logger.info(f"[{step}/{total_steps}] 构建 FFmpeg 编码命令")
        ffmpeg_cmd = self._frame_encoder.build_command(fps, w, h, layer_params)

        step += 1; logger.info(f"[{step}/{total_steps}] 启动 FFmpeg 编码器")
        try:
            self._frame_encoder.start(ffmpeg_cmd)
            # 刷新异步日志队列，避免与 tqdm 进度条输出交叠
            logger.complete()
            self._render_loop(
                fps, total_frames, danmaku_pool,
                layout_params, layer_params, step, total_steps,
            )
        except KeyboardInterrupt:
            logger.warning("用户中断压制")
        except DanmakuProError:
            raise
        except Exception as e:
            recovery = handle_error(e, component="burner", operation="run")
            if recovery == RecoveryAction.ABORT:
                raise RuntimeError(f"压制失败: {e}") from e
            raise
        finally:
            logger.info("清理资源")
            self._frame_encoder.cleanup()

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
            pbar: 进度条
            frame_idx: 当前帧索引
            total_frames: 总帧数

        Raises:
            EncodeError: 编码器错误且策略为中止
        """
        try:
            frame_encoder.submit_frame(renderer.get_frame_data())
            pbar.update(1)
        except (BrokenPipeError, OSError, RuntimeError) as e:
            recovery = handle_error(
                e, component="burner", operation="submit_frame", frame_idx=frame_idx,
            )
            if recovery == RecoveryAction.ABORT:
                raise EncodeError(f"编码器错误: {e}") from e
            elif recovery == RecoveryAction.SKIP:
                logger.warning(f"[{frame_idx:>6}/{total_frames}] 跳过帧")
            else:
                raise

    def _render_loop(
        self,
        fps: float,
        total_frames: int,
        danmaku_pool: list[Any],
        layout_params: LayoutParams,
        layer_params: LayerParams,
        step: int,
        total_steps: int,
    ) -> None:
        """渲染主循环（单线程）
        Args:
            fps: 视频帧率
            total_frames: 总帧数
            danmaku_pool: 弹幕对象池
            layout_params: 布局参数
            layer_params: 层参数
            step: 当前步骤序号
            total_steps: 总步骤数
        Raises:
            DanmakuProError: 弹幕压制过程中发生错误
        """
        frame_encoder = self._frame_encoder
        anim = self._config.animation

        active_text: list[Any] = []
        active_gift: list[Any] = []

        layout_ctx = LayoutContext(animation=anim)

        renderer = DanmakuRenderer(layer_params)

        total_danmaku = len(danmaku_pool)
        total_text_danmaku = sum(1 for d in danmaku_pool if not d.event.is_gift)
        total_gift_danmaku = total_danmaku - total_text_danmaku

        step += 1; logger.info(
            f"[{step}/{total_steps}] 压制渲染 | "
            f"弹幕池: 共 {total_danmaku} 条 (文本 {total_text_danmaku} + 礼物 {total_gift_danmaku}), "
            f"视频 {total_frames} 帧 @ {fps:.1f}fps"
        )

        # 强制刷新异步日志队列，确保步骤日志在 tqdm 进度条之前输出
        logger.complete()

        pbar = tqdm(total=total_frames, desc="压制进度", unit="帧")

        fade_out_zone = self._config.style.fade_out_zone
        total_text_spawned = 0
        total_gift_spawned = 0

        try:
            for frame_idx in range(total_frames):
                current_time = frame_idx / fps

                # 弹幕逻辑
                text_has_new, gift_has_new, text_emitted, gift_emitted = (
                    LayoutEngine.spawn_new_danmakus(
                        layout_ctx, current_time, danmaku_pool, active_text, active_gift,
                        self._asset_provider,
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
                    active_text + active_gift,
                    layout_params,
                    fade_out_zone,
                )

                # 编码
                self._encode_frame(
                    frame_encoder, renderer, pbar, frame_idx, total_frames,
                )
        finally:
            renderer.end()
            pbar.close()

        # 仅在正常完成时输出统计（异常时不会执行到这里）
        logger.info(
            f"压制完成: {total_frames} 帧, "
            f"文本弹幕 {total_text_spawned}/{total_text_danmaku}, "
            f"礼物弹幕 {total_gift_spawned}/{total_gift_danmaku}"
        )