"""基于 XML 文件测试图片资源加载是否完整

解析 XML 弹幕文件，提取所有 Emoji 和礼物名称，
验证对应的 PNG 图片资源是否存在且可正常加载。

XML 路径可通过 --xml-path 参数或 DANMAKU_XML 环境变量指定，
文件不存在时自动 skip。
"""

from pathlib import Path

import pytest
from PySide6.QtGui import QImage

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMOJI_DIR = _PROJECT_ROOT / "assets" / "emoji"
GIFT_DIR = _PROJECT_ROOT / "assets" / "gift"


# Emoji图片测试
class TestEmojiAssets:
    def test_emoji_png_files_exist(self, emoji_names):
        assert len(emoji_names) > 0, "XML 中未找到任何 Emoji 引用"

        missing = []
        for name in sorted(emoji_names):
            png_path = EMOJI_DIR / f"{name}.png"
            if not png_path.exists():
                missing.append(name)

        if missing:
            pytest.fail(
                f"以下 Emoji 缺少对应 PNG 文件 ({len(missing)} 个):\n" +
                "\n".join(f"  - [{name}] → {EMOJI_DIR / f'{name}.png'}" for name in missing)
            )

    def test_emoji_png_can_load(self, qapp, emoji_names):
        assert len(emoji_names) > 0, "XML 中未找到任何 Emoji 引用"

        failed = []
        for name in sorted(emoji_names):
            png_path = EMOJI_DIR / f"{name}.png"
            img = QImage(str(png_path))
            if img.isNull():
                failed.append(name)

        if failed:
            pytest.fail(
                f"以下 Emoji 图片加载失败 ({len(failed)} 个):\n" +
                "\n".join(f"  - [{name}] → {EMOJI_DIR / f'{name}.png'}" for name in failed)
            )

    def test_emoji_png_has_valid_size(self, qapp, emoji_names):
        assert len(emoji_names) > 0, "XML 中未找到任何 Emoji 引用"

        invalid = []
        for name in sorted(emoji_names):
            png_path = EMOJI_DIR / f"{name}.png"
            img = QImage(str(png_path))
            if img.isNull():
                continue
            if img.width() <= 0 or img.height() <= 0:
                invalid.append(f"{name} ({img.width()}x{img.height()})")

        if invalid:
            pytest.fail(
                f"以下 Emoji 图片尺寸无效 ({len(invalid)} 个):\n" +
                "\n".join(f"  - {item}" for item in invalid)
            )


# 礼物图片测试
class TestGiftAssets:
    def test_gift_png_files_exist(self, gift_names):
        assert len(gift_names) > 0, "XML 中未找到任何礼物引用"

        missing = []
        for name in sorted(gift_names):
            png_path = GIFT_DIR / f"{name}.png"
            if not png_path.exists():
                missing.append(name)

        if missing:
            pytest.fail(
                f"以下礼物缺少对应 PNG 文件 ({len(missing)} 个):\n" +
                "\n".join(f"  - {name} → {GIFT_DIR / f'{name}.png'}" for name in missing)
            )

    def test_gift_png_can_load(self, qapp, gift_names):
        assert len(gift_names) > 0, "XML 中未找到任何礼物引用"

        failed = []
        for name in sorted(gift_names):
            png_path = GIFT_DIR / f"{name}.png"
            img = QImage(str(png_path))
            if img.isNull():
                failed.append(name)

        if failed:
            pytest.fail(
                f"以下礼物图片加载失败 ({len(failed)} 个):\n" +
                "\n".join(f"  - {name} → {GIFT_DIR / f'{name}.png'}" for name in failed)
            )

    def test_gift_png_has_valid_size(self, qapp, gift_names):
        assert len(gift_names) > 0, "XML 中未找到任何礼物引用"

        invalid = []
        for name in sorted(gift_names):
            png_path = GIFT_DIR / f"{name}.png"
            img = QImage(str(png_path))
            if img.isNull():
                continue
            if img.width() <= 0 or img.height() <= 0:
                invalid.append(f"{name} ({img.width()}x{img.height()})")

        if invalid:
            pytest.fail(
                f"以下图片尺寸无效 ({len(invalid)} 个):\n" +
                "\n".join(f"  - {item}" for item in invalid)
            )


# XML文件完整性测试
class TestXmlFileIntegrity:
    def test_xml_file_exists(self, xml_path):
        assert xml_path.exists(), f"XML 文件不存在: {xml_path}"

    def test_xml_contains_danmaku_events(self, events):
        danmaku_count = sum(1 for e in events if not e.is_gift)
        assert danmaku_count > 0, "XML 中未找到弹幕事件"

    def test_xml_contains_gift_events(self, events):
        gift_count = sum(1 for e in events if e.is_gift)
        assert gift_count > 0, "XML 中未找到礼物事件"


# 资产加载器集成测试
class TestAssetLoaderIntegration:
    def test_asset_loader_loads_xml_resources(self, qapp, events):
        from danmakupro.asset_loader import AssetLoader

        assert len(events) > 0, "parse_xml 未返回任何事件"

        loader = AssetLoader()
        loader.load_assets(events)

        emoji_count = len(loader.emoji_cache)
        gift_count = len(loader.gift_cache)
        assert emoji_count > 0, "AssetLoader 未缓存任何 Emoji"
        assert gift_count > 0, "AssetLoader 未缓存任何礼物"

        failed = []
        for name, img in loader.emoji_cache.items():
            if img.isNull():
                failed.append(f"[{name}]")
        for name, img in loader.gift_cache.items():
            if img.isNull():
                failed.append(name)

        if failed:
            pytest.fail(
                f"以下图片资源加载失败 ({len(failed)}/{emoji_count + gift_count}):\n" +
                "\n".join(f"  - {item}" for item in failed)
            )