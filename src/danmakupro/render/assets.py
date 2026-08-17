"""资源加载器

管理字体、Emoji 和礼物图片的加载与缓存。
"""

from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QByteArray
from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QGuiApplication, QImage, QColor, QFont, QFontMetrics, QFontDatabase, QRawFont,
)

from ..config.models import DEFAULT_CONFIG
from ..input.models import DanmakuEvent
from ..utils import extract_emoji_names

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_CORE_FONTS: dict[str, str] = {
    "Microsoft YaHei": "msyh.ttc",
    "Microsoft YaHei Bold": "msyhbd.ttc",
    "Segoe UI": "segoeui.ttf",
    "Segoe UI Emoji": "seguiemj.ttf",
    "Segoe UI Symbol": "SegoeUISymbol.ttf",
}

_EXTENDED_FONTS: dict[str, str] = {
    "Noto Sans": "NotoSans.ttf",
    "Noto Sans CJK SC": "NotoSansCJKsc-Regular.otf",
    "Noto Sans Symbols 2": "NotoSansSymbols2-Regular.ttf",
    "Tahoma": "tahoma.ttf",
    "Nirmala UI": "Nirmala.ttc", 
    "Malgun Gothic": "malgun.ttf",
}


def load_image_assets(
    asset_dir: Path,
    asset_names: set[str],
    line_height: int,
    cache: dict[str, QImage],
    asset_type: str,
) -> set[str]:
    """加载图片资源

    Returns:
        未能加载的图片名称集合
    """
    missing: set[str] = set()
    if not asset_dir.exists():
        logger.warning(f"{asset_type} 文件夹不存在")
        return asset_names

    for name in asset_names:
        file_path = asset_dir / f"{name}.png"
        img = QImage(str(file_path))
        if not img.isNull():
            cache[name] = img.scaled(
                line_height, line_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            missing.add(name)

    if missing:
        logger.warning(f"{asset_type} 缺失图片: {sorted(missing)}")
    logger.info(f"{asset_type} 预加载完成: {len(cache)} 个, 缺失: {len(missing)} 个")
    return missing


class AssetLoader:
    """资源加载器"""

    def __init__(self, font_size: int = DEFAULT_CONFIG.style.font_size):
        self.emoji_cache: dict[str, QImage] = {}
        self.gift_cache: dict[str, QImage] = {}
        self.bg_color = QColor(20, 20, 20, 127)
        self._font_size = font_size

        if QGuiApplication.instance() is None:
            raise RuntimeError("必须先创建 QApplication")

        self._font_dir = _PROJECT_ROOT / "assets" / "fonts"
        self._loaded_families: list[str] = []
        self._init_fonts()

        self.emoji_dir = _PROJECT_ROOT / "assets" / "emoji"
        self.gift_dir = _PROJECT_ROOT / "assets" / "gift"

    def _init_fonts(self) -> None:
        """加载核心字体"""
        for family, filename in _CORE_FONTS.items():
            path = self._font_dir / filename
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
                self._loaded_families.append(family)

        self._rebuild_font()

    def _rebuild_font(self) -> None:
        """重建字体"""
        bold_families = [f for f in self._loaded_families if "Bold" in f]
        regular_families = [f for f in self._loaded_families if "Bold" not in f]
        families = bold_families + regular_families

        self.font = QFont()
        self.font.setFamilies(families)
        self.font.setPointSize(self._font_size)
        self.font.setBold(True)
        self.font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)
        self.fm = QFontMetrics(self.font)
        self.line_height = self.fm.height()

    def load_assets(self, events: list[DanmakuEvent]) -> None:
        """按需加载资源"""
        used_emoji: set[str] = set()
        used_gift: set[str] = set()
        all_chars: set[str] = set()

        for ev in events:
            all_chars.update(ev.user)
            all_chars.update(ev.text)
            if ev.is_gift:
                used_gift.add(ev.gift_name)
            elif '[' in ev.text and ']' in ev.text:
                for name in extract_emoji_names(ev.text):
                    used_emoji.add(name)

        self._load_fonts_for_chars(all_chars)
        load_image_assets(self.emoji_dir, used_emoji, self.line_height, self.emoji_cache, "Emoji")
        load_image_assets(self.gift_dir, used_gift, self.line_height, self.gift_cache, "礼物")

    def _load_fonts_for_chars(self, chars: set[str]) -> None:
        """按需加载扩展字体"""
        raw_fonts = self._build_raw_fonts()
        missing = self._find_missing_chars(chars, raw_fonts)
        if not missing:
            return

        newly_loaded = 0
        for family, filename in _EXTENDED_FONTS.items():
            if family in self._loaded_families:
                continue
            path = self._font_dir / filename
            if not path.exists():
                continue
            if self._font_covers_any(path, missing):
                QFontDatabase.addApplicationFont(str(path))
                self._loaded_families.append(family)
                newly_loaded += 1
                raw_fonts = self._build_raw_fonts()
                missing = self._find_missing_chars(chars, raw_fonts)
                if not missing:
                    break

        if newly_loaded > 0:
            self._rebuild_font()

    def _build_raw_fonts(self) -> list[QRawFont]:
        """构建已加载字体的 QRawFont 列表"""
        raw_fonts = []
        for family in self._loaded_families:
            f = QFont(family, self._font_size, QFont.Weight.Bold)
            raw_fonts.append(QRawFont.fromFont(f))
        return raw_fonts

    def _find_missing_chars(self, chars: set[str], raw_fonts: list[QRawFont]) -> set[str]:
        """查找缺失字符"""
        missing: set[str] = set()
        for c in chars:
            if c == ' ':
                continue
            for rf in raw_fonts:
                indexes = rf.glyphIndexesForString(c)
                if len(indexes) > 0 and indexes[0] != 0:
                    break
            else:
                missing.add(c)
        return missing

    @staticmethod
    def _font_covers_any(path: Path, chars: set[str]) -> bool:
        """检查字体是否覆盖任意字符"""
        with open(path, "rb") as f:
            data = QByteArray(f.read())
        rf = QRawFont()
        rf.loadFromData(data, 25.0, QFont.HintingPreference.PreferDefaultHinting)
        for c in chars:
            indexes = rf.glyphIndexesForString(c)
            if len(indexes) > 0 and indexes[0] != 0:
                return True
        return False