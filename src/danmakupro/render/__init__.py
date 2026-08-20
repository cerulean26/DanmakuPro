"""渲染模块

负责弹幕渲染和资源管理。
"""

from .assets import AssetLoader
from .layout_builder import DanmakuLayout, DanmakuLayoutBuilder
from .renderer import DanmakuRenderer
from .segments import RenderSegment, TextRow

__all__ = [
    "AssetLoader", "DanmakuRenderer",
    "DanmakuLayout", "DanmakuLayoutBuilder",
    "RenderSegment", "TextRow",
]