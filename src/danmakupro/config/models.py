"""配置数据模型

所有配置相关的数据类定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


# =============================================================================
# 编码模式
# =============================================================================

class EncodeMode(StrEnum):
    """编码模式常量"""
    AUTO = "auto"
    GPU = "gpu"
    QSV = "qsv"
    CPU = "cpu"


# =============================================================================
# 子配置
# =============================================================================

@dataclass(frozen=True)
class LayoutStyle:
    """布局样式配置"""
    danmaku_x: int = 30
    layer_width_extra: int = 100
    bubble_padding_x: int = 14
    bubble_padding_y: int = 5
    bubble_row_gap: int = 5
    bubble_vertical_gap: int = 4
    bubble_multiline_radius: float = 14.0
    gift_spacing: int = 6
    emoji_spacing: int = 4
    font_size: int = 25
    fade_out_zone: float = 30.0 # 淡出区域高度（像素）


@dataclass(frozen=True)
class LayoutRatio:
    """布局比例配置"""
    bottom_ratio: float = 0.98
    text_h_ratio: float = 0.2125
    text_w_ratio: float = 0.8
    gift_h_ratio: float = 0.075


@dataclass(frozen=True)
class AnimationParams:
    """动画参数配置"""
    text_damping_factor: float = 0.25 # 文本阻尼因子
    gift_damping_factor: float = 0.25 # 礼物阻尼因子
    text_spawn_interval: float = 0.5 # 文本弹幕生成间隔
    text_spawn_batch_size: int = 3 # 文本弹幕生成批次大小
    gift_spawn_interval: float = 0.5 # 礼物弹幕生成间隔
    gift_spawn_batch_size: int = 2 # 礼物弹幕生成批次大小
    gift_dwell_time: float | None = 5.0 # 礼物弹幕停留时间，单位秒
    min_gift_price: float = 1.0 # 最低礼物价格过滤，低于此值不显示


@dataclass(frozen=True)
class EncodeParams:
    """编码参数配置"""
    gpu_preset: str = "p4"
    gpu_cq: int = 23
    qsv_preset: str = "medium"
    qsv_quality: int = 23
    cpu_preset: str = "veryfast"
    cpu_crf: int = 23
    cpu_min_reserve_threads: int = 2


@dataclass(frozen=True)
class SystemParams:
    """系统参数配置"""
    pipe_buffer_size: int = 10_000_000 # 管道缓冲区大小
    pipe_queue_size: int = 16 # 异步写入队列大小
    ffmpeg_timeout: int = 10 # FFmpeg 超时时间
    stderr_thread_timeout: int = 5 # stderr 线程超时时间
    h264_alignment: int = 16 # H264 编码对齐大小
    max_queue_frames: int = 64  # 异步写入队列最大帧数，防止内存无限增长


# =============================================================================
# 聚合配置
# =============================================================================

@dataclass(frozen=True)
class DanmakuConfig:
    """弹幕压制完整配置"""
    style: LayoutStyle = field(default_factory=LayoutStyle)
    ratio: LayoutRatio = field(default_factory=LayoutRatio)
    animation: AnimationParams = field(default_factory=AnimationParams)
    encode: EncodeParams = field(default_factory=EncodeParams)
    system: SystemParams = field(default_factory=SystemParams)


# =============================================================================
# 默认值
# =============================================================================

DEFAULT_CONFIG = DanmakuConfig()