"""渲染模块

负责弹幕渲染和资源管理。
"""

from .assets import AssetLoader
from .renderer import DanmakuRenderer

__all__ = ["AssetLoader", "DanmakuRenderer"]