"""日志配置模块

统一管理 loguru 日志的初始化配置，供 CLI 入口共用。

日志目录的确定顺序见 resolve_log_dir：
    1. 环境变量 DANMAKUPRO_LOG_DIR
    2. 源码检出时的仓库根 logs/
    3. 已安装（wheel / pip）时的用户级目录

为什么不能一律取「项目根」：项目根是靠 Path(__file__) 往上数三级推出来的，
这只在 src 布局的源码检出里成立。wheel 安装后代码落在 site-packages 下，
同样往上三级得到的是 Python 自己的 Lib 目录 —— 往那里写日志既看不见，
在系统级安装时还会因无写权限直接 PermissionError，第一行日志都出不来。
"""

import os
import sys
from pathlib import Path

from loguru import logger

_ENV_LOG_DIR = "DANMAKUPRO_LOG_DIR"
_LOG_SUBDIR = "logs"
_LOG_FILE = "ffmpeg.log"
# src 布局下 __file__ 往上三级即仓库根，可用仓库根/src/danmakupro 是否存在的来区分
# 「源码检出」与「已安装」；wheel 安装时这里会是 .../Lib，没有 src/danmakupro。
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
    """确定日志目录。

    Args:
        source_root: 待测的根目录，默认取 _SOURCE_ROOT。暴露出来是为了让测试能
            注入两种形态的安装位置（源码检出 / 已安装），无需真的换环境。

    Returns:
        环境变量 DANMAKUPRO_LOG_DIR 优先；否则源码检出时用 根目录/logs，
        已安装时用用户级目录。
    """
    override = os.environ.get(_ENV_LOG_DIR)
    if override:
        return Path(override)
    root = _SOURCE_ROOT if source_root is None else source_root
    if (root / "src" / "danmakupro").is_dir():
        return root / _LOG_SUBDIR
    return _user_log_dir()


_LOG_DIR = resolve_log_dir()

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

    日志目录不可写时不抛异常，降级为「仅终端输出」并给出 WARNING —— 目录解析
    已能避开无写权限位置（见 resolve_log_dir），但磁盘只读、杀软拦截等仍可能
    让 mkdir 失败，而丢日志显然不该让整个任务连帧都没渲就退出。
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

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.add(
            sink=str(_LOG_DIR / _LOG_FILE),
            format=_FILE_FORMAT,
            level="INFO",
            enqueue=True,
            rotation="10 MB",
            retention=7,
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning(f"日志文件不可用，本次运行仅输出到终端（{_LOG_DIR}）：{exc}")
