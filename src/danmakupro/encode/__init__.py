"""编码模块

负责视频编码与 FFmpeg 管理。子模块分工：probe 读视频元数据、capability 探测
硬件能力、commands 构建命令行，ffmpeg 编排压制进程。
"""

from .ffmpeg import FFmpegManager

__all__ = ["FFmpegManager"]
