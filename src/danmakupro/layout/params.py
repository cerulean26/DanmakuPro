"""布局参数

布局计算所需的数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutParams:
    """弹幕布局参数"""
    bottom: int      # 弹幕区底部边界
    text_h: int      # 弹幕区高度
    text_top: int    # 弹幕区顶部边界
    text_w: int      # 弹幕区最大宽度
    gap: int         # 弹幕垂直间距
    gift_top: int    # 礼物区顶部边界
    gift_h: int      # 礼物区高度


@dataclass(frozen=True)
class LayerParams:
    """渲染层参数"""
    layer_x: int
    layer_y: int
    layer_w: int
    layer_h: int