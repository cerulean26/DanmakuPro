"""输入/输出路径校验工具

提供视频、XML、输出路径的独立校验函数，与压制引擎解耦。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import sys

from loguru import logger

from ..errors import InputError
from ..logger_config import flush_logs

SUPPORTED_VIDEO_EXTS = frozenset(
    {".mp4", ".flv", ".mkv", ".avi", ".mov", ".ts", ".webm"}
)
SUPPORTED_OUTPUT_EXTS = frozenset({".mp4", ".flv", ".mkv", ".avi", ".mov"})

#: 覆盖确认回调类型：Path -> bool。
ConfirmOverwrite = Callable[[Path], bool]


def validate_video_input(video_in: str) -> None:
    """校验输入视频文件。

    Args:
        video_in: 输入视频路径

    Raises:
        InputError: 文件不存在、是目录、或格式不支持
    """
    path = Path(video_in)
    if not path.exists():
        raise InputError(f"视频文件不存在: {video_in}")
    if path.is_dir():
        raise InputError(f"视频路径是目录: {video_in}")
    if path.suffix.lower() not in SUPPORTED_VIDEO_EXTS:
        raise InputError(f"不支持的视频格式: {path.suffix}")


def validate_xml_input(xml_in: str) -> None:
    """校验输入弹幕 XML 文件。

    Args:
        xml_in: 输入 XML 路径

    Raises:
        InputError: 文件不存在、是目录、或格式不支持
    """
    path = Path(xml_in)
    if not path.exists():
        raise InputError(f"弹幕 XML 文件不存在: {xml_in}")
    if path.is_dir():
        raise InputError(f"弹幕 XML 路径是目录: {xml_in}")
    if path.suffix.lower() != ".xml":
        raise InputError(f"不支持的弹幕格式: {path.suffix}")


def _human_size(num_bytes: int) -> str:
    """把字节数格式化成便于阅读的字符串（用于展示待覆盖文件的体积）。"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def confirm_overwrite(path: Path) -> bool:
    """交互式终端询问是否覆盖，非交互环境拒绝覆盖并提示 -f。"""
    if sys.stdin is None or not sys.stdin.isatty():
        logger.warning(f"输出文件已存在: {path}")
        logger.warning("当前不是交互式终端，无法询问是否覆盖；如需覆盖请加 -f")
        return False

    try:
        stat = path.stat()
    except OSError:
        # 询问的瞬间文件刚好消失（被其他进程删掉）：没有可覆盖的对象，
        # 直接放行比抛一个含义模糊的 OSError 更合理。
        return True

    detail = "0 字节" if stat.st_size == 0 else _human_size(stat.st_size)
    when = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    logger.warning(f"输出文件已存在: {path}（{detail}，最后修改 {when}）")

    # 日志由 loguru 的后台线程异步写出，此刻上面那条 WARNING 多半还在队列里。
    # 不排空就显示提示，用户会看到「是否覆盖该文件？[y/N] 」后面粘着迟到的
    # 警告信息。注意 sys.stderr.flush() 对此无效 —— 它刷不到 loguru 的队列。
    flush_logs()

    while True:
        try:
            answer = input("是否覆盖该文件？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            # Ctrl+C 与输入流关闭一律按「不覆盖」处理，由调用方给出统一
            # 错误信息，避免两种退出方式各写一套提示。
            print()
            return False
        if answer in ("y", "yes"):
            return True
        if answer in ("", "n", "no"):
            return False
        print("请输入 y 或 n。")


def validate_output_path(
    video_out: str,
    force: bool = False,
    confirm: ConfirmOverwrite | None = None,
) -> None:
    """校验输出路径。force 为真直接覆盖，否则询问用户，拒绝时抛 InputError。"""
    path = Path(video_out)
    out_dir = path.parent

    if not out_dir.exists():
        raise InputError(f"输出目录不存在: {out_dir}")
    if path.suffix.lower() not in SUPPORTED_OUTPUT_EXTS:
        raise InputError(f"不支持的输出格式: {path.suffix}")
    if not path.exists():
        return

    if force:
        logger.warning(f"输出文件已存在，-f 已指定，直接覆盖: {video_out}")
        return

    ask = confirm if confirm is not None else confirm_overwrite
    if ask(path):
        logger.warning(f"输出文件已存在，将覆盖: {video_out}")
        return

    raise InputError(
        f"输出文件已存在，已取消覆盖: {video_out}\n"
        f"如需覆盖请加 -f，或改用 -o 指定其他输出路径。"
    )
