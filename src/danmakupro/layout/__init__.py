"""布局模块

负责弹幕布局计算、碰撞检测和位置更新。
"""

from .engine import LayoutEngine, LayoutContext
from .params import LayoutParams, LayerParams

__all__ = ["LayoutEngine", "LayoutContext", "LayoutParams", "LayerParams"]