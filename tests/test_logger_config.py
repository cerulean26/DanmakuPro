"""logger_config 单元测试"""

from unittest.mock import patch, MagicMock

from danmakupro.logger_config import configure_logger, flush_logs


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


class TestFlushLogs:
    """测试 flush_logs：排空 enqueue 队列。"""

    def test_calls_logger_complete(self):
        """必须调用 logger.complete() —— loguru 唯一的队列排空入口。"""
        mock_logger = MagicMock()
        with patch("danmakupro.logger_config.logger", mock_logger):
            flush_logs()
        mock_logger.complete.assert_called_once_with()

    def test_real_enqueue_sink_is_drained(self):
        """真跑一次 enqueue 管道：flush_logs 返回后记录必须已写出（无需 sleep）。"""
        from loguru import logger

        written: list[str] = []
        sink_id = logger.add(
            lambda m: written.append(m.record["message"]),
            level="INFO",
            format="{message}",
            enqueue=True,
        )
        try:
            logger.info("哨兵")
            flush_logs()
            assert written == ["哨兵"]
        finally:
            logger.remove(sink_id)
