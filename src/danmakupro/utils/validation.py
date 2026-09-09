"""输入/输出路径校验工具

提供视频、XML、输出路径的独立校验函数，与压制引擎解耦。
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from ..errors import InputError

SUPPORTED_VIDEO_EXTS = frozenset({".mp4", ".flv", ".mkv", ".avi", ".mov", ".ts", ".webm"})
SUPPORTED_OUTPUT_EXTS = frozenset({".mp4", ".flv", ".mkv", ".avi", ".mov"})


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


def validate_output_path(video_out: str, force: bool = False) -> None:
    """校验输出路径，检测文件覆盖。

    Args:
        video_out: 输出视频路径
        force: 是否强制覆盖已有文件

    Raises:
        InputError: 输出目录不存在、格式不支持或文件已存在且未指定 force
    """
    path = Path(video_out)
    out_dir = path.parent

    if not out_dir.exists():
        raise InputError(f"输出目录不存在: {out_dir}")
    if path.suffix.lower() not in SUPPORTED_OUTPUT_EXTS:
        raise InputError(f"不支持的输出格式: {path.suffix}")
    if path.exists():
        if not force:
            raise InputError(f"输出文件已存在: {video_out}")
        logger.warning(f"输出文件已存在，将被覆盖: {video_out}")