"""DanmakuBurner 单元测试"""

from unittest.mock import patch, MagicMock

import pytest

from danmakupro.core.burner import DanmakuBurner
from danmakupro.config.models import DEFAULT_CONFIG
from danmakupro.input.event import DanmakuEvent


@pytest.fixture
def mock_deps():
    with patch("danmakupro.core.burner.validate_video_input"), \
         patch("danmakupro.core.burner.validate_xml_input"), \
         patch("danmakupro.core.burner.validate_output_path"), \
         patch("danmakupro.core.burner.AssetLoader"), \
         patch("danmakupro.core.burner.FFmpegManager"):
        yield


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
            str(video), str(xml), config=DEFAULT_CONFIG, force=True,
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
            str(video), str(xml), video_out=str(out),
            config=DEFAULT_CONFIG, force=True,
        )
        assert burner.video_out.endswith("custom.mp4")

    def test_init_creates_asset_loader(self, mock_deps, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        burner = DanmakuBurner(
            str(video), str(xml), config=DEFAULT_CONFIG, force=True,
        )
        assert burner._asset_provider is not None
        assert burner._frame_encoder is not None


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
                events, 1, 10.0, "文本弹幕", 1, 1,
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
                events, 1, 10.0, "文本弹幕", 1, 2,
            )
            call_args = mock_logger.warning.call_args[0][0]
            assert "文本弹幕未完全发射" in call_args
            assert "超出视频时长" in call_args

    def test_unspawned_blocked(self):
        events = [
            DanmakuEvent(time=0.5, user="u1", text="t1", is_gift=True, gift_name="g", gift_count=1),
            DanmakuEvent(time=5.0, user="u2", text="t2", is_gift=True, gift_name="g", gift_count=1),
        ]
        with patch("danmakupro.core.burner.logger") as mock_logger:
            DanmakuBurner._warn_unspawned(
                events, 1, 10.0, "礼物弹幕", 1, 10,
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
            DanmakuEvent(time=1.0, user="u2", text="t2", is_gift=True, gift_name="g", gift_count=1),
        ]
        ctx = MagicMock()
        ctx.text_event_idx = 1
        ctx.gift_event_idx = 2
        with patch("danmakupro.core.burner.logger") as mock_logger:
            DanmakuBurner._report_completion_stats(
                events, ctx, 30, 300, 1, 1, 1, 1, 0.0,
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
                events, ctx, 30, 300, 1, 2, 0, 0, 0.0,
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
            "w": 1920, "h": 1080, "fps": 30, "frames": 300,
        }
        mock_encoder.build_command.return_value = ["ffmpeg", "..."]

        with patch("danmakupro.core.burner.parse_xml", return_value=events), \
             patch("danmakupro.core.burner.RenderPipeline") as mock_pipeline_cls, \
             patch("danmakupro.core.burner.DanmakuLayoutBuilder"), \
             patch("danmakupro.core.burner.LayoutEngine") as mock_engine, \
             patch.object(DanmakuBurner, "_report_completion_stats"):

            mock_engine.calculate_params.return_value = (MagicMock(), MagicMock())
            mock_pipeline = MagicMock()
            mock_pipeline.run.return_value = MagicMock(
                text_spawned=1, gift_spawned=0,
                layout_ctx=MagicMock(), t_start=0.0,
                total_text_danmaku=1, total_gift_danmaku=0,
            )
            mock_pipeline_cls.return_value = mock_pipeline

            burner = DanmakuBurner(
                str(video), str(xml), video_out=str(out),
                config=DEFAULT_CONFIG, force=True,
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
            "w": 1920, "h": 1080, "fps": 30, "frames": 300,
        }
        mock_encoder.build_command.return_value = ["ffmpeg", "..."]

        with patch("danmakupro.core.burner.parse_xml", return_value=events), \
             patch("danmakupro.core.burner.RenderPipeline") as mock_pipeline_cls, \
             patch("danmakupro.core.burner.DanmakuLayoutBuilder"), \
             patch("danmakupro.core.burner.LayoutEngine") as mock_engine:

            mock_engine.calculate_params.return_value = (MagicMock(), MagicMock())
            mock_pipeline = MagicMock()
            mock_pipeline.run.side_effect = KeyboardInterrupt
            mock_pipeline_cls.return_value = mock_pipeline

            burner = DanmakuBurner(
                str(video), str(xml), video_out=str(out),
                config=DEFAULT_CONFIG, force=True,
            )
            burner._frame_encoder = mock_encoder
            burner.run()
            mock_encoder.cleanup.assert_called_once()