"""编码模块

负责视频编码和 FFmpeg 管理。
"""

from .ffmpeg import FFmpegManager

__all__ = ["FFmpegManager"]