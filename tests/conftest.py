"""全局 pytest fixture

集中管理 Qt 应用、字体、图片缓存等共享 fixture，避免各测试文件重复定义。
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication, QFont, QFontMetrics, QImage, QColor

from danmakupro.config import DEFAULT_CONFIG
from danmakupro.utils import extract_emoji_names

style = DEFAULT_CONFIG.style
from danmakupro.render.assets import load_image_assets
from danmakupro.input.parser import parse_xml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_XML = _PROJECT_ROOT / "source" / "test.xml"
_EMOJI_DIR = _PROJECT_ROOT / "assets" / "emoji"
_GIFT_DIR = _PROJECT_ROOT / "assets" / "gift"

LINE_HEIGHT = 36
FONT_SIZE = style.font_size


@dataclass
class MockAssetLoader:
    """模拟 AssetLoader，提供测试所需的字体、缓存和度量信息。"""
    font: QFont
    fm: QFontMetrics
    line_height: int
    emoji_cache: dict
    gift_cache: dict
    bg_color: QColor


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


def pytest_addoption(parser):
    parser.addoption(
        "--xml-path",
        default=os.getenv("DANMAKU_XML", str(_DEFAULT_XML)),
        help="XML 弹幕文件路径（默认: source 目录下的测试文件）",
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
# 图片缓存
# =============================================================================


@pytest.fixture(scope="session")
def emoji_cache(qapp):
    cache: dict[str, QImage] = {}
    if _EMOJI_DIR.exists():
        names = {p.stem for p in _EMOJI_DIR.glob("*.png")}
        load_image_assets(_EMOJI_DIR, names, LINE_HEIGHT, cache, "emoji")
    return cache


@pytest.fixture(scope="session")
def gift_cache(qapp):
    cache: dict[str, QImage] = {}
    if _GIFT_DIR.exists():
        names = {p.stem for p in _GIFT_DIR.glob("*.png")}
        load_image_assets(_GIFT_DIR, names, LINE_HEIGHT, cache, "gift")
    return cache


# =============================================================================
# XML 解析结果（仅当文件存在时可用）
# =============================================================================


@pytest.fixture(scope="session")
def xml_path(request):
    path = Path(request.config.getoption("--xml-path"))
    if not path.exists():
        pytest.skip(f"XML 文件不存在: {path}")
    return path


@pytest.fixture(scope="session")
def events(xml_path):
    return parse_xml(str(xml_path), min_gift_price=0.0)


@pytest.fixture(scope="session")
def emoji_names(events):
    names: set[str] = set()
    for e in events:
        if not e.is_gift and e.text:
            for name in extract_emoji_names(e.text):
                names.add(name)
    return names


@pytest.fixture(scope="session")
def gift_names(events):
    return {e.gift_name for e in events if e.is_gift and e.gift_name}