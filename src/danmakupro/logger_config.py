"""日志配置模块

统一管理 loguru 日志的初始化配置，供 CLI 入口共用。

日志目录优先级：
    1. 环境变量 DANMAKUPRO_LOG_DIR
    2. 项目根目录下的 logs/ 文件夹
"""

import os
import sys
from pathlib import Path

from loguru import logger

_LOG_DIR = Path(
    os.environ.get("DANMAKUPRO_LOG_DIR")
    or (Path(__file__).resolve().parent.parent.parent / "logs")
)

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


def _ensure_utf8_stderr() -> None:
    """把 stderr 切到 UTF-8，消除 Windows GBK 控制台下的中文乱码。

    文件 sink 已显式指定 encoding="utf-8"，但 stderr sink 走的是进程默认编码：
    Windows 中文环境下为 cp936，中文会直接输出成乱码
    （实测「编码模式: GPU (NVENC)」→「缂栫爜妯″紡」）。

    失败一律静默：stderr 可能已被替换（pytest capture、GUI 宿主接管）
    或根本不可写（pythonw 无控制台），此时 reconfigure 不可用，
    但日志功能本身不应因此中断。
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


def configure_logger() -> None:
    """配置 loguru 日志。

    - stderr：彩色输出，INFO 级别，供用户实时查看进度
    - 文件：ffmpeg.log，INFO 级别，含源码位置，供故障排查

    在添加 sink 之前会先把 stderr 重配为 UTF-8（见 _ensure_utf8_stderr）。
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_utf8_stderr()
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
        level="INFO",
        enqueue=True,
        rotation="10 MB",
        retention=7,
        encoding="utf-8",
    )