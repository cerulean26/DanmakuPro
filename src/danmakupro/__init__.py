"""DanmakuPro — 弹幕压制引擎

将 XML 弹幕文件渲染并叠加到视频上，生成带弹幕的视频文件。
"""

from .config.models import (
    DanmakuConfig, DEFAULT_CONFIG, EncodeMode,
    LayoutStyle, LayoutRatio, AnimationParams, EncodeParams, SystemParams,
)
from .core.burner import DanmakuBurner
from .input.parser import parse_xml
from .render.renderer import DanmakuRenderer

__all__ = [
    # 配置
    "DanmakuConfig", "DEFAULT_CONFIG", "EncodeMode",
    "LayoutStyle", "LayoutRatio", "AnimationParams", "EncodeParams", "SystemParams",
    # 核心
    "DanmakuBurner",
    # 输入
    "parse_xml",
    # 渲染
    "DanmakuRenderer",
]