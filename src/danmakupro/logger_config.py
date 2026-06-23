"""日志配置模块

统一管理 loguru 日志的初始化配置，供 CLI 和 GUI 入口共用。
"""

import sys
from pathlib import Path

from loguru import logger

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

_STDERR_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level}</level> - "
    "<level>{message}</level>"
)

_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level} | "
    "{name}:{function}:{line} - {message}"
)


def configure_logger() -> None:
    """配置 loguru 日志。

    - stderr：彩色输出，INFO 级别，供用户实时查看进度
    - 文件：ffmpeg.log，DEBUG 级别，含源码位置，供故障排查
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()

    logger.add(
        sink=sys.stderr,
        format=_STDERR_FORMAT,
        level="INFO",
        colorize=True,
        enqueue=True,
    )

    logger.add(
        sink=str(_LOG_DIR / "ffmpeg.log"),
        format=_FILE_FORMAT,
        level="DEBUG",
        enqueue=True,
        rotation="10 MB",
        retention=7,
        encoding="utf-8",
    )