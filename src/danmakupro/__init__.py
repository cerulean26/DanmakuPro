"""DanmakuPro — 弹幕压制引擎

将 XML 弹幕文件渲染并叠加到视频上，生成带弹幕的视频文件。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from .config.models import (
    DanmakuConfig, DEFAULT_CONFIG, EncodeMode,
    LayoutStyle, LayoutRatio, AnimationParams, EncodeParams, SystemParams,
)

if TYPE_CHECKING:
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

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "DanmakuBurner": (".core.burner", "DanmakuBurner"),
    "parse_xml": (".input.parser", "parse_xml"),
    "DanmakuRenderer": (".render.renderer", "DanmakuRenderer"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = import_module(module_path, __package__)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")