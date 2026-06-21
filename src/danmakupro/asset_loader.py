"""资源加载模块

负责字体初始化、Emoji 和礼物图片的按需预加载与缓存管理。
"""

from pathlib import Path

from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QGuiApplication, QImage, QColor, QFont, QFontMetrics, QFontDatabase,
)

from .config import FONT_SIZE
from .models import DanmakuEvent
from .utils import extract_emoji_names


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class AssetLoader:
    """资源加载器：管理字体、Emoji 和礼物图片的加载与缓存。

    Attributes:
        font: 弹幕渲染字体
        fm: 字体度量信息
        line_height: 行高（像素）
        emoji_cache: Emoji 图片缓存 {name: QImage}
        gift_cache: 礼物图片缓存 {name: QImage}
        bg_color: 弹幕背景色
    """

    def __init__(self):
        self.emoji_cache: dict[str, QImage] = {}
        self.gift_cache: dict[str, QImage] = {}
        self.bg_color = QColor(20, 20, 20, 150)

        _ = QGuiApplication.instance() or QGuiApplication([])

        self._init_fonts()

        self.emoji_dir = _PROJECT_ROOT / "assets" / "emoji"
        self.gift_dir = _PROJECT_ROOT / "assets" / "gift"

    def _init_fonts(self) -> None:
        """加载自定义字体并配置弹幕字体。

        按优先级顺序尝试字体族：微软雅黑 -> Tai Le -> Noto Sans -> Emoji -> Symbol。
        字体文件位于 assets/fonts/ 目录。
        """
        font_dir = _PROJECT_ROOT / "assets" / "fonts"
        font_map = {
            "Microsoft YaHei": "msyhbd.ttc",
            "Noto Sans Tai Tham": "NotoSansTaiTham-Regular.ttf",
            "Segoe UI Emoji": "seguiemj.ttf",
            "Segoe UI Symbol": "seguisym.ttf",
        }
        for family, filename in font_map.items():
            path = font_dir / filename
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))

        self.font = QFont()
        self.font.setFamilies([
            "Microsoft YaHei",
            "Microsoft Tai Le",
            "Noto Sans Tai Tham",
            "Segoe UI Emoji",
            "Segoe UI Symbol",
        ])
        self.font.setPointSize(FONT_SIZE)
        self.font.setBold(True)
        self.font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)
        self.fm = QFontMetrics(self.font)
        self.line_height = self.fm.height()

    def load_assets(self, events: list[DanmakuEvent]) -> None:
        """分析弹幕事件，按需精确预加载 Emoji 和礼物图片。

        遍历所有弹幕事件，提取用到的 Emoji 名称和礼物名称，
        然后只加载实际需要的图片资源。

        Args:
            events: 弹幕事件列表
        """
        logger.info("[2/5] 正在预加载资源...")
        used_emoji_names: set[str] = set()
        used_gift_names: set[str] = set()

        for ev in events:
            if ev.is_gift:
                used_gift_names.add(ev.gift_name)
            elif '[' in ev.text and ']' in ev.text:
                for name in extract_emoji_names(ev.text):
                    used_emoji_names.add(name)

        self._load_image_assets(self.emoji_dir, used_emoji_names, self.emoji_cache, "Emoji")
        self._load_image_assets(self.gift_dir, used_gift_names, self.gift_cache, "礼物")

    def _load_image_assets(
        self,
        asset_dir: Path,
        asset_names: set[str],
        cache: dict[str, QImage],
        asset_type: str,
    ) -> None:
        """通用图片资源加载方法。

        从指定目录加载 PNG 图片，缩放到行高大小并缓存。

        Args:
            asset_dir: 资源目录路径
            asset_names: 需要加载的资源名称集合（不含扩展名）
            cache: 目标缓存字典
            asset_type: 资源类型名称（用于日志）
        """
        if not asset_dir.exists():
            logger.warning(f"{asset_type} 文件夹不存在，跳过预加载")
            return

        logger.info(f"正在预加载 {asset_type}...")
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
                logger.debug(f"图片加载失败: {file_path}")
        logger.info(f"{asset_type} 预加载完成 | 数量={len(cache)}")