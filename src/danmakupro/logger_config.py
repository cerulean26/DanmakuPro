"""日志配置模块，供 CLI 入口共用。

日志文件 ``<日志目录>/danmakupro.log``，10 MB 轮转，保留 7 个历史。
目录优先级：环境变量 DANMAKUPRO_LOG_DIR > 源码根 logs/ > 用户级目录。
"""

import os
import sys
from pathlib import Path

from loguru import logger

_ENV_LOG_DIR = "DANMAKUPRO_LOG_DIR"
_LOG_SUBDIR = "logs"
_LOG_FILE = "danmakupro.log"
# 源码检出时指向仓库根，wheel 安装时指向 Python Lib，用于区分两种部署形态。
_SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent


def _user_log_dir() -> Path:
    """用户级日志目录（installed 场景），不依赖代码装在哪个目录。

    Windows 走 LOCALAPPDATA（%LOCALAPPDATA%\\DanmakuPro\\logs），
    其它平台走 XDG_STATE_HOME，未设置时回落到 ~/.local/state。
    """
    if sys.platform == "win32":
        appdata = os.environ.get("LOCALAPPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Local"
    else:
        xdg = os.environ.get("XDG_STATE_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "DanmakuPro" / _LOG_SUBDIR


def resolve_log_dir(source_root: Path | None = None) -> Path:
    """确定日志目录：环境变量优先，其次源码根/logs，最后用户级目录。"""
    override = os.environ.get(_ENV_LOG_DIR)
    if override:
        return Path(override)
    root = _SOURCE_ROOT if source_root is None else source_root
    if (root / "src" / "danmakupro").is_dir():
        return root / _LOG_SUBDIR
    return _user_log_dir()


_STDERR_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level}</level> - "
    "<level>{message}</level>"
)

_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}"
)


def _ensure_utf8_stderr() -> None:
    """将 stderr 写出编码设为 UTF-8。

    仅影响重定向场景（CI、管道），真实控制台无效果。详细理由见 ADR-0003。
    失败静默：stderr 不可用时不应中断日志功能。
    """
    stream = sys.stderr
    if stream is None:
        return
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError, TypeError):
        pass


def flush_logs() -> None:
    """等待 enqueue 队列中的日志全部写出。

    enqueue=True 时日志为异步写出，调用方在紧接着写终端前应调用此函数，
    避免输出交错。对未开启 enqueue 的 sink 是空操作。
    """
    logger.complete()


def configure_logger() -> None:
    """配置 loguru：stderr 彩色输出 + 文件持久化，均为 INFO 级别。

    目录在调用时求值（非 import 期缓存），不可写时降级为仅终端输出。
    """
    _ensure_utf8_stderr()
    logger.remove()

    logger.add(
        sink=sys.stderr,
        format=_STDERR_FORMAT,
        level="INFO",
        colorize=True,
        enqueue=True,
    )

    log_dir = resolve_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            sink=str(log_dir / _LOG_FILE),
            format=_FILE_FORMAT,
            level="INFO",
            enqueue=True,
            rotation="10 MB",
            retention=7,
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning(f"日志文件不可用，本次运行仅输出到终端（{log_dir}）：{exc}")
    else:
        logger.info(f"日志文件：{log_dir / _LOG_FILE}")
