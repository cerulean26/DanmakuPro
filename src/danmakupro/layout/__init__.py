"""布局模块

负责弹幕布局计算、碰撞检测和位置更新。
"""

from .active import ActiveDanmaku
from .engine import LayoutEngine, LayoutContext
from .params import LayoutParams, LayerParams

__all__ = [
    "ActiveDanmaku",
    "LayoutEngine", "LayoutContext",
    "LayoutParams", "LayerParams",
]