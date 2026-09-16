"""DanmakuBurner 单元测试"""

from contextlib import contextmanager
from typing import cast
from unittest.mock import patch, MagicMock
import sys

import pytest

from danmakupro.config.models import AnimationParams, DanmakuConfig, DEFAULT_CONFIG
from danmakupro.core.burner import DanmakuBurner
from danmakupro.errors import DanmakuProError, ErrorCategory, InputError
from danmakupro.input.event import DanmakuEvent


class _Stdin:
    """stdin 替身：isatty() 固定返回给定值，用于模拟终端 / 管道两种环境。"""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def mock_deps():
    with (
        patch("danmakupro.core.burner.validate_video_input"),
        patch("danmakupro.core.burner.validate_xml_input"),
        patch("danmakupro.core.burner.validate_output_path"),
        patch("danmakupro.core.burner.AssetLoader"),
        patch("danmakupro.core.burner.FFmpegManager"),
    ):
        yield


# =============================================================================
# 测试辅助
# =============================================================================


def _mk_resource(
    *,
    used_emoji=(),
    missing_emoji=(),
    used_gift=(),
    missing_gift=(),
    missing_chars=(),
    total_chars=0,
):
    """构造 AssetLoader.load_assets 的返回值。"""
    return {
        "used_emoji": set(used_emoji),
        "missing_emoji": set(missing_emoji),
        "used_gift": set(used_gift),
        "missing_gift": set(missing_gift),
        "missing_chars": set(missing_chars),
        "total_chars": total_chars,
    }


def _mk_vinfo(*, w=1920, h=1080, fps=30, frames=3000, vfr=False):
    """构造 FFmpegManager.get_video_info 的返回值（3000 帧 @30fps = 100s）。"""
    return {"w": w, "h": h, "fps": fps, "frames": frames, "vfr": vfr}


def _make_run_burner(mock_deps, tmp_path):
    """构造已接好 mock 编码器的 burner。

    返回值里的 out 文件是**预先存在的**，用来模拟上次失败留下的残缺产物，
    以便断言失败路径确实把它清掉了。
    """
    video = tmp_path / "test.mp4"
    video.touch()
    xml = tmp_path / "test.xml"
    xml.touch()
    out = tmp_path / "out.mp4"
    out.touch()

    burner = DanmakuBurner(
        str(video),
        str(xml),
        video_out=str(out),
        config=DEFAULT_CONFIG,
        force=True,
    )
    encoder = MagicMock()
    encoder.get_video_info.return_value = _mk_vinfo()
    encoder.build_command.return_value = ["ffmpeg", "..."]
    burner._frame_encoder = encoder
    cast(MagicMock, burner._asset_provider).load_assets.return_value = _mk_resource()
    return burner, out


@contextmanager
def _patch_run_deps(events, *, side_effect):
    """patch 掉 run() 的渲染依赖，并让 pipeline.run 抛出指定异常。"""
    with (
        patch("danmakupro.core.burner.parse_xml", return_value=events),
        patch("danmakupro.core.burner.RenderPipeline") as mock_pipeline_cls,
        patch("danmakupro.core.burner.DanmakuLayoutBuilder"),
        patch("danmakupro.core.burner.LayoutEngine") as mock_engine,
    ):
        mock_engine.calculate_params.return_value = (MagicMock(), MagicMock())
        mock_pipeline = MagicMock()
        mock_pipeline.run.side_effect = side_effect
        mock_pipeline_cls.return_value = mock_pipeline
        yield mock_pipeline


# =============================================================================
# __init__
# =============================================================================


class TestBurnerInit:
    def test_default_output_path(self, mock_deps, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        burner = DanmakuBurner(
            str(video),
            str(xml),
            config=DEFAULT_CONFIG,
            force=True,
        )
        assert burner.video_out.endswith("-弹幕版.mp4")
        assert "test-弹幕版.mp4" in burner.video_out

    def test_custom_output_path(self, mock_deps, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        out = tmp_path / "custom.mp4"
        out.touch()
        burner = DanmakuBurner(
            str(video),
            str(xml),
            video_out=str(out),
            config=DEFAULT_CONFIG,
            force=True,
        )
        assert burner.video_out.endswith("custom.mp4")

    def test_init_creates_asset_loader(self, mock_deps, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        burner = DanmakuBurner(
            str(video),
            str(xml),
            config=DEFAULT_CONFIG,
            force=True,
        )
        assert burner._asset_provider is not None
        assert burner._frame_encoder is not None

    # 以下两条刻意不 mock validate_output_path —— 要验证的正是「输出文件已
    # 存在」这条真实链路（询问 → 分叉），以及分叉发生在创建任何组件之前。

    def test_rejected_overwrite_aborts_before_building(self, tmp_path, monkeypatch):
        """拒绝覆盖时构造应中止，且不创建 AssetLoader / FFmpegManager。"""
        monkeypatch.setattr(sys, "stdin", _Stdin(tty=False))
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        out = tmp_path / "out.mp4"
        out.touch()

        with (
            patch("danmakupro.core.burner.AssetLoader") as mock_assets,
            patch("danmakupro.core.burner.FFmpegManager") as mock_encoder,
        ):
            with pytest.raises(InputError, match="已取消覆盖"):
                DanmakuBurner(
                    str(video),
                    str(xml),
                    video_out=str(out),
                    config=DEFAULT_CONFIG,
                )

        mock_assets.assert_not_called()
        mock_encoder.assert_not_called()

    def test_accepted_overwrite_proceeds(self, tmp_path, monkeypatch):
        """交互式回答 y 时，同名文件不再阻挡构造。"""
        monkeypatch.setattr(sys, "stdin", _Stdin(tty=True))
        monkeypatch.setattr("builtins.input", lambda *a: "y")
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        out = tmp_path / "out.mp4"
        out.touch()

        with (
            patch("danmakupro.core.burner.AssetLoader"),
            patch("danmakupro.core.burner.FFmpegManager"),
        ):
            burner = DanmakuBurner(
                str(video),
                str(xml),
                video_out=str(out),
                config=DEFAULT_CONFIG,
            )

        assert burner.video_out == out.as_posix()


# =============================================================================
# _warn_unspawned
# =============================================================================


class TestWarnUnspawned:
    def test_no_unspawned(self):
        events = [
            DanmakuEvent(time=0.5, user="u1", text="t1"),
        ]
        with patch("danmakupro.core.burner.logger") as mock_logger:
            DanmakuBurner._warn_unspawned(
                events,
                1,
                10.0,
                "文本弹幕",
                1,
                1,
            )
            call_args = mock_logger.warning.call_args[0][0]
            assert "文本弹幕未完全发射: 1/1" in call_args

    def test_unspawned_beyond_duration(self):
        events = [
            DanmakuEvent(time=0.5, user="u1", text="t1"),
            DanmakuEvent(time=15.0, user="u2", text="t2"),
        ]
        with patch("danmakupro.core.burner.logger") as mock_logger:
            DanmakuBurner._warn_unspawned(
                events,
                1,
                10.0,
                "文本弹幕",
                1,
                2,
            )
            call_args = mock_logger.warning.call_args[0][0]
            assert "文本弹幕未完全发射" in call_args
            assert "超出视频时长" in call_args

    def test_unspawned_blocked(self):
        events = [
            DanmakuEvent(
                time=0.5,
                user="u1",
                text="t1",
                is_gift=True,
                gift_name="g",
                gift_count=1,
            ),
            DanmakuEvent(
                time=5.0,
                user="u2",
                text="t2",
                is_gift=True,
                gift_name="g",
                gift_count=1,
            ),
        ]
        with patch("danmakupro.core.burner.logger") as mock_logger:
            DanmakuBurner._warn_unspawned(
                events,
                1,
                10.0,
                "礼物弹幕",
                1,
                10,
            )
            call_args = mock_logger.warning.call_args[0][0]
            assert "礼物弹幕未完全发射" in call_args
            assert "被批次限制阻塞" in call_args


# =============================================================================
# _report_completion_stats
# =============================================================================


class TestReportCompletionStats:
    def test_all_spawned(self):
        events = [
            DanmakuEvent(time=0.5, user="u1", text="t1"),
            DanmakuEvent(
                time=1.0,
                user="u2",
                text="t2",
                is_gift=True,
                gift_name="g",
                gift_count=1,
            ),
        ]
        ctx = MagicMock()
        ctx.text_event_idx = 1
        ctx.gift_event_idx = 2
        with patch("danmakupro.core.burner.logger") as mock_logger:
            DanmakuBurner._report_completion_stats(
                events,
                ctx,
                30,
                300,
                1,
                1,
                1,
                1,
                0.0,
            )
            mock_logger.info.assert_called_once()

    def test_text_not_all_spawned(self):
        events = [
            DanmakuEvent(time=0.5, user="u1", text="t1"),
            DanmakuEvent(time=1.0, user="u2", text="t2"),
        ]
        ctx = MagicMock()
        ctx.text_event_idx = 1
        ctx.gift_event_idx = 0
        with patch("danmakupro.core.burner.logger") as mock_logger:
            DanmakuBurner._report_completion_stats(
                events,
                ctx,
                30,
                300,
                1,
                2,
                0,
                0,
                0.0,
            )
            assert mock_logger.warning.called


# =============================================================================
# run
# =============================================================================


class TestBurnerRun:
    def test_run_flow(self, mock_deps, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        out = tmp_path / "out.mp4"
        out.touch()

        events = [DanmakuEvent(time=0.5, user="u", text="hello")]
        mock_encoder = MagicMock()
        mock_encoder.get_video_info.return_value = {
            "w": 1920,
            "h": 1080,
            "fps": 30,
            "frames": 300,
            "vfr": False,
        }
        mock_encoder.build_command.return_value = ["ffmpeg", "..."]

        with (
            patch("danmakupro.core.burner.parse_xml", return_value=events),
            patch("danmakupro.core.burner.RenderPipeline") as mock_pipeline_cls,
            patch("danmakupro.core.burner.DanmakuLayoutBuilder"),
            patch("danmakupro.core.burner.LayoutEngine") as mock_engine,
            patch.object(DanmakuBurner, "_report_completion_stats"),
        ):
            mock_engine.calculate_params.return_value = (MagicMock(), MagicMock())
            mock_pipeline = MagicMock()
            mock_pipeline.run.return_value = MagicMock(
                text_spawned=1,
                gift_spawned=0,
                layout_ctx=MagicMock(),
                t_start=0.0,
                total_text_danmaku=1,
                total_gift_danmaku=0,
            )
            mock_pipeline_cls.return_value = mock_pipeline

            burner = DanmakuBurner(
                str(video),
                str(xml),
                video_out=str(out),
                config=DEFAULT_CONFIG,
                force=True,
            )
            burner._frame_encoder = mock_encoder
            burner.run()

            mock_encoder.start.assert_called_once()
            mock_encoder.cleanup.assert_called_once()
            mock_pipeline.run.assert_called_once()

    def test_run_keyboard_interrupt(self, mock_deps, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        out = tmp_path / "out.mp4"
        out.touch()

        events = [DanmakuEvent(time=0.5, user="u", text="hello")]
        mock_encoder = MagicMock()
        mock_encoder.get_video_info.return_value = {
            "w": 1920,
            "h": 1080,
            "fps": 30,
            "frames": 300,
            "vfr": False,
        }
        mock_encoder.build_command.return_value = ["ffmpeg", "..."]

        with (
            patch("danmakupro.core.burner.parse_xml", return_value=events),
            patch("danmakupro.core.burner.RenderPipeline") as mock_pipeline_cls,
            patch("danmakupro.core.burner.DanmakuLayoutBuilder"),
            patch("danmakupro.core.burner.LayoutEngine") as mock_engine,
        ):
            mock_engine.calculate_params.return_value = (MagicMock(), MagicMock())
            mock_pipeline = MagicMock()
            mock_pipeline.run.side_effect = KeyboardInterrupt
            mock_pipeline_cls.return_value = mock_pipeline

            burner = DanmakuBurner(
                str(video),
                str(xml),
                video_out=str(out),
                config=DEFAULT_CONFIG,
                force=True,
            )
            burner._frame_encoder = mock_encoder
            # 中断必须继续上抛：吞掉它会让进程以 0 退出，调用方无法区分
            # 「用户取消」与「压制成功」。
            with pytest.raises(KeyboardInterrupt):
                burner.run()
            # 上抛前仍要完成收尾
            mock_encoder.cleanup.assert_called_once()
            # 中断同失败：不允许留下残缺产物挡住下次运行
            assert not out.exists()

    def test_discards_output_when_interrupt_hits_cleanup(
        self,
        mock_deps,
        tmp_path,
    ):
        """中断恰好落在收尾期间时，产物清理不能被跳过。

        Ctrl+C 会同时送达 Python 与 ffmpeg，两者到达时刻有先后。若中断在
        cleanup() 等待 FFmpeg 退出时到达，就会从 finally 中抛出；此时若
        清理代码与 cleanup() 是串行的，残缺文件就会留下，下次运行又被
        「输出文件已存在」挡住 —— 即 P1-5 修过的问题复发。
        """
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        out = tmp_path / "out.mp4"
        out.touch()

        events = [DanmakuEvent(time=0.5, user="u", text="hello")]
        mock_encoder = MagicMock()
        mock_encoder.get_video_info.return_value = {
            "w": 1920,
            "h": 1080,
            "fps": 30,
            "frames": 300,
            "vfr": False,
        }
        mock_encoder.build_command.return_value = ["ffmpeg", "..."]
        # 模拟中断在收尾期间抵达
        mock_encoder.cleanup.side_effect = KeyboardInterrupt

        with (
            patch("danmakupro.core.burner.parse_xml", return_value=events),
            patch("danmakupro.core.burner.RenderPipeline") as mock_pipeline_cls,
            patch("danmakupro.core.burner.DanmakuLayoutBuilder"),
            patch("danmakupro.core.burner.LayoutEngine") as mock_engine,
        ):
            mock_engine.calculate_params.return_value = (MagicMock(), MagicMock())
            mock_pipeline = MagicMock()
            mock_pipeline.run.side_effect = KeyboardInterrupt
            mock_pipeline_cls.return_value = mock_pipeline

            burner = DanmakuBurner(
                str(video),
                str(xml),
                video_out=str(out),
                config=DEFAULT_CONFIG,
                force=True,
            )
            burner._frame_encoder = mock_encoder
            with pytest.raises(KeyboardInterrupt):
                burner.run()
            # 收尾被打断，但产物清理仍必须完成
            assert not out.exists()

    def test_run_reraises_danmakupro_error_as_is(self, mock_deps, tmp_path):
        """已知错误（DanmakuProError 及其子类）原样上抛，不二次包装。"""
        burner, out = _make_run_burner(mock_deps, tmp_path)
        events = [DanmakuEvent(time=0.5, user="u", text="hi")]
        original = InputError("坏输入")

        with _patch_run_deps(events, side_effect=original):
            with pytest.raises(InputError) as exc_info:
                burner.run()

        # 同一个对象，category / context 未被破坏
        assert exc_info.value is original
        assert exc_info.value.category is ErrorCategory.INPUT
        # 失败路径同样要清掉残缺产物
        assert not out.exists()

    def test_run_wraps_unexpected_exception(self, mock_deps, tmp_path):
        """未知异常包装为 DanmakuProError，但保留原始异常的类别。"""
        burner, out = _make_run_burner(mock_deps, tmp_path)
        events = [DanmakuEvent(time=0.5, user="u", text="hi")]

        with _patch_run_deps(events, side_effect=ValueError("bad frame")):
            with pytest.raises(DanmakuProError) as exc_info:
                burner.run()

        assert "压制失败: bad frame" in str(exc_info.value)
        # ValueError → INPUT。若一律包成 RuntimeError 会变成 RENDER，分类失真。
        assert exc_info.value.category is ErrorCategory.INPUT
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert not out.exists()


# =============================================================================
# _discard_incomplete_output
# =============================================================================


class TestDiscardIncompleteOutput:
    def _make_burner(self, mock_deps, tmp_path, out_name):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        return DanmakuBurner(
            str(video),
            str(xml),
            video_out=str(tmp_path / out_name),
            config=DEFAULT_CONFIG,
            force=True,
        )

    def test_missing_file_is_noop(self, mock_deps, tmp_path):
        burner = self._make_burner(mock_deps, tmp_path, "nope.mp4")
        with patch("danmakupro.core.burner.logger") as mock_logger:
            burner._discard_incomplete_output()
            # 文件本就不存在：既不报错也不打日志
            mock_logger.warning.assert_not_called()

    def test_unlink_failure_only_warns(self, mock_deps, tmp_path):
        burner = self._make_burner(mock_deps, tmp_path, "out.mp4")
        out = tmp_path / "out.mp4"
        out.touch()

        with (
            patch("pathlib.Path.unlink", side_effect=OSError("拒绝访问")),
            patch("danmakupro.core.burner.logger") as mock_logger,
        ):
            burner._discard_incomplete_output()

            assert "无法删除" in mock_logger.warning.call_args[0][0]
        # 清理失败只告警不抛出，且不能误报「已删除」
        assert out.exists()


# =============================================================================
# check
# =============================================================================


def _text_events(count, *, step=1.0):
    return [DanmakuEvent(time=i * step, user="u", text=f"t{i}") for i in range(count)]


def _gift_event(t=1.5):
    return DanmakuEvent(
        time=t,
        user="u",
        text="",
        is_gift=True,
        gift_name="火箭",
        gift_count=1,
    )


@pytest.fixture
def make_check_burner(mock_deps, tmp_path):
    """构造可直接跑 check() 的 burner，依赖全部可注入。"""

    def _build(*, events, resource, v_info, pipeline="gpu", config=DEFAULT_CONFIG):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        burner = DanmakuBurner(
            str(video),
            str(xml),
            video_out=str(tmp_path / "out.mp4"),
            config=config,
            force=True,
        )
        encoder = MagicMock()
        encoder.get_video_info.return_value = v_info
        encoder.active_pipeline = pipeline
        burner._frame_encoder = encoder
        cast(MagicMock, burner._asset_provider).load_assets.return_value = resource
        return burner

    return _build


def _run_check(burner, events):
    """跑一次 check()，返回报告的行列表（check 把整份报告拼成单条日志）。"""
    with (
        patch("danmakupro.core.burner.parse_xml", return_value=events),
        patch("danmakupro.core.burner.logger") as mock_logger,
    ):
        burner.check()
        raw = mock_logger.opt.return_value.info.call_args[0][0]
    return raw.split("\n")


def _verdict_line(lines, prefix):
    """取「文本:」/「礼物:」那一行的下一行 —— 即发射能力判定。"""
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            return lines[i + 1]
    raise AssertionError(f"报告里没有以 {prefix!r} 开头的行")


class TestCheck:
    def test_all_clean(self, make_check_burner):
        events = [
            DanmakuEvent(time=0.5, user="u1", text="hello"),
            DanmakuEvent(time=1.0, user="u2", text="world"),
            _gift_event(),
        ]
        burner = make_check_burner(
            events=events,
            resource=_mk_resource(
                used_emoji=["微笑"], used_gift=["火箭"], total_chars=8
            ),
            v_info=_mk_vinfo(),
        )

        text = "\n".join(_run_check(burner, events))

        assert "文本 2, 礼物 1" in text
        assert "✅ 全部字符已覆盖" in text
        assert "✅ 全部已加载" in text
        assert "编码器: GPU (NVENC)" in text
        assert "所有资源完整，可以开始压制" in text
        # 100s 只有 3 条事件，远低于 6 条/秒的基础能力
        assert "冗余" in text

    def test_reports_missing_resources(self, make_check_burner):
        events = [DanmakuEvent(time=0.5, user="u1", text="囧")]
        burner = make_check_burner(
            events=events,
            resource=_mk_resource(
                used_emoji=["微笑"],
                missing_emoji=["微笑"],
                used_gift=["火箭"],
                missing_gift=["火箭"],
                missing_chars=["囧"],
                total_chars=1,
            ),
            v_info=_mk_vinfo(),
        )

        text = "\n".join(_run_check(burner, events))

        assert "3 类资源不完整" in text
        assert "1 个字符无字体覆盖" in text
        assert "❌ 微笑" in text
        assert "❌ 火箭" in text
        # 字符缺失时打印 Unicode 码点，便于排查字体
        assert "U+56E7" in text

    def test_unused_assets_reported(self, make_check_burner):
        events = [DanmakuEvent(time=0.5, user="u1", text="hi")]
        burner = make_check_burner(
            events=events,
            resource=_mk_resource(),
            v_info=_mk_vinfo(),
        )

        text = "\n".join(_run_check(burner, events))

        assert "未使用" in text
        assert "所有资源完整" in text

    def test_empty_events(self, make_check_burner):
        burner = make_check_burner(
            events=[],
            resource=_mk_resource(),
            v_info=_mk_vinfo(),
        )

        text = "\n".join(_run_check(burner, []))

        # 无事件时时间范围按 0.0 兜底，不能抛 IndexError
        assert "弹幕: 0 条" in text
        assert "时间范围: 0.0s ~ 0.0s" in text

    def test_unknown_pipeline_label_passthrough(self, make_check_burner):
        events = [DanmakuEvent(time=0.5, user="u1", text="hi")]
        burner = make_check_burner(
            events=events,
            resource=_mk_resource(),
            v_info=_mk_vinfo(),
            pipeline="weird-pipeline",
        )

        text = "\n".join(_run_check(burner, events))

        # 未在标签表里的管线名原样输出，而不是 KeyError
        assert "编码器: weird-pipeline" in text

    def test_text_headroom_near_bottleneck(self, make_check_burner):
        # 基础能力 3 / 0.5 = 6 条/秒；12 条 / 3s = 4 条/秒 → 冗余 1.5x
        events = _text_events(12, step=0.2)
        burner = make_check_burner(
            events=events,
            resource=_mk_resource(),
            v_info=_mk_vinfo(frames=90),  # 3.0s
        )

        lines = _run_check(burner, events)

        assert "接近瓶颈，自适应加速可兜底" in _verdict_line(lines, "文本:")

    def test_text_over_capacity_uses_adaptive(self, make_check_burner):
        # 基础能力 6 条/秒；12 条 / 1s = 12 条/秒 → 冗余 0.5x，需自适应兜底
        events = _text_events(12, step=0.05)
        burner = make_check_burner(
            events=events,
            resource=_mk_resource(),
            v_info=_mk_vinfo(frames=30),  # 1.0s
        )

        lines = _run_check(burner, events)
        verdict = _verdict_line(lines, "文本:")

        assert "依赖自适应加速" in verdict
        assert "max_latency=2.0s" in verdict

    def test_over_capacity_adaptive_disabled(self, make_check_burner):
        cfg = DanmakuConfig(animation=AnimationParams(max_spawn_latency=None))
        events = _text_events(12, step=0.05)
        burner = make_check_burner(
            events=events,
            resource=_mk_resource(),
            v_info=_mk_vinfo(frames=30),  # 1.0s → 同样 0.5x
            config=cfg,
        )

        lines = _run_check(burner, events)

        # 禁用自适应时必须明确告知「会丢弹幕」，不能只报接近瓶颈
        assert "自适应已禁用，将丢弃弹幕" in _verdict_line(lines, "文本:")

    def test_zero_duration_does_not_crash(self, make_check_burner):
        events = [DanmakuEvent(time=0.5, user="u1", text="hi")]
        burner = make_check_burner(
            events=events,
            resource=_mk_resource(),
            v_info=_mk_vinfo(frames=0),
        )

        lines = _run_check(burner, events)

        # duration 为 0 时需求按 0 计（兜底分支），不能除零崩溃
        assert "冗余" in _verdict_line(lines, "文本:")

    def test_vfr_warning_logged(self, make_check_burner):
        """VFR 素材要给出提示：帧率口径已修正，但画面观感可能顿挫。"""
        events = [DanmakuEvent(time=0.5, user="u1", text="hi")]
        burner = make_check_burner(
            events=events,
            resource=_mk_resource(),
            v_info=_mk_vinfo(vfr=True),
        )

        with (
            patch("danmakupro.core.burner.parse_xml", return_value=events),
            patch("danmakupro.core.burner.logger") as mock_logger,
        ):
            burner.check()
            warnings = [str(c.args[0]) for c in mock_logger.warning.call_args_list]

        assert any("变帧率(VFR)素材" in w for w in warnings)
