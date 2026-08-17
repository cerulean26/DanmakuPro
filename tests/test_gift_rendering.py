"""礼物弹幕渲染单元测试

验证礼物弹幕从 XML 解析到最终渲染的完整链路。
需要 Qt 环境（QApplication），标记为 integration 测试。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage

from danmakupro.input.models import DanmakuEvent, ActiveDanmaku, RenderSegment
from danmakupro.input.parser import parse_xml
from danmakupro.render.assets import AssetLoader
from danmakupro.config.models import DEFAULT_CONFIG


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def qt_app():
    """提供 Qt 应用实例（模块级，只创建一次）"""
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication([])
    yield app


@pytest.fixture
def sample_xml(tmp_path: Path) -> Path:
    """创建包含礼物弹幕的测试 XML 文件"""
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<i>
    <d p="0.5,1,25,16777215,0,0,0,0">普通弹幕文本</d>
    <gift ts="1.0" giftname="小心心" giftcount="10" price="100" user="测试用户"></gift>
    <gift ts="2.0" giftname="粉丝团灯牌" giftcount="1" price="100" user="粉丝A"></gift>
    <gift ts="3.0" giftname="保时捷" giftcount="1" price="12000" user="土豪"></gift>
    <d p="4.0,1,25,16777215,0,0,0,0">另一条弹幕</d>
</i>
"""
    xml_path = tmp_path / "test_gifts.xml"
    xml_path.write_text(xml_content, encoding="utf-8")
    return xml_path


@pytest.fixture
def asset_loader(qt_app) -> AssetLoader:
    """提供资源加载器实例"""
    return AssetLoader(font_size=DEFAULT_CONFIG.style.font_size)


# =============================================================================
# 测试：XML 解析
# =============================================================================

class TestGiftParsing:
    """测试礼物弹幕的 XML 解析"""

    def test_parse_gift_events(self, sample_xml: Path):
        """验证能正确解析礼物事件"""
        events = parse_xml(str(sample_xml), min_gift_price=0.0)

        # 总共 5 个事件（2 普通弹幕 + 3 礼物）
        assert len(events) == 5

        # 筛选礼物事件
        gift_events = [e for e in events if e.is_gift]
        assert len(gift_events) == 3

        # 验证礼物属性
        gift = gift_events[0]
        assert gift.time == 1.0
        assert gift.user == "测试用户"
        assert gift.gift_name == "小心心"
        assert gift.gift_count == 10
        assert gift.is_gift is True

    def test_gift_price_filter(self, sample_xml: Path):
        """验证礼物价格过滤功能"""
        # 设置最低价格为 1000，只保留保时捷（12000）
        events = parse_xml(str(sample_xml), min_gift_price=1000.0)
        gift_events = [e for e in events if e.is_gift]

        assert len(gift_events) == 1
        assert gift_events[0].gift_name == "保时捷"

    def test_gift_text_format(self, sample_xml: Path):
        """验证礼物文本格式"""
        events = parse_xml(str(sample_xml), min_gift_price=0.0)
        gift_events = [e for e in events if e.is_gift]

        # 文本格式应为 "{gift_name}x{gift_count}"
        assert gift_events[0].text == "小心心x10"
        assert gift_events[1].text == "粉丝团灯牌x1"
        assert gift_events[2].text == "保时捷x1"


# =============================================================================
# 测试：资源加载
# =============================================================================

class TestGiftAssetLoading:
    """测试礼物图片资源加载"""

    def test_load_gift_images(self, qt_app, asset_loader: AssetLoader, sample_xml: Path):
        """验证礼物图片加载：存在的图片进入缓存，缺失的不进入"""
        events = parse_xml(str(sample_xml), min_gift_price=0.0)
        asset_loader.load_assets(events)

        # 验证缓存中的图片是有效的 QImage
        for name, img in asset_loader.gift_cache.items():
            assert isinstance(img, QImage)
            assert not img.isNull(), f"礼物图片 '{name}' 为空"

    def test_missing_gift_not_in_cache(self, qt_app, asset_loader: AssetLoader):
        """验证缺失礼物图片不会进入缓存，只记录日志"""
        # 使用一个不存在的礼物名
        events = [
            DanmakuEvent(time=0, user="用户", text="不存在的礼物x1",
                        is_gift=True, gift_name="不存在的礼物", gift_count=1)
        ]

        asset_loader.load_assets(events)

        # 缺失的礼物不应在缓存中
        assert "不存在的礼物" not in asset_loader.gift_cache


# =============================================================================
# 测试：弹幕对象构建
# =============================================================================

class TestActiveDanmaku:
    """测试活跃弹幕对象的构建和渲染段落"""

    def test_gift_segment_building(self, qt_app, asset_loader: AssetLoader):
        """验证礼物弹幕的渲染段落构建"""
        event = DanmakuEvent(
            time=0, user="测试用户", text="小心心x10",
            is_gift=True, gift_name="小心心", gift_count=10
        )

        # 先加载资源（确保礼物图片在缓存中）
        asset_loader.load_assets([event])

        dm = ActiveDanmaku(
            event=event,
            font_metrics=asset_loader.fm,
            emoji_cache=asset_loader.emoji_cache,
            gift_cache=asset_loader.gift_cache,
            max_content_width=800,
            line_height=asset_loader.line_height,
        )

        # 验证尺寸已计算
        assert dm.total_width > 0
        assert dm.height > 0

        # 验证有渲染行
        assert len(dm.rows) > 0

        # 验证行中包含预期的段落类型
        all_segments: list[RenderSegment] = []
        for row in dm.rows:
            all_segments.extend(row.segments)

        segment_types = [seg.type for seg in all_segments]
        assert 'text' in segment_types, "应包含文本段落"

        # 如果礼物图片存在，应包含 gift_image 段落
        if event.gift_name in asset_loader.gift_cache:
            assert 'gift_image' in segment_types or 'spacing' in segment_types, \
                "应包含礼物图片或间距段落"

    def test_gift_pre_render(self, qt_app, asset_loader: AssetLoader):
        """验证礼物弹幕的预渲染"""
        event = DanmakuEvent(
            time=0, user="用户", text="保时捷x1",
            is_gift=True, gift_name="保时捷", gift_count=1
        )

        asset_loader.load_assets([event])

        dm = ActiveDanmaku(
            event=event,
            font_metrics=asset_loader.fm,
            emoji_cache=asset_loader.emoji_cache,
            gift_cache=asset_loader.gift_cache,
            max_content_width=800,
            line_height=asset_loader.line_height,
        )

        # 初始状态：缓存图片为 None
        assert dm.cached_image is None

        # 预渲染
        dm.pre_render(
            asset_loader.font,
            asset_loader.emoji_cache,
            asset_loader.gift_cache,
            asset_loader.bg_color,
        )

        # 预渲染后：缓存图片应存在且有效
        assert dm.cached_image is not None
        assert isinstance(dm.cached_image, QImage)
        assert not dm.cached_image.isNull()
        assert dm.cached_image.width() == dm.total_width
        assert dm.cached_image.height() == dm.height


# =============================================================================
# 测试：端到端渲染验证
# =============================================================================

class TestGiftEndToEnd:
    """端到端测试：验证礼物能正确渲染到画布"""

    def test_gift_render_to_canvas(self, qt_app, asset_loader: AssetLoader):
        """验证礼物弹幕能渲染到画布并产生非透明像素"""
        from danmakupro.render.renderer import DanmakuRenderer
        from danmakupro.layout.params import LayerParams

        event = DanmakuEvent(
            time=0, user="测试用户", text="小心心x99",
            is_gift=True, gift_name="小心心", gift_count=99
        )

        asset_loader.load_assets([event])

        dm = ActiveDanmaku(
            event=event,
            font_metrics=asset_loader.fm,
            emoji_cache=asset_loader.emoji_cache,
            gift_cache=asset_loader.gift_cache,
            max_content_width=800,
            line_height=asset_loader.line_height,
        )
        dm.pre_render(
            asset_loader.font,
            asset_loader.emoji_cache,
            asset_loader.gift_cache,
            asset_loader.bg_color,
        )

        # 设置弹幕位置
        dm.current_y = 100
        dm.x = 30

        # 创建渲染器和画布
        layer_params = LayerParams(layer_x=0, layer_y=0, layer_w=400, layer_h=300)
        renderer = DanmakuRenderer(layer_params)

        # 手动渲染（不依赖 layout_params）
        renderer.canvas.fill(Qt.GlobalColor.transparent)
        renderer.painter.setOpacity(1.0)
        dm.render(renderer.painter, int(dm.x), int(dm.current_y))

        # 验证画布上有非透明像素（礼物被绘制了）
        has_content = False
        for y in range(renderer.canvas.height()):
            for x in range(renderer.canvas.width()):
                pixel = renderer.canvas.pixel(x, y)
                alpha = (pixel >> 24) & 0xFF
                if alpha > 0:
                    has_content = True
                    break
            if has_content:
                break

        assert has_content, "画布上应有礼物弹幕的像素内容"

        renderer.end()


# =============================================================================
# 运行入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])