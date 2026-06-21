"""全局 pytest fixture

集中管理 Qt 应用、字体、图片缓存等共享 fixture，避免各测试文件重复定义。
"""

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication, QFont, QFontMetrics, QImage
from PySide6.QtCore import Qt

from danmakupro.config import EMOJI_PATTERN, FONT_SIZE
from danmakupro.parser import parse_xml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_XML = _PROJECT_ROOT / "source" / "2026-06-20 16-00-05-993 放黑豹.xml"
_EMOJI_DIR = _PROJECT_ROOT / "assets" / "emoji"
_GIFT_DIR = _PROJECT_ROOT / "assets" / "gift"

LINE_HEIGHT = 36


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
        for png in _EMOJI_DIR.glob("*.png"):
            img = QImage(str(png))
            if not img.isNull():
                cache[png.stem] = img.scaled(
                    LINE_HEIGHT, LINE_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
    return cache


@pytest.fixture(scope="session")
def gift_cache(qapp):
    cache: dict[str, QImage] = {}
    if _GIFT_DIR.exists():
        for png in _GIFT_DIR.glob("*.png"):
            img = QImage(str(png))
            if not img.isNull():
                cache[png.stem] = img.scaled(
                    LINE_HEIGHT, LINE_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
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
    return parse_xml(str(xml_path))


@pytest.fixture(scope="session")
def emoji_names(events):
    names: set[str] = set()
    for e in events:
        if not e.is_gift and e.text:
            for match in EMOJI_PATTERN.finditer(e.text):
                names.add(match.group(1))
    return names


@pytest.fixture(scope="session")
def gift_names(events):
    return {e.gift_name for e in events if e.is_gift and e.gift_name}