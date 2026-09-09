"""CLI 入口单元测试"""

from unittest.mock import patch, MagicMock

import pytest

from danmakupro.cli import main
from danmakupro.config.models import EncodeMode


class TestCLIMain:

    def test_help_exits(self):
        with patch("sys.argv", ["danmakupro", "--help"]):
            with pytest.raises(SystemExit):
                main()

    def test_missing_args_exits(self):
        with patch("sys.argv", ["danmakupro"]):
            with pytest.raises(SystemExit):
                main()

    def test_basic_arguments(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with patch("sys.argv", ["danmakupro", str(video), str(xml)]), \
             patch("danmakupro.cli.load_config") as mock_load_config, \
             patch("danmakupro.cli.configure_logger"), \
             patch("danmakupro.cli.ensure_qt_app"), \
             patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls, \
             patch("danmakupro.cli.QApplication"):

            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            mock_burner_cls.assert_called_once()
            mock_burner.run.assert_called_once()

    def test_force_flag(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with patch("sys.argv", ["danmakupro", str(video), str(xml), "-f"]), \
             patch("danmakupro.cli.load_config") as mock_load_config, \
             patch("danmakupro.cli.configure_logger"), \
             patch("danmakupro.cli.ensure_qt_app"), \
             patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls, \
             patch("danmakupro.cli.QApplication"):

            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            call_kwargs = mock_burner_cls.call_args[1]
            assert call_kwargs["force"] is True

    def test_encode_mode(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with patch("sys.argv", ["danmakupro", str(video), str(xml), "--encode", "cpu"]), \
             patch("danmakupro.cli.load_config") as mock_load_config, \
             patch("danmakupro.cli.configure_logger"), \
             patch("danmakupro.cli.ensure_qt_app"), \
             patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls, \
             patch("danmakupro.cli.QApplication"):

            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            call_kwargs = mock_burner_cls.call_args[1]
            assert call_kwargs["encode_mode"] == EncodeMode.CPU

    def test_output_flag(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        out = tmp_path / "out.mp4"
        out.touch()

        with patch("sys.argv", ["danmakupro", str(video), str(xml), "-o", str(out), "-f"]), \
             patch("danmakupro.cli.load_config") as mock_load_config, \
             patch("danmakupro.cli.configure_logger"), \
             patch("danmakupro.cli.ensure_qt_app"), \
             patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls, \
             patch("danmakupro.cli.QApplication"):

            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            call_kwargs = mock_burner_cls.call_args[1]
            assert call_kwargs["video_out"] == str(out)

    def test_config_flag(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        cfg = tmp_path / "config.yaml"
        cfg.touch()

        with patch("sys.argv", ["danmakupro", str(video), str(xml), "-c", str(cfg)]), \
             patch("danmakupro.cli.load_config") as mock_load_config, \
             patch("danmakupro.cli.configure_logger"), \
             patch("danmakupro.cli.ensure_qt_app"), \
             patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls, \
             patch("danmakupro.cli.QApplication"):

            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            mock_load_config.assert_called_once_with(str(cfg))

    def test_burner_error_handling(self, tmp_path):
        from danmakupro.errors import DanmakuProError, ErrorCategory

        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with patch("sys.argv", ["danmakupro", str(video), str(xml)]), \
             patch("danmakupro.cli.load_config"), \
             patch("danmakupro.cli.configure_logger"), \
             patch("danmakupro.cli.ensure_qt_app"), \
             patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls, \
             patch("danmakupro.cli.QApplication"):

            mock_burner_cls.side_effect = DanmakuProError(
                "test error", ErrorCategory.INPUT,
            )
            with pytest.raises(SystemExit):
                main()

    def test_run_error_handling(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with patch("sys.argv", ["danmakupro", str(video), str(xml)]), \
             patch("danmakupro.cli.load_config"), \
             patch("danmakupro.cli.configure_logger"), \
             patch("danmakupro.cli.ensure_qt_app"), \
             patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls, \
             patch("danmakupro.cli.QApplication"):

            mock_burner = MagicMock()
            mock_burner.run.side_effect = RuntimeError("boom")
            mock_burner_cls.return_value = mock_burner
            with pytest.raises(SystemExit):
                main()