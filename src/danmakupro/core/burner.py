"""弹幕压制核心引擎

DanmakuBurner 是弹幕压制的编排器，负责步骤串联。
渲染管线由 RenderPipeline 负责。
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import TYPE_CHECKING

from loguru import logger

from ..config.models import DanmakuConfig, DEFAULT_CONFIG, EncodeMode
from ..errors import DanmakuProError
from ..input.parser import parse_xml
from ..layout.engine import LayoutEngine
from ..render.assets import AssetLoader
from ..render.layout_builder import DanmakuLayoutBuilder
from ..encode.ffmpeg import FFmpegManager
from ..utils.validation import validate_video_input, validate_xml_input, validate_output_path
from .pipeline import RenderPipeline

if TYPE_CHECKING:
    from ..input.event import DanmakuEvent
    from ..layout.engine import LayoutContext




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

    def run(self) -> None:
        """执行完整的弹幕压制流程。

        按顺序执行 4 个步骤：
        1. 解析弹幕 XML
        2. 加载资源文件
        3. 获取视频元数据
        4. 启动 FFmpeg 编码器 + 压制渲染

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
        logger.info(
            f"[1] 解析 XML → {len(events)} 事件"
            f" (文本 {text_count}+礼物 {len(events) - text_count}),"
            f" {t_min:.1f}~{t_max:.1f}s"
        )

        # Step 2
        self._asset_provider.load_assets(events)
        logger.info(
            f"[2] 加载资源 → "
            f"Emoji {len(self._asset_provider.emoji_cache)}, "
            f"礼物 {len(self._asset_provider.gift_cache)}"
        )

        # Step 3
        v_info = self._frame_encoder.get_video_info()
        raw_w: int = int(v_info['w'])
        raw_h: int = int(v_info['h'])
        fps: float = float(v_info['fps'])
        total_frames: int = int(v_info['frames'])

        align = syscfg.video_alignment
        w = int(((raw_w + align - 1) // align) * align)
        h = int(((raw_h + align - 1) // align) * align)

        logger.info(
            f"[3] 视频信息 → {raw_w}x{raw_h}, {fps:.0f}fps, "
            f"{total_frames} 帧 ({total_frames / fps:.0f}s)"
        )

        # Step 4-6: 布局计算、构建器初始化、编码命令（均为瞬时操作）
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
        pipeline = RenderPipeline(
            self._frame_encoder, self._config, self._asset_provider,
        )

        try:
            self._frame_encoder.start(ffmpeg_cmd)
            logger.info("[4] 准备就绪 → 启动 FFmpeg")

            result = pipeline.run(
                fps, total_frames, events, layout_builder,
                layout_params, layer_params,
            )

            DanmakuBurner._report_completion_stats(
                events, result.layout_ctx, fps, total_frames,
                result.total_text_danmaku, result.total_gift_danmaku,
                result.text_spawned, result.gift_spawned,
                result.t_start,
            )
        except KeyboardInterrupt:
            logger.warning("用户中断压制")
        except DanmakuProError:
            raise
        except Exception as e:
            raise RuntimeError(f"压制失败: {e}") from e
        finally:
            self._frame_encoder.cleanup()

    @staticmethod
    def _warn_unspawned(
        events: list[DanmakuEvent],
        start_idx: int,
        video_duration: float,
        label: str,
        spawned: int,
        total: int,
    ) -> None:
        unspawned: list[DanmakuEvent] = []
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

    @staticmethod
    def _report_completion_stats(
        events: list[DanmakuEvent],
        layout_ctx: LayoutContext,
        fps: float,
        total_frames: int,
        total_text_danmaku: int,
        total_gift_danmaku: int,
        total_text_spawned: int,
        total_gift_spawned: int,
        t_start: float,
    ) -> None:
        """输出渲染完成统计信息，包括未发射弹幕警告。

        Args:
            events: 弹幕事件列表
            layout_ctx: 布局上下文（含 text_event_idx 和 gift_event_idx）
            fps: 视频帧率
            total_frames: 总帧数
            total_text_danmaku: 文本弹幕总数
            total_gift_danmaku: 礼物弹幕总数
            total_text_spawned: 实际发射的文本弹幕数
            total_gift_spawned: 实际发射的礼物弹幕数
            t_start: 渲染开始时间（perf_counter）
        """
        elapsed = time.perf_counter() - t_start
        video_duration = total_frames / fps
        logger.info(
            f"完成: {total_frames} 帧, {elapsed:.1f}s, "
            f"弹幕 {total_text_spawned}/{total_text_danmaku} + 礼物 {total_gift_spawned}/{total_gift_danmaku}"
        )
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