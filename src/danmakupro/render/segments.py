"""渲染段落实体

定义弹幕渲染过程中的段落和行数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RenderSegment:
    """渲染段落"""
    type: str
    content: str
    width: int
    color: tuple[int, int, int] | None = None
    has_cache: bool = False


@dataclass(slots=True)
class TextRow:
    """文本行"""
    segments: list[RenderSegment] = field(default_factory=list)
    width: int = 0