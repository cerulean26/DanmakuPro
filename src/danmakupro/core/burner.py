"""弹幕压制核心引擎

DanmakuBurner 是弹幕压制的编排器，负责步骤串联。
渲染管线由 RenderPipeline 负责。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
        encode_mode: str = EncodeMode.AUTO,
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
            force: 输出文件已存在时是否跳过确认直接覆盖。为 False 时在
                交互式终端询问用户，非交互环境则拒绝覆盖（提示 -f）
            check_only: 仅做资源检查，不压制。为 True 时跳过输出路径校验 ——
                检查模式不产出任何文件，校验「输出文件已存在」没有意义，
                反而会被上一次失败留下的残缺产物挡在门外。
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

        # check_only 下不校验输出路径：见 __init__ 的 check_only 说明。
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
        """准备阶段（Step 1-3）：解析 XML、加载资源、读取视频元数据。

        check() 与 run() 共用，避免两处各写一遍近 60 行、改一处漏一处。

        ffprobe（子进程，约 0.23s）与「解析 XML → 加载资源」（约 0.33s）
        互不依赖，故把前者丢进后台线程并发执行：串行 0.56s → 并发
        max(0.33s, 0.23s)，实测省下约 0.23s 纯等待。

        Returns:
            (events, resource, v_info)。resource 为 AssetLoader.load_assets
            的返回值，v_info 为 FFmpegManager.get_video_info 的返回值。

        Raises:
            RuntimeError: 未安装 ffprobe
        """
        cfg = self._config
        with ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="prepare",
        ) as pool:
            video_info_future = pool.submit(self._frame_encoder.get_video_info)

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

            v_info = video_info_future.result()

        fps: float = float(v_info["fps"])
        total_frames: int = int(v_info["frames"])
        logger.info(
            f"[3] 视频信息 → {int(v_info['w'])}x{int(v_info['h'])}, {fps:.0f}fps, "
            f"{total_frames} 帧 ({total_frames / fps:.0f}s)"
        )

        # 用 .get 而非下标：vfr 是后加的字段，老调用方（含测试中的 mock）
        # 可能只给四个基本键，缺键时按「非 VFR」处理。
        if v_info.get("vfr"):
            # 帧率口径已按 frames/duration 修正（见 FFmpegManager
            # ._resolve_render_fps），时间轴不会漂移，这里只提示观感影响。
            logger.warning(
                "变帧率(VFR)素材：全片帧率不恒定。"
                "弹幕已按真实平均帧率生成，时间轴与画面对齐，"
                "但画面帧率波动时弹幕运动可能略有顿挫"
            )

        return events, resource, v_info

    def check(self) -> None:
        """资源完整性检查模式 —— 不执行实际压制。

        在正式压制前运行，输出以下诊断信息：
        - 视频元数据（分辨率 / 帧率 / 时长 / 总帧数）
        - 弹幕事件统计（总数 / 文本 / 礼物）
        - 字体覆盖率（缺失字符及 Unicode 码点）
        - Emoji / 礼物图片缺失清单
        - 编码器可用性（GPU / QSV / CPU）
        """
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

        # 编码器可用性（已在 __init__ 中探测）
        _PIPELINE_LABELS: dict[str, str] = {
            "gpu": "GPU (NVENC)",
            "qsv": "QSV",
            "cpu": "CPU (libx264)",
        }
        pipeline = self._frame_encoder.active_pipeline
        pipeline_label = _PIPELINE_LABELS.get(pipeline, pipeline)

        # ── 发射能力评估 ──
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

        # ── 构建报告（拼为单条消息，避免 print/log 交叉错位） ──
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
        lines.append(f"\n  ⚙️  编码器: {pipeline_label}")
        issues = 3 - ok_count
        if issues == 0:
            lines.append("\n  ✅ 所有资源完整，可以开始压制")
        else:
            lines.append(f"\n  ⚠️  {issues} 类资源不完整，压制时对应元素将显示为占位符")
        lines.append(sep)

        logger.opt(raw=True).info("\n".join(lines))

    def run(self) -> None:
        """执行完整的弹幕压制流程。

        按顺序执行 4 个步骤：
        1. 解析弹幕 XML
        2. 加载资源文件
        3. 获取视频元数据
        4. 启动 FFmpeg 编码器 + 压制渲染

        Raises:
            DanmakuProError: 弹幕压制相关的已知错误
            RuntimeError: 不可恢复的致命错误
            KeyboardInterrupt: 用户中断（记录警告后原样上抛，
                中断必须继续向上传播，否则调用方会误判为压制成功）

        Note:
            无论成功、失败还是中断，finally 块都会执行资源清理；
            中断与失败一样会删除不完整的输出文件。
        """
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

        # Step 4-6: 布局计算、构建器初始化、编码命令（均为瞬时操作）
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

        # Step 4
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
            # 标记中断，让 cleanup 不要把 FFmpeg 的退出报成「压制成功/失败」。
            self._frame_encoder.interrupted = True
            # 收尾要等 FFmpeg 退出、删除残缺产物，可能耗时，先给即时反馈。
            logger.warning("收到中断信号，正在收尾…")
            # 必须继续抛出。吞掉中断会让进程以 0 退出，脚本/编排方无法把
            # 「用户按了 Ctrl+C」和「压制成功」区分开，残缺产物也会被当成成品。
            # 资源清理由 finally 负责，抛出不影响收尾。
            raise
        except DanmakuProError:
            failed = True
            raise
        except Exception as e:
            failed = True
            # 用 ErrorHandler.classify 保留原始异常的类别，而不是一律包成
            # RuntimeError（那会让 _classify_error 把一切都归为 RENDER）。
            raise DanmakuProError(
                f"压制失败: {e}",
                category=ErrorHandler.classify(e),
                context=ErrorContext(component="burner", operation="run"),
            ) from e
        finally:
            # 中断可能恰好落在收尾期间：Ctrl+C 会同时送达 Python 与
            # ffmpeg，两者到达时刻有先后，若中断在 cleanup() 等待 FFmpeg
            # 退出时到达，就会从 finally 中抛出，跳过后面的产物清理 ——
            # 残缺文件留下，下次运行又被「输出文件已存在」挡住。
            # 嵌套 try/finally 保证无论收尾是否被打断，清理都会执行。
            try:
                self._frame_encoder.cleanup()
            finally:
                if failed or not self._frame_encoder.encode_succeeded:
                    self._discard_incomplete_output()

    def _discard_incomplete_output(self) -> None:
        """删除未成功完成时留下的残缺输出文件。

        失败或中断后残留的 0 字节（或半截）mp4 会让下次运行卡在
        「输出文件已存在」，而用户往往不知道那是上一次失败留下的产物。
        成功路径不会调用本方法。

        删除失败只警告不抛出：清理失败不应掩盖真正的压制错误。
        """
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
