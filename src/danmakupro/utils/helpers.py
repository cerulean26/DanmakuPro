"""通用工具函数"""

from __future__ import annotations

import re

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication


# Emoji 标记正则表达式
EMOJI_PATTERN = re.compile(r'\[([^\]]+)\]')


def extract_emoji_names(text: str) -> list[str]:
    """提取文本中所有 Emoji 名称"""
    return [m.group(1) for m in EMOJI_PATTERN.finditer(text)]


def ensure_qt_app() -> QApplication:
    """确保 QApplication 已创建"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    if isinstance(app, QCoreApplication) and not isinstance(app, QApplication):
        app = QApplication([])
    return app