from PySide6.QtGui import QImage, QColor

from danmakupro.render.assets import load_image_assets, AssetLoader
from danmakupro.input.event import DanmakuEvent


# =============================================================================
# load_image_assets
# =============================================================================

class TestLoadImageAssets:

    def test_load_valid_png(self, tmp_path):
        emoji_dir = tmp_path / "emoji"
        emoji_dir.mkdir()
        png = emoji_dir / "微笑.png"
        img = QImage(36, 36, QImage.Format.Format_ARGB32)
        img.fill(QColor(255, 255, 255))
        img.save(str(png))

        cache: dict[str, QImage] = {}
        load_image_assets(emoji_dir, {"微笑"}, 36, cache, "emoji")

        assert "微笑" in cache
        assert not cache["微笑"].isNull()

    def test_missing_png_not_in_cache(self, tmp_path):
        emoji_dir = tmp_path / "emoji"
        emoji_dir.mkdir()

        cache: dict[str, QImage] = {}
        load_image_assets(emoji_dir, {"不存在"}, 36, cache, "emoji")

        assert "不存在" not in cache

    def test_nonexistent_dir(self, tmp_path):
        missing_dir = tmp_path / "nonexistent"

        cache: dict[str, QImage] = {}
        load_image_assets(missing_dir, {"test"}, 36, cache, "emoji")

        assert len(cache) == 0

    def test_mixed_valid_and_missing(self, tmp_path):
        emoji_dir = tmp_path / "emoji"
        emoji_dir.mkdir()
        png = emoji_dir / "大笑.png"
        img = QImage(36, 36, QImage.Format.Format_ARGB32)
        img.fill(QColor(255, 255, 255))
        img.save(str(png))

        cache: dict[str, QImage] = {}
        load_image_assets(emoji_dir, {"大笑", "不存在"}, 36, cache, "emoji")

        assert "大笑" in cache
        assert "不存在" not in cache


# =============================================================================
# AssetLoader
# =============================================================================

class TestAssetLoader:

    def test_creation_with_defaults(self, qapp):
        loader = AssetLoader()
        assert loader.font is not None
        assert loader.emoji_cache == {}
        assert loader.gift_cache == {}

    def test_creation_with_custom_font_size(self, qapp):
        loader = AssetLoader(font_size=48)
        assert loader.line_height > 0

    def test_creation_with_custom_assets_dir(self, qapp, tmp_path):
        loader = AssetLoader(assets_dir=str(tmp_path))
        assert loader.emoji_dir == tmp_path / "emoji"
        assert loader.gift_dir == tmp_path / "gift"

    def test_load_assets_populates_caches(self, qapp, tmp_path):
        emoji_dir = tmp_path / "emoji"
        emoji_dir.mkdir()
        png = emoji_dir / "微笑.png"
        img = QImage(36, 36, QImage.Format.Format_ARGB32)
        img.fill(QColor(255, 255, 255))
        img.save(str(png))

        gift_dir = tmp_path / "gift"
        gift_dir.mkdir()
        png2 = gift_dir / "火箭.png"
        img2 = QImage(36, 36, QImage.Format.Format_ARGB32)
        img2.fill(QColor(255, 0, 0))
        img2.save(str(png2))

        loader = AssetLoader(assets_dir=str(tmp_path))
        events = [
            DanmakuEvent(time=0, user="u", text="[微笑]"),
            DanmakuEvent(time=1, user="u", text="火箭x1",
                         is_gift=True, gift_name="火箭", gift_count=1),
        ]
        loader.load_assets(events)

        assert "微笑" in loader.emoji_cache
        assert "火箭" in loader.gift_cache

    def test_load_assets_missing_images(self, qapp, tmp_path):
        loader = AssetLoader(assets_dir=str(tmp_path))
        events = [
            DanmakuEvent(time=0, user="u", text="[不存在]"),
            DanmakuEvent(time=1, user="u", text="不存在x1",
                         is_gift=True, gift_name="不存在", gift_count=1),
        ]
        loader.load_assets(events)

        assert "不存在" not in loader.emoji_cache
        assert "不存在" not in loader.gift_cache

    def test_load_assets_no_emoji_no_gift(self, qapp):
        loader = AssetLoader()
        events = [
            DanmakuEvent(time=0, user="u", text="hello"),
        ]
        loader.load_assets(events)

    def test_load_fonts_for_chars(self, qapp):
        loader = AssetLoader()
        loader._load_fonts_for_chars({"A", "中", " "})