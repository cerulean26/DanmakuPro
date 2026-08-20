"""弹幕事件数据类

定义从 XML 解析出的弹幕事件结构。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DanmakuEvent:
    """弹幕事件"""
    time: float
    user: str
    text: str
    is_gift: bool = False
    gift_name: str = ""
    gift_count: int = 0