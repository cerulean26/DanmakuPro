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
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}"
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


def flush_logs() -> None:
    """等待 enqueue 队列中的日志全部写出到各 sink。

    为什么需要：两个 sink 都配了 ``enqueue=True``，日志记录由 loguru 的后台
    线程异步写出，``logger.warning()`` 返回时记录往往还躺在队列里。此时若主
    线程紧接着往同一终端输出别的东西（``input()`` 的交互提示、tqdm 进度条），
    滞留的那条日志会晚一步挤出来，和别的内容粘在同一行。

    注意 ``sys.stderr.flush()`` 解决不了这个问题：它刷的是 Python 的文本缓冲，
    而待写的记录还在 loguru 的队列里，flush 时无内容可刷。实测（2026-09-16，
    enqueue=True 复刻本配置）5/5 轮出现「提示先显示、WARNING 后挤出」，改用
    本函数后 5/5 轮顺序正确。

    对未开启 enqueue 的 sink 是空操作，无 sink 时亦可安全调用。
    """
    logger.complete()


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
