"""弹幕压制核心引擎"""

from __future__ import annotations

from pathlib import Path
import time
from typing import TYPE_CHECKING

from loguru import logger

from ..config.models import DanmakuConfig, DEFAULT_CONFIG, EncodeMode
from ..errors import DanmakuProError, ErrorContext, ErrorHandler
from ..input.parser import parse_xml
from ..layout.engine import LayoutEngine
from ..render.assets import AssetLoader
from ..render.layout_builder import DanmakuLayoutBuilder
from ..encode.capability import pipeline_label
from ..encode.ffmpeg import FFmpegManager
from ..utils.validation import (
    validate_video_input,
    validate_xml_input,
    validate_output_path,
)
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
        encode_mode: str = EncodeMode.H264,
        config: DanmakuConfig = DEFAULT_CONFIG,
        force: bool = False,
        check_only: bool = False,
    ):
        """初始化弹幕压制引擎
        Args:
            video_in: 输入视频路径
            xml_in: 输入弹幕 XML 文件路径
            video_out: 输出视频路径
            encode_mode: 编码模式
            config: 弹幕配置
            force: 输出文件已存在时是否跳过确认直接覆盖
            check_only: 仅做资源检查，不压制（跳过输出路径校验以避免被残留文件阻挡）
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

        if not check_only:
            validate_output_path(self.video_out, force)

        self._asset_provider = AssetLoader(
            font_size=self._config.style.font_size,
            assets_dir=self._config.system.assets_dir,
        )
        self._frame_encoder = FFmpegManager(
            video_in,
            self.video_out,
            encode_mode,
            self._config.encode,
            self._config.system,
        )

    def _prepare_events_and_video_info(
        self,
    ) -> tuple[list[DanmakuEvent], dict, dict]:
        """解析 XML、加载资源、读取视频元数据，check() 与 run() 共用。"""
        cfg = self._config
        events = parse_xml(self.xml_in, min_gift_price=cfg.animation.min_gift_price)
        text_count = sum(1 for e in events if not e.is_gift)
        t_min = events[0].time if events else 0.0
        t_max = events[-1].time if events else 0.0
        logger.info(
            f"[1] 解析 XML → {len(events)} 事件"
            f" (文本 {text_count}+礼物 {len(events) - text_count}),"
            f" {t_min:.1f}~{t_max:.1f}s"
        )

        resource = self._asset_provider.load_assets(events)
        emoji_used = len(resource["used_emoji"])
        emoji_missing = len(resource["missing_emoji"])
        gift_used = len(resource["used_gift"])
        gift_missing = len(resource["missing_gift"])
        logger.info(
            f"[2] 加载资源 → "
            f"Emoji {emoji_used - emoji_missing}/{emoji_used}, "
            f"礼物 {gift_used - gift_missing}/{gift_used}"
        )

        v_info = self._frame_encoder.get_video_info()

        fps: float = float(v_info["fps"])
        total_frames: int = int(v_info["frames"])
        logger.info(
            f"[3] 视频信息 → {int(v_info['w'])}x{int(v_info['h'])}, {fps:.0f}fps, "
            f"{total_frames} 帧 ({total_frames / fps:.0f}s)"
        )

        return events, resource, v_info

    def check(self) -> None:
        """资源完整性检查，不执行实际压制。"""
        cfg = self._config
        events, resource, v_info = self._prepare_events_and_video_info()

        text_count = sum(1 for e in events if not e.is_gift)
        gift_count = len(events) - text_count
        t_min = events[0].time if events else 0.0
        t_max = events[-1].time if events else 0.0

        raw_w: int = int(v_info["w"])
        raw_h: int = int(v_info["h"])
        fps: float = float(v_info["fps"])
        total_frames: int = int(v_info["frames"])
        duration = total_frames / fps

        pipeline = self._frame_encoder.active_pipeline
        pl_label = pipeline_label(pipeline)

        anim = cfg.animation
        text_rate = text_count / duration if duration > 0 else 0
        gift_rate = gift_count / duration if duration > 0 else 0
        text_cap = anim.text_spawn_batch_size / anim.text_spawn_interval
        gift_cap = anim.gift_spawn_batch_size / anim.gift_spawn_interval
        text_headroom = text_cap / text_rate if text_rate > 0 else float("inf")
        gift_headroom = gift_cap / gift_rate if gift_rate > 0 else float("inf")

        def _headroom_verdict(headroom: float, lat: float | None) -> str:
            if headroom >= 2:
                return f"     ✅ 冗余 {headroom:.0f}x，可全部发射"
            if headroom >= 1:
                return "     ⚠️  接近瓶颈，自适应加速可兜底"
            if lat is not None:
                return f"     ⚠️  超出基础能力，依赖自适应加速 (max_latency={lat}s)"
            return "     ❌ 超出基础能力且自适应已禁用，将丢弃弹幕"

        missing_chars: set[str] = resource["missing_chars"]

        def _asset_lines(label: str, used: set, missing: set) -> list[str]:
            ok = len(used) - len(missing)
            lines = [f"\n  🖼️  {label}: {ok}/{len(used)}"]
            if missing:
                for name in sorted(missing):
                    lines.append(f"     ❌ {name}")
            elif used:
                lines.append("     ✅ 全部已加载")
            else:
                lines.append("     ℹ️  未使用")
            return lines

        ok_count = sum(
            [
                len(missing_chars) == 0,
                len(resource["missing_emoji"]) == 0,
                len(resource["missing_gift"]) == 0,
            ]
        )

        lines: list[str] = []
        sep = "=" * 60
        lines.append("")
        lines.append(sep)
        lines.append("  资源完整性检查报告")
        lines.append(sep)
        lines.append(
            f"\n  📹 视频: {raw_w}x{raw_h} @ {fps:.0f}fps, "
            f"{duration:.0f}s ({total_frames} 帧)"
        )
        lines.append(
            f"\n  💬 弹幕: {len(events)} 条 (文本 {text_count}, 礼物 {gift_count})"
        )
        lines.append(f"     时间范围: {t_min:.1f}s ~ {t_max:.1f}s")
        lines.append("\n  🚀 发射能力评估:")
        lines.append(
            f"     文本: {text_rate:.1f} 条/秒 (需求) vs {text_cap:.0f} 条/秒 (基础能力)"
        )
        lines.append(_headroom_verdict(text_headroom, anim.max_spawn_latency))
        lines.append(
            f"     礼物: {gift_rate:.1f} 条/秒 (需求) vs {gift_cap:.0f} 条/秒 (基础能力)"
        )
        lines.append(_headroom_verdict(gift_headroom, anim.max_spawn_latency))
        lines.append(f"\n  🔤 字体覆盖: {resource['total_chars']} 个不同字符")
        if missing_chars:
            lines.append(f"     ❌ {len(missing_chars)} 个字符无字体覆盖:")
            for c in sorted(missing_chars):
                lines.append(f"        {c!r}  (U+{ord(c):04X})")
        else:
            lines.append("     ✅ 全部字符已覆盖")
        lines.extend(
            _asset_lines(
                "Emoji 图片", resource["used_emoji"], resource["missing_emoji"]
            )
        )
        lines.extend(
            _asset_lines("礼物图片", resource["used_gift"], resource["missing_gift"])
        )
        lines.append(f"\n  ⚙️  编码器: {pl_label}")
        issues = 3 - ok_count
        if issues == 0:
            lines.append("\n  ✅ 所有资源完整，可以开始压制")
        else:
            lines.append(f"\n  ⚠️  {issues} 类资源不完整，压制时对应元素将显示为占位符")
        lines.append(sep)

        logger.opt(raw=True).info("\n".join(lines))

    def run(self) -> None:
        """执行完整的弹幕压制流程。"""
        cfg = self._config
        style = cfg.style
        syscfg = cfg.system

        events, _resource, v_info = self._prepare_events_and_video_info()

        raw_w: int = int(v_info["w"])
        raw_h: int = int(v_info["h"])
        fps: float = float(v_info["fps"])
        total_frames: int = int(v_info["frames"])

        align = syscfg.video_alignment
        w = int(((raw_w + align - 1) // align) * align)
        h = int(((raw_h + align - 1) // align) * align)

        layout_params, layer_params = LayoutEngine.calculate_params(
            w,
            h,
            style,
            cfg.ratio,
            self._asset_provider.line_height,
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

        pipeline = RenderPipeline(
            self._frame_encoder,
            self._config,
            self._asset_provider,
        )

        failed = False
        try:
            self._frame_encoder.start(ffmpeg_cmd)
            logger.info("[4] 准备就绪 → 启动 FFmpeg")

            result = pipeline.run(
                fps,
                total_frames,
                events,
                layout_builder,
                layout_params,
                layer_params,
            )

            DanmakuBurner._report_completion_stats(
                events,
                result.layout_ctx,
                fps,
                total_frames,
                result.total_text_danmaku,
                result.total_gift_danmaku,
                result.text_spawned,
                result.gift_spawned,
                result.t_start,
            )
        except KeyboardInterrupt:
            failed = True
            self._frame_encoder.interrupted = True
            logger.warning("收到中断信号，正在收尾…")
            raise
        except DanmakuProError:
            failed = True
            raise
        except Exception as e:
            failed = True
            raise DanmakuProError(
                f"压制失败: {e}",
                category=ErrorHandler.classify(e),
                context=ErrorContext(component="burner", operation="run"),
            ) from e
        finally:
            try:
                self._frame_encoder.cleanup()
            finally:
                if failed or not self._frame_encoder.encode_succeeded:
                    self._discard_incomplete_output()

    def _discard_incomplete_output(self) -> None:
        """删除失败或中断后残留的残缺输出文件。"""
        path = Path(self.video_out)
        if not path.exists():
            return
        try:
            path.unlink()
        except OSError as e:
            logger.warning(f"无法删除不完整的输出文件 {path}: {e}")
            return
        logger.warning(f"已删除未完成的输出文件: {path}")

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
        """输出渲染完成统计与未发射弹幕警告。"""
        elapsed = time.perf_counter() - t_start
        video_duration = total_frames / fps
        logger.info(
            f"完成: {total_frames} 帧, {elapsed:.1f}s, "
            f"弹幕 {total_text_spawned}/{total_text_danmaku} + 礼物 {total_gift_spawned}/{total_gift_danmaku}"
        )
        if total_text_spawned < total_text_danmaku:
            DanmakuBurner._warn_unspawned(
                events,
                layout_ctx.text_event_idx,
                video_duration,
                "文本弹幕",
                total_text_spawned,
                total_text_danmaku,
            )
        if total_gift_spawned < total_gift_danmaku:
            DanmakuBurner._warn_unspawned(
                events,
                layout_ctx.gift_event_idx,
                video_duration,
                "礼物弹幕",
                total_gift_spawned,
                total_gift_danmaku,
            )