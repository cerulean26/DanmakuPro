"""logger_config 单元测试"""

from unittest.mock import patch, MagicMock

from danmakupro.logger_config import configure_logger


class TestConfigureLogger:

    def test_removes_existing_handlers(self):
        mock_logger = MagicMock()
        with patch("danmakupro.logger_config.logger", mock_logger):
            configure_logger()
        mock_logger.remove.assert_called_once()

    def test_adds_two_sinks(self):
        mock_logger = MagicMock()
        with patch("danmakupro.logger_config.logger", mock_logger):
            configure_logger()
        assert mock_logger.add.call_count == 2

    def test_stderr_sink_format(self):
        mock_logger = MagicMock()
        with patch("danmakupro.logger_config.logger", mock_logger):
            configure_logger()
        stderr_call = mock_logger.add.call_args_list[0]
        _, kwargs = stderr_call
        assert kwargs["format"] is not None
        assert kwargs["level"] == "INFO"
        assert kwargs["colorize"] is True

    def test_file_sink_format(self):
        mock_logger = MagicMock()
        with patch("danmakupro.logger_config.logger", mock_logger):
            configure_logger()
        file_call = mock_logger.add.call_args_list[1]
        _, kwargs = file_call
        assert kwargs["format"] is not None
        assert kwargs["level"] == "INFO"
        assert kwargs["rotation"] == "10 MB"
        assert kwargs["retention"] == 7
        assert kwargs["encoding"] == "utf-8"