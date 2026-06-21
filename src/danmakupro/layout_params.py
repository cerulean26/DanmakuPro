"""布局参数数据结构

使用 dataclass 替代 Dict[str, int]，提供类型安全和 IDE 自动补全。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutParams:
    """弹幕布局参数（不可变）"""
    container_bottom: int
    max_container_height: int
    max_y_limit: int
    max_content_width: int
    bubble_vertical_gap: int


@dataclass(frozen=True)
class LayerParams:
    """渲染层参数（不可变）"""
    layer_x: int
    layer_y: int
    layer_w: int
    layer_h: int