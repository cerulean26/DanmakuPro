"""logger_config 单元测试"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import danmakupro.logger_config as lc
from danmakupro.logger_config import configure_logger, flush_logs, resolve_log_dir

_SOURCE_IS_CHECKOUT = (lc._SOURCE_ROOT / "src" / "danmakupro").is_dir()


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

    def test_file_sink_uses_danmakupro_name(self, monkeypatch, tmp_path):
        """文件名须体现「装的是全应用日志」—— 旧名 ffmpeg.log 名实不符。"""
        monkeypatch.setenv("DANMAKUPRO_LOG_DIR", str(tmp_path / "logs"))
        mock_logger = MagicMock()
        with patch("danmakupro.logger_config.logger", mock_logger):
            configure_logger()
        _, kwargs = mock_logger.add.call_args_list[1]
        assert Path(kwargs["sink"]).name == "danmakupro.log"

    def test_log_dir_resolved_at_call_time(self, monkeypatch, tmp_path):
        """目录在调用时求值，不在 import 期缓存。

        用例与 import 顺序对抗：``lc`` 早已导入，此处才设置环境变量 —— 若实现
        改回模块级 ``_LOG_DIR = resolve_log_dir()``，本用例会落回仓库 logs/ 而失败。
        """
        monkeypatch.setenv("DANMAKUPRO_LOG_DIR", str(tmp_path / "late"))
        mock_logger = MagicMock()
        with patch("danmakupro.logger_config.logger", mock_logger):
            configure_logger()
        _, kwargs = mock_logger.add.call_args_list[1]
        assert Path(kwargs["sink"]).parent == tmp_path / "late"

    def test_logs_file_path_on_success(self, monkeypatch, tmp_path):
        """成功挂上文件 sink 后打印路径，让「日志落在哪」在终端可见。"""
        log_dir = tmp_path / "logs"
        monkeypatch.setenv("DANMAKUPRO_LOG_DIR", str(log_dir))
        mock_logger = MagicMock()
        with patch("danmakupro.logger_config.logger", mock_logger):
            configure_logger()
        mock_logger.info.assert_called_once()
        assert str(log_dir / "danmakupro.log") in mock_logger.info.call_args.args[0]


class TestResolveLogDir:
    """日志目录解析。

    这里的三条用例对应 P1-3：旧实现用 Path(__file__) 往上数三级猜目录，
    wheel 安装后那三级落在 Python 自己的 Lib 下 —— 既看不见，系统级安装还会
    PermissionError 直接崩在启动第一步。因此「能不能区分两种安装形态」是重点。
    """

    def test_env_var_takes_priority(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DANMAKUPRO_LOG_DIR", str(tmp_path / "custom"))
        assert resolve_log_dir(source_root=tmp_path) == tmp_path / "custom"

    def test_source_checkout_uses_repo_logs(self, monkeypatch, tmp_path):
        """源码检出（含 src/danmakupro）沿用仓库根 logs/ —— 与开发期习惯一致。"""
        monkeypatch.delenv("DANMAKUPRO_LOG_DIR", raising=False)
        root = tmp_path / "repo"
        (root / "src" / "danmakupro").mkdir(parents=True)
        assert resolve_log_dir(source_root=root) == root / "logs"

    def test_installed_package_uses_user_dir(self, monkeypatch, tmp_path):
        """已安装形态：结果必须落在用户目录，绝不能再是安装位置里面。"""
        monkeypatch.delenv("DANMAKUPRO_LOG_DIR", raising=False)
        appdata = tmp_path / "appdata"
        # 两个变量都设，使期望值与 win32 / posix 分支无关（CI 跑 Linux）
        monkeypatch.setenv("LOCALAPPDATA", str(appdata))
        monkeypatch.setenv("XDG_STATE_HOME", str(appdata))

        installed_root = tmp_path / "Lib"  # 模拟 wheel 装完后的解释器目录
        got = resolve_log_dir(source_root=installed_root)

        assert got == appdata / "DanmakuPro" / "logs"
        assert got != installed_root / "logs"

    @pytest.mark.skipif(not _SOURCE_IS_CHECKOUT, reason="仅在源码检出下有意义")
    def test_real_source_layout_unchanged(self, monkeypatch):
        monkeypatch.delenv("DANMAKUPRO_LOG_DIR", raising=False)
        assert resolve_log_dir() == lc._SOURCE_ROOT / "logs"


class TestFileSinkUnavailable:
    def test_degrades_to_stderr_only(self, monkeypatch, tmp_path):
        """日志目录不可写时不崩，降级为仅终端输出并给出 WARNING。

        加固的场景：解析已避开无写权限位置，但只读磁盘、杀软拦截仍可能让
        mkdir 失败 —— 丢日志不等于任务该失败。
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("", encoding="utf-8")  # 是文件，其下无法建目录
        monkeypatch.setenv("DANMAKUPRO_LOG_DIR", str(blocker / "logs"))

        mock_logger = MagicMock()
        with patch("danmakupro.logger_config.logger", mock_logger):
            configure_logger()

        assert mock_logger.add.call_count == 1  # 只有 stderr sink
        mock_logger.warning.assert_called_once()
        mock_logger.info.assert_not_called()


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
