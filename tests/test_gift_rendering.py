"""礼物弹幕渲染单元测试

验证礼物弹幕从 XML 解析到最终渲染的完整链路。
需要 Qt 环境（QApplication），标记为 integration 测试。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from danmakupro.input.event import DanmakuEvent
from danmakupro.layout.active import ActiveDanmaku
from danmakupro.render.active_view import ActiveDanmakuView
from danmakupro.render.segments import RenderSegment
from danmakupro.render.layout_builder import DanmakuLayoutBuilder
from danmakupro.input.parser import parse_xml
from danmakupro.config.models import DEFAULT_CONFIG


@pytest.fixture
def sample_xml(tmp_path: Path) -> Path:
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


# =============================================================================
# 测试：XML 解析
# =============================================================================

class TestGiftParsing:

    def test_parse_gift_events(self, sample_xml: Path):
        events = parse_xml(str(sample_xml), min_gift_price=0.0)
        assert len(events) == 5

        gift_events = [e for e in events if e.is_gift]
        assert len(gift_events) == 3

        gift = gift_events[0]
        assert gift.time == 1.0
        assert gift.user == "测试用户"
        assert gift.gift_name == "小心心"
        assert gift.gift_count == 10
        assert gift.is_gift is True

    def test_gift_price_filter(self, sample_xml: Path):
        events = parse_xml(str(sample_xml), min_gift_price=10.0)
        gift_events = [e for e in events if e.is_gift]
        assert len(gift_events) == 1
        assert gift_events[0].gift_name == "保时捷"

    def test_gift_text_format(self, sample_xml: Path):
        events = parse_xml(str(sample_xml), min_gift_price=0.0)
        gift_events = [e for e in events if e.is_gift]
        assert gift_events[0].text == "小心心x10"
        assert gift_events[1].text == "粉丝团灯牌x1"
        assert gift_events[2].text == "保时捷x1"


# =============================================================================
# 测试：弹幕对象构建与预渲染
# =============================================================================

class TestActiveDanmaku:

    def test_gift_segment_building(self, qapp, asset_loader):
        event = DanmakuEvent(
            time=0, user="测试用户", text="小心心x10",
            is_gift=True, gift_name="小心心", gift_count=10
        )
        asset_loader.load_assets([event])

        builder = DanmakuLayoutBuilder(
            fm=asset_loader.fm,
            emoji_cache=asset_loader.emoji_cache,
            gift_cache=asset_loader.gift_cache,
            max_content_width=800,
            line_height=asset_loader.line_height,
        )
        layout = builder.build(event)
        dm = ActiveDanmaku(event=event, layout=layout, x=DEFAULT_CONFIG.style.danmaku_x)

        assert dm.total_width > 0
        assert dm.height > 0
        assert len(dm.rows) > 0

        all_segments: list[RenderSegment] = []
        for row in dm.rows:
            all_segments.extend(row.segments)
        segment_types = [seg.type for seg in all_segments]
        assert 'text' in segment_types

        if event.gift_name in asset_loader.gift_cache:
            assert 'gift_image' in segment_types or 'spacing' in segment_types

    def test_gift_pre_render(self, qapp, asset_loader):
        event = DanmakuEvent(
            time=0, user="用户", text="保时捷x1",
            is_gift=True, gift_name="保时捷", gift_count=1
        )
        asset_loader.load_assets([event])

        builder = DanmakuLayoutBuilder(
            fm=asset_loader.fm,
            emoji_cache=asset_loader.emoji_cache,
            gift_cache=asset_loader.gift_cache,
            max_content_width=800,
            line_height=asset_loader.line_height,
        )
        layout = builder.build(event)
        dm = ActiveDanmaku(event=event, layout=layout, x=DEFAULT_CONFIG.style.danmaku_x)
        view = ActiveDanmakuView(dm)

        assert view.cached_image is None

        view.pre_render(
            asset_loader.font,
            asset_loader.emoji_cache,
            asset_loader.gift_cache,
            DEFAULT_CONFIG.style.bubble_bg_color,
        )

        assert view.cached_image is not None
        assert isinstance(view.cached_image, QImage)
        assert not view.cached_image.isNull()
        assert view.cached_image.width() == dm.total_width
        assert view.cached_image.height() == dm.height


# =============================================================================
# 测试：端到端渲染验证
# =============================================================================

class TestGiftEndToEnd:

    def test_gift_render_to_canvas(self, qapp, asset_loader):
        from danmakupro.render.renderer import DanmakuRenderer
        from danmakupro.layout.params import LayerParams

        event = DanmakuEvent(
            time=0, user="测试用户", text="小心心x99",
            is_gift=True, gift_name="小心心", gift_count=99
        )
        asset_loader.load_assets([event])

        builder = DanmakuLayoutBuilder(
            fm=asset_loader.fm,
            emoji_cache=asset_loader.emoji_cache,
            gift_cache=asset_loader.gift_cache,
            max_content_width=800,
            line_height=asset_loader.line_height,
        )
        layout = builder.build(event)
        dm = ActiveDanmaku(event=event, layout=layout, x=DEFAULT_CONFIG.style.danmaku_x)
        view = ActiveDanmakuView(dm)
        view.pre_render(
            asset_loader.font,
            asset_loader.emoji_cache,
            asset_loader.gift_cache,
            DEFAULT_CONFIG.style.bubble_bg_color,
        )

        dm.current_y = 100
        dm.x = 30

        layer_params = LayerParams(layer_x=0, layer_y=0, layer_w=400, layer_h=300)
        renderer = DanmakuRenderer(layer_params)

        renderer.canvas.fill(Qt.GlobalColor.transparent)
        renderer.painter.setOpacity(1.0)
        view.render(renderer.painter, int(dm.x), int(dm.current_y))

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

        assert has_content
        renderer.end()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])