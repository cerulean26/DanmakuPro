"""全局 pytest fixture

集中管理 Qt 应用、字体、图片缓存等共享 fixture，避免各测试文件重复定义。
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication, QFont, QFontMetrics, QImage, QColor

from danmakupro.config import DEFAULT_CONFIG

style = DEFAULT_CONFIG.style

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

LINE_HEIGHT = 36
FONT_SIZE = style.font_size
_PLACEHOLDER_SIZE = 36

_TEST_EMOJI_NAMES = ["微笑", "大笑"]
_TEST_GIFT_NAMES = ["小心心", "保时捷", "火箭"]


def _make_placeholder_image() -> QImage:
    img = QImage(_PLACEHOLDER_SIZE, _PLACEHOLDER_SIZE, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255, 255))
    return img


@dataclass
class MockAssetLoader:
    font: QFont
    fm: QFontMetrics
    line_height: int
    emoji_cache: dict
    gift_cache: dict
    bg_color: QColor

    def load_assets(self, events):
        pass


@pytest.fixture
def asset_loader(font, font_metrics, emoji_cache, gift_cache):
    return MockAssetLoader(
        font=font,
        fm=font_metrics,
        line_height=LINE_HEIGHT,
        emoji_cache=emoji_cache,
        gift_cache=gift_cache,
        bg_color=QColor(20, 20, 20, 150),
    )


# =============================================================================
# Qt & 字体
# =============================================================================


@pytest.fixture(scope="session")
def qapp():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    yield app


@pytest.fixture(scope="session")
def font(qapp):
    f = QFont("Microsoft YaHei", FONT_SIZE)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


@pytest.fixture(scope="session")
def font_metrics(font):
    return QFontMetrics(font)


# =============================================================================
# 图片缓存（内存占位图，不依赖磁盘文件）
# =============================================================================


@pytest.fixture(scope="session")
def emoji_cache(qapp):
    return {name: _make_placeholder_image() for name in _TEST_EMOJI_NAMES}


@pytest.fixture(scope="session")
def gift_cache(qapp):
    return {name: _make_placeholder_image() for name in _TEST_GIFT_NAMES}