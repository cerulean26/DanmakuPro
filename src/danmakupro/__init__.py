"""DanmakuPro — 弹幕压制引擎

将 XML 弹幕文件渲染并叠加到视频上，生成带弹幕的视频文件。

核心模块:
    - models:        弹幕数据模型 (DanmakuEvent, ActiveDanmaku, RenderSegment 等)
    - config:        全局常量配置 (字体大小、间距、动画参数等)
    - layout_params: 布局参数数据结构 (LayoutParams, LayerParams)
    - parser:        XML 弹幕解析器
    - asset_loader:  资源加载器 (字体、Emoji、礼物图片)
    - layout_engine: 布局引擎 (布局计算、碰撞检测、位置更新)
    - ffmpeg_manager: FFmpeg 进程管理器
    - renderer:      弹幕渲染器 (画布管理、帧渲染)
    - burner:        弹幕压制编排器 (DanmakuBurner)
    - utils:         通用工具函数 (Emoji 检测等)
    - gui:           文件选择对话框 (danmakupro-gui 入口)
    - cli:           命令行入口 (danmakupro 入口)
"""

from .models import (
    DanmakuEvent, RenderSegment, TextRow, ActiveDanmaku,
)
from .parser import parse_xml
from .layout_params import LayoutParams, LayerParams
from .asset_loader import AssetLoader
from .layout_engine import LayoutEngine
from .ffmpeg_manager import FFmpegManager
from .renderer import DanmakuRenderer
from .burner import DanmakuBurner
from .utils import has_emoji, extract_emoji_names

__all__ = [
    # models
    "DanmakuEvent", "RenderSegment", "TextRow", "ActiveDanmaku",
    # parser
    "parse_xml",
    # layout params
    "LayoutParams", "LayerParams",
    # components
    "AssetLoader", "LayoutEngine", "FFmpegManager", "DanmakuRenderer",
    # burner
    "DanmakuBurner",
    # utils
    "has_emoji", "extract_emoji_names",
]