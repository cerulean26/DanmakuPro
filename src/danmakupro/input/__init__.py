"""输入处理模块

负责 XML 解析和数据模型。
"""

from .models import DanmakuEvent, ActiveDanmaku, RenderSegment, TextRow
from .parser import parse_xml

__all__ = [
    "DanmakuEvent", "ActiveDanmaku", "RenderSegment", "TextRow",
    "parse_xml",
]