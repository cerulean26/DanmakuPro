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
# 校验辅助函数
# =============================================================================

def _assert_non_negative(obj: object, *names: str) -> None:
    for name in names:
        v = getattr(obj, name)
        if v < 0:
            raise ValueError(f"{name} 不能为负数，当前 {v}")


def _assert_positive(obj: object, *names: str) -> None:
    for name in names:
        v = getattr(obj, name)
        if v <= 0:
            raise ValueError(f"{name} 必须 > 0，当前 {v}")


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
    fade_out_zone: float = 30.0

    def __post_init__(self):
        _assert_non_negative(self, "bubble_padding_x", "bubble_padding_y",
                             "bubble_row_gap", "bubble_vertical_gap",
                             "gift_spacing", "emoji_spacing", "danmaku_x",
                             "layer_width_extra", "fade_out_zone")
        _assert_positive(self, "font_size")
        _assert_non_negative(self, "bubble_multiline_radius")


@dataclass(frozen=True)
class LayoutRatio:
    """布局比例配置

    使用"弹幕行数"替代"高度比例"，用户无需计算像素。
    """
    max_text_rows: int = 4
    max_gift_rows: int = 2
    text_width_ratio: float = 0.8
    bottom_margin: int = 22

    def __post_init__(self):
        _assert_non_negative(self, "max_text_rows", "max_gift_rows", "bottom_margin")
        if not (0 < self.text_width_ratio <= 1.0):
            raise ValueError(f"text_width_ratio 必须在 (0, 1] 范围内，当前 {self.text_width_ratio}")


@dataclass(frozen=True)
class AnimationParams:
    """动画参数配置"""
    text_damping_factor: float = 0.25
    gift_damping_factor: float = 0.25
    text_spawn_interval: float = 0.5
    text_spawn_batch_size: int = 3
    gift_spawn_interval: float = 0.5
    gift_spawn_batch_size: int = 2
    gift_dwell_time: float | None = 5.0
    min_gift_price: float = 1.0

    def __post_init__(self):
        for name in ("text_damping_factor", "gift_damping_factor"):
            v = getattr(self, name)
            if not (0 < v <= 1.0):
                raise ValueError(f"{name} 必须在 (0, 1] 范围内，当前 {v}")
        _assert_non_negative(self, "text_spawn_interval", "gift_spawn_interval",
                             "min_gift_price")
        _assert_positive(self, "text_spawn_batch_size", "gift_spawn_batch_size")
        if self.gift_dwell_time is not None and self.gift_dwell_time < 0:
            raise ValueError(f"gift_dwell_time 不能为负数，当前 {self.gift_dwell_time}")


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

    def __post_init__(self):
        for name in ("gpu_cq", "qsv_quality", "cpu_crf"):
            v = getattr(self, name)
            if not (0 <= v <= 51):
                raise ValueError(f"{name} 必须在 [0, 51] 范围内，当前 {v}")
        _assert_positive(self, "cpu_min_reserve_threads")
        for name in ("gpu_preset", "qsv_preset", "cpu_preset"):
            if not getattr(self, name):
                raise ValueError(f"{name} 不能为空字符串")


@dataclass(frozen=True)
class SystemParams:
    """系统参数配置"""
    pipe_buffer_size: int = 10_000_000
    pipe_queue_size: int = 16
    ffmpeg_timeout: int = 10
    stderr_thread_timeout: int = 5
    video_alignment: int = 16
    max_queue_frames: int = 64

    def __post_init__(self):
        _assert_positive(self, "pipe_buffer_size", "pipe_queue_size",
                         "ffmpeg_timeout", "stderr_thread_timeout",
                         "max_queue_frames")
        if self.video_alignment <= 0 or (self.video_alignment & (self.video_alignment - 1)) != 0:
            raise ValueError(
                f"video_alignment 必须是 2 的幂，当前 {self.video_alignment}"
            )


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