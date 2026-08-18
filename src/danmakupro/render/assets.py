"""资源加载器

管理字体、Emoji 和礼物图片的加载与缓存。
"""

from __future__ import annotations
from pathlib import Path
from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QGuiApplication, QImage, QColor, QFont, QFontMetrics, QFontDatabase, QRawFont,
)
from ..config.models import DEFAULT_CONFIG
from ..input.models import DanmakuEvent
from ..utils import extract_emoji_names

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 核心字体族：按优先级排列，所有 Windows 10+ 系统均自带
_CORE_FAMILIES: list[str] = [
    "Microsoft YaHei",
    "Segoe UI",
    "Segoe UI Emoji",
    "Segoe UI Symbol",
]


class AssetLoader:
    """资源加载器"""

    def __init__(self, font_size: int = DEFAULT_CONFIG.style.font_size):
        self.emoji_cache: dict[str, QImage] = {}
        self.gift_cache: dict[str, QImage] = {}
        self.bg_color = QColor(20, 20, 20, 127)
        self._font_size = font_size

        if QGuiApplication.instance() is None:
            raise RuntimeError("必须先创建 QApplication")

        self._loaded_families: list[str] = []
        self._init_fonts()

        self.emoji_dir = _PROJECT_ROOT / "assets" / "emoji"
        self.gift_dir = _PROJECT_ROOT / "assets" / "gift"

    def _init_fonts(self) -> None:
        """初始化核心字体族"""
        self._loaded_families = list(_CORE_FAMILIES)
        self._rebuild_font()

    def _rebuild_font(self) -> None:
        """重建字体"""
        self.font = QFont()
        self.font.setFamilies(self._loaded_families)
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
        self._load_image_assets(self.emoji_dir, used_emoji, self.emoji_cache, "Emoji")
        self._load_image_assets(self.gift_dir, used_gift, self.gift_cache, "礼物")

    def _load_image_assets(
        self,
        asset_dir: Path,
        asset_names: set[str],
        cache: dict[str, QImage],
        asset_type: str,
    ) -> None:
        """加载图片资源"""
        missing: set[str] = set()
        if not asset_dir.exists():
            logger.warning(f"{asset_type} 文件夹不存在")
            return

        for name in asset_names:
            file_path = asset_dir / f"{name}.png"
            img = QImage(str(file_path))
            if not img.isNull():
                cache[name] = img.scaled(
                    self.line_height, self.line_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            else:
                missing.add(name)

        if missing:
            logger.warning(f"{asset_type} 缺失图片: {sorted(missing)}")

    def _load_fonts_for_chars(self, chars: set[str]) -> None:
        """按需从系统字体库加载覆盖缺失字符的字体"""
        raw_fonts = self._build_raw_fonts()
        missing = self._find_missing_chars(chars, raw_fonts)
        if not missing:
            return

        newly_loaded = 0
        db = QFontDatabase()
        for family in db.families():
            if family in self._loaded_families:
                continue
            raw = self._build_single_raw_font(family)
            if any(self._raw_font_has_char(raw, c) for c in missing):
                self._loaded_families.append(family)
                newly_loaded += 1
                missing = {c for c in missing if not self._raw_font_has_char(raw, c)}
                if not missing:
                    break

        if newly_loaded > 0:
            self._rebuild_font()

        if missing:
            logger.warning(
                f"以下字符无字体覆盖，将显示为占位符: {''.join(sorted(missing))}"
            )

    def _build_raw_fonts(self) -> list[QRawFont]:
        """构建已加载字体的 QRawFont 列表"""
        raw_fonts = []
        for family in self._loaded_families:
            raw_fonts.append(self._build_single_raw_font(family))
        return raw_fonts

    def _build_single_raw_font(self, family: str) -> QRawFont:
        """构建单个字体的 QRawFont"""
        f = QFont(family, self._font_size, QFont.Weight.Bold)
        return QRawFont.fromFont(f)

    def _find_missing_chars(self, chars: set[str], raw_fonts: list[QRawFont]) -> set[str]:
        """查找缺失字符"""
        missing: set[str] = set()
        for c in chars:
            if c == ' ':
                continue
            for rf in raw_fonts:
                if self._raw_font_has_char(rf, c):
                    break
            else:
                missing.add(c)
        return missing

    @staticmethod
    def _raw_font_has_char(rf: QRawFont, char: str) -> bool:
        """检查 QRawFont 是否包含指定字符的字形"""
        indexes = rf.glyphIndexesForString(char)
        return len(indexes) > 0 and indexes[0] != 0