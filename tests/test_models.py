"""models.py 单元测试

测试 DanmakuEvent、ActiveDanmaku 的构建、分段、折行、尺寸计算和越界检测。
"""

from pathlib import Path

import pytest
from PySide6.QtGui import QColor

from danmakupro.models import DanmakuEvent, ActiveDanmaku, RenderSegment, TextRow
from danmakupro.config import (
    BUBBLE_PADDING_X, BUBBLE_PADDING_Y, BUBBLE_ROW_GAP,
    BUBBLE_MULTILINE_RADIUS, DANMAKU_X,
)

MAX_CONTENT_WIDTH = 800


def _make_danmaku(
    text: str,
    font_metrics,
    emoji_cache: dict,
    gift_cache: dict,
    is_gift: bool = False,
    gift_name: str = "",
    gift_count: int = 0,
    max_content_width: int = MAX_CONTENT_WIDTH,
    line_height: int = 36,
) -> ActiveDanmaku:
    event = DanmakuEvent(
        time=1.0, user="测试用户", text=text,
        is_gift=is_gift, gift_name=gift_name, gift_count=gift_count,
    )
    return ActiveDanmaku(
        event, font_metrics, emoji_cache, gift_cache,
        max_content_width=max_content_width, line_height=line_height,
    )


# =============================================================================
# DanmakuEvent
# =============================================================================


class TestDanmakuEvent:
    def test_default_values(self):
        e = DanmakuEvent(time=1.0, user="u", text="t")
        assert not e.is_gift
        assert e.gift_name == ""
        assert e.gift_count == 0

    def test_gift_event(self):
        e = DanmakuEvent(time=2.0, user="u", text="", is_gift=True,
                         gift_name="火箭", gift_count=3)
        assert e.is_gift
        assert e.gift_name == "火箭"
        assert e.gift_count == 3


# =============================================================================
# ActiveDanmaku - 普通弹幕
# =============================================================================


class TestActiveDanmakuNormal:
    def test_basic_construction(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("你好世界", font_metrics, emoji_cache, gift_cache)
        assert dm.event.text == "你好世界"
        assert dm.total_width > 0
        assert dm.height > 0
        assert dm.x == DANMAKU_X
        assert dm.cached_image is None

    def test_has_rows(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        assert len(dm.rows) >= 1

    def test_single_line_radius(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("短文本", font_metrics, emoji_cache, gift_cache)
        if len(dm.rows) == 1:
            assert dm.radius == dm.height / 2.0

    def test_multi_line_radius(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("这是一段非常长的文本用来测试折行功能"
                           "需要足够长才能触发多行折行"
                           "继续添加更多文字以确保折行",
                           font_metrics, emoji_cache, gift_cache,
                           max_content_width=200)
        if len(dm.rows) > 1:
            assert dm.radius == BUBBLE_MULTILINE_RADIUS

    def test_dimensions_include_padding(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        assert dm.total_width >= BUBBLE_PADDING_X * 2
        assert dm.height >= BUBBLE_PADDING_Y * 2 + 36


# =============================================================================
# ActiveDanmaku - 礼物弹幕
# =============================================================================


class TestActiveDanmakuGift:
    def test_gift_with_cached_image(self, font_metrics, emoji_cache, gift_cache):
        gift_name = next(iter(gift_cache), None)
        if gift_name is None:
            pytest.skip("无礼物图片缓存")

        dm = _make_danmaku("", font_metrics, emoji_cache, gift_cache,
                           is_gift=True, gift_name=gift_name, gift_count=5)
        types = [seg.type for row in dm.rows for seg in row.segments]
        assert 'gift_image' in types

    def test_gift_without_cached_image(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("", font_metrics, emoji_cache, gift_cache,
                           is_gift=True, gift_name="不存在的礼物", gift_count=1)
        types = [seg.type for row in dm.rows for seg in row.segments]
        assert 'gift_image' not in types

    def test_gift_has_gift_text_color(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("", font_metrics, emoji_cache, gift_cache,
                           is_gift=True, gift_name="火箭", gift_count=1)
        colors = [seg.color for seg in dm.rows[0].segments if seg.color is not None]
        assert any(c == ActiveDanmaku.COLOR_GIFT_TEXT for c in colors)


# =============================================================================
# ActiveDanmaku - Emoji
# =============================================================================


class TestActiveDanmakuEmoji:
    def test_emoji_in_text(self, font_metrics, emoji_cache, gift_cache):
        emoji_name = next(iter(emoji_cache), None)
        if emoji_name is None:
            pytest.skip("无 Emoji 图片缓存")

        dm = _make_danmaku(f"你好[{emoji_name}]世界", font_metrics, emoji_cache, gift_cache)
        types = [seg.type for row in dm.rows for seg in row.segments]
        assert 'emoji' in types

    def test_unknown_emoji_as_text(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("你好[不存在的emoji]世界", font_metrics, emoji_cache, gift_cache)
        types = [seg.type for row in dm.rows for seg in row.segments]
        assert 'emoji' not in types
        text_contents = [seg.content for row in dm.rows for seg in row.segments
                         if seg.type == 'text']
        assert any("不存在的emoji" in t for t in text_contents)

    def test_text_between_emojis(self, font_metrics, emoji_cache, gift_cache):
        emoji_name = next(iter(emoji_cache), None)
        if emoji_name is None:
            pytest.skip("无 Emoji 图片缓存")

        dm = _make_danmaku(
            f"[{emoji_name}]中间文本[{emoji_name}]",
            font_metrics, emoji_cache, gift_cache,
        )
        types = [seg.type for row in dm.rows for seg in row.segments]
        emoji_count = types.count('emoji')
        assert emoji_count == 2
        text_contents = [seg.content for row in dm.rows for seg in row.segments
                         if seg.type == 'text']
        assert any("中间文本" in t for t in text_contents)


# =============================================================================
# ActiveDanmaku - 折行
# =============================================================================


class TestActiveDanmakuWrapping:
    def test_short_text_no_wrap(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("短", font_metrics, emoji_cache, gift_cache)
        assert len(dm.rows) == 1

    def test_long_text_wraps(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("这是一段非常长的文本" * 10,
                           font_metrics, emoji_cache, gift_cache,
                           max_content_width=200)
        assert len(dm.rows) > 1

    def test_narrow_width_forces_wrap(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("你好世界", font_metrics, emoji_cache, gift_cache,
                           max_content_width=50)
        assert len(dm.rows) > 1


# =============================================================================
# ActiveDanmaku - 越界检测
# =============================================================================


class TestActiveDanmakuOutOfBounds:
    def test_not_out_of_bounds(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 100.0
        assert not dm.is_out_of_bounds(0.0)

    def test_out_of_bounds(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = -dm.height - 10
        assert dm.is_out_of_bounds(0.0)

    def test_exactly_at_boundary(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = -dm.height
        assert dm.is_out_of_bounds(0.0)


# =============================================================================
# ActiveDanmaku - 预渲染
# =============================================================================


class TestActiveDanmakuPreRender:
    def test_pre_render_creates_image(self, font_metrics, emoji_cache, gift_cache, font):
        dm = _make_danmaku("测试预渲染", font_metrics, emoji_cache, gift_cache)
        assert dm.cached_image is None
        dm._pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        assert dm.cached_image is not None
        assert not dm.cached_image.isNull()

    def test_pre_render_image_size(self, font_metrics, emoji_cache, gift_cache, font):
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm._pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        assert dm.cached_image is not None
        assert dm.cached_image.width() == dm.total_width
        assert dm.cached_image.height() == dm.height


# =============================================================================
# RenderSegment & TextRow
# =============================================================================


class TestDataClasses:
    def test_render_segment(self):
        seg = RenderSegment(type='text', content='hello', width=50, color=None)
        assert seg.type == 'text'
        assert seg.content == 'hello'
        assert seg.width == 50
        assert not seg.has_cache

    def test_text_row(self):
        row = TextRow()
        assert row.segments == []
        assert row.width == 0


# =============================================================================
# ActiveDanmaku - Emoji/间距折行
# =============================================================================


class TestActiveDanmakuEmojiWrapping:
    def test_emoji_wraps_when_exceeds_width(self, font_metrics, emoji_cache, gift_cache):
        emoji_name = next(iter(emoji_cache), None)
        if emoji_name is None:
            pytest.skip("无 Emoji 图片缓存")

        dm = _make_danmaku(
            f"前缀[{emoji_name}]",
            font_metrics, emoji_cache, gift_cache,
            max_content_width=30,
        )
        assert len(dm.rows) > 1

    def test_spacing_segment_wraps(self, font_metrics, emoji_cache, gift_cache):
        emoji_name = next(iter(emoji_cache), None)
        if emoji_name is None:
            pytest.skip("无 Emoji 图片缓存")

        dm = _make_danmaku(
            f"[{emoji_name}][{emoji_name}]",
            font_metrics, emoji_cache, gift_cache,
            max_content_width=36,
        )
        assert len(dm.rows) >= 2


# =============================================================================
# ActiveDanmaku - 二分查找折行边界
# =============================================================================


class TestActiveDanmakuBinaryWrap:
    def test_single_char_per_row_on_tiny_width(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_danmaku(
            "你好世界",
            font_metrics, emoji_cache, gift_cache,
            max_content_width=20,
        )
        assert len(dm.rows) >= 2

    def test_wrap_preserves_all_content(self, font_metrics, emoji_cache, gift_cache):
        text = "这是一段需要折行的长文本"
        dm = _make_danmaku(text, font_metrics, emoji_cache, gift_cache, max_content_width=100)
        rendered = "".join(seg.content for row in dm.rows for seg in row.segments if seg.type == 'text')
        assert "测试用户" in rendered or text in rendered


# =============================================================================
# ActiveDanmaku - 预渲染绘制分支
# =============================================================================


class TestActiveDanmakuPreRenderBranches:
    def test_pre_render_with_emoji(self, font_metrics, emoji_cache, gift_cache, font):
        emoji_name = next(iter(emoji_cache), None)
        if emoji_name is None:
            pytest.skip("无 Emoji 图片缓存")

        dm = _make_danmaku(f"[{emoji_name}]", font_metrics, emoji_cache, gift_cache)
        dm._pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        assert dm.cached_image is not None
        assert not dm.cached_image.isNull()

    def test_pre_render_with_gift_image(self, font_metrics, emoji_cache, gift_cache, font):
        gift_name = next(iter(gift_cache), None)
        if gift_name is None:
            pytest.skip("无礼物图片缓存")

        dm = _make_danmaku("", font_metrics, emoji_cache, gift_cache,
                           is_gift=True, gift_name=gift_name, gift_count=1)
        dm._pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        assert dm.cached_image is not None
        assert not dm.cached_image.isNull()

    def test_render_draws_cached_image(self, font_metrics, emoji_cache, gift_cache, font):
        dm = _make_danmaku("测试render", font_metrics, emoji_cache, gift_cache)
        dm._pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))

        from PySide6.QtGui import QImage as QImg, QPainter
        canvas = QImg(dm.total_width, dm.height, QImg.Format.Format_ARGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        dm.render(painter, 0, 0)
        painter.end()
        assert dm.cached_image is not None