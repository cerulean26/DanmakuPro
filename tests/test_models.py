"""models.py 单元测试

测试 DanmakuEvent、ActiveDanmaku 的构建、分段、折行、尺寸计算和越界检测。
"""

from pathlib import Path

import pytest
from PySide6.QtGui import QColor

from danmakupro.input.models import DanmakuEvent, ActiveDanmaku, RenderSegment, TextRow
from danmakupro.config import DEFAULT_CONFIG

style = DEFAULT_CONFIG.style

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
    """创建 ActiveDanmaku 测试实例。"""
    event = DanmakuEvent(
        time=1.0, user="测试用户", text=text,
        is_gift=is_gift, gift_name=gift_name, gift_count=gift_count,
    )
    return ActiveDanmaku(
        event, font_metrics, emoji_cache, gift_cache,
        max_content_width=max_content_width, line_height=line_height,
    )


# =============================================================================
# DanmakuEvent 数据类
# =============================================================================


class TestDanmakuEvent:
    """测试弹幕事件数据类的默认值和构造。"""

    def test_default_values(self):
        """非礼物弹幕的默认值应为空/零。"""
        e = DanmakuEvent(time=1.0, user="u", text="t")
        assert not e.is_gift
        assert e.gift_name == ""
        assert e.gift_count == 0

    def test_gift_event(self):
        """礼物弹幕应正确保存礼物属性。"""
        e = DanmakuEvent(time=2.0, user="u", text="", is_gift=True,
                         gift_name="火箭", gift_count=3)
        assert e.is_gift
        assert e.gift_name == "火箭"
        assert e.gift_count == 3


# =============================================================================
# ActiveDanmaku - 普通弹幕
# =============================================================================


class TestActiveDanmakuNormal:
    """测试普通文本弹幕的构建、尺寸和行属性。"""

    def test_basic_construction(self, font_metrics, emoji_cache, gift_cache):
        """构造后应具有正尺寸、正确的 X 偏移和空缓存。"""
        dm = _make_danmaku("你好世界", font_metrics, emoji_cache, gift_cache)
        assert dm.event.text == "你好世界"
        assert dm.total_width > 0
        assert dm.height > 0
        assert dm.x == style.danmaku_x
        assert dm.cached_image is None

    def test_has_rows(self, font_metrics, emoji_cache, gift_cache):
        """任何弹幕应至少有一行渲染行。"""
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        assert len(dm.rows) >= 1

    def test_single_line_radius(self, font_metrics, emoji_cache, gift_cache):
        """单行弹幕的圆角半径应为高度的一半。"""
        dm = _make_danmaku("短文本", font_metrics, emoji_cache, gift_cache)
        if len(dm.rows) == 1:
            assert dm.radius == dm.height / 2.0

    def test_multi_line_radius(self, font_metrics, emoji_cache, gift_cache):
        """多行弹幕的圆角半径应为配置的多行圆角值。"""
        dm = _make_danmaku("这是一段非常长的文本用来测试折行功能"
                           "需要足够长才能触发多行折行"
                           "继续添加更多文字以确保折行",
                           font_metrics, emoji_cache, gift_cache,
                           max_content_width=200)
        if len(dm.rows) > 1:
            assert dm.radius == style.bubble_multiline_radius

    def test_dimensions_include_padding(self, font_metrics, emoji_cache, gift_cache):
        """气泡尺寸应包含水平和垂直内边距。"""
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        assert dm.total_width >= style.bubble_padding_x * 2
        assert dm.height >= style.bubble_padding_y * 2 + 36


# =============================================================================
# ActiveDanmaku - 礼物弹幕
# =============================================================================


class TestActiveDanmakuGift:
    """测试礼物弹幕的段落构建和颜色。"""

    def test_gift_with_cached_image(self, font_metrics, emoji_cache, gift_cache):
        """有缓存的礼物图片应生成 gift_image 段落。"""
        gift_name = next(iter(gift_cache), None)
        if gift_name is None:
            pytest.skip("无礼物图片缓存")

        dm = _make_danmaku("", font_metrics, emoji_cache, gift_cache,
                           is_gift=True, gift_name=gift_name, gift_count=5)
        types = [seg.type for row in dm.rows for seg in row.segments]
        assert 'gift_image' in types

    def test_gift_without_cached_image(self, font_metrics, emoji_cache, gift_cache):
        """无缓存的礼物图片不应生成 gift_image 段落。"""
        dm = _make_danmaku("", font_metrics, emoji_cache, gift_cache,
                           is_gift=True, gift_name="不存在的礼物", gift_count=1)
        types = [seg.type for row in dm.rows for seg in row.segments]
        assert 'gift_image' not in types

    def test_gift_has_gift_text_color(self, font_metrics, emoji_cache, gift_cache):
        """礼物弹幕的文本段落应使用礼物文本颜色。"""
        dm = _make_danmaku("", font_metrics, emoji_cache, gift_cache,
                           is_gift=True, gift_name="火箭", gift_count=1)
        colors = [seg.color for seg in dm.rows[0].segments if seg.color is not None]
        assert any(c == ActiveDanmaku.COLOR_GIFT_TEXT for c in colors)


# =============================================================================
# ActiveDanmaku - Emoji
# =============================================================================


class TestActiveDanmakuEmoji:
    """测试 Emoji 在弹幕文本中的解析和段落生成。"""

    def test_emoji_in_text(self, font_metrics, emoji_cache, gift_cache):
        """已缓存的 Emoji 应生成 emoji 段落。"""
        emoji_name = next(iter(emoji_cache), None)
        if emoji_name is None:
            pytest.skip("无 Emoji 图片缓存")

        dm = _make_danmaku(f"你好[{emoji_name}]世界", font_metrics, emoji_cache, gift_cache)
        types = [seg.type for row in dm.rows for seg in row.segments]
        assert 'emoji' in types

    def test_unknown_emoji_as_text(self, font_metrics, emoji_cache, gift_cache):
        """未缓存的 Emoji 应作为纯文本段落处理。"""
        dm = _make_danmaku("你好[不存在的emoji]世界", font_metrics, emoji_cache, gift_cache)
        types = [seg.type for row in dm.rows for seg in row.segments]
        assert 'emoji' not in types
        text_contents = [seg.content for row in dm.rows for seg in row.segments
                         if seg.type == 'text']
        assert any("不存在的emoji" in t for t in text_contents)

    def test_text_between_emojis(self, font_metrics, emoji_cache, gift_cache):
        """两个 Emoji 之间的文本应保留为 text 段落。"""
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
    """测试文本折行逻辑。"""

    def test_short_text_no_wrap(self, font_metrics, emoji_cache, gift_cache):
        """短文本不应折行。"""
        dm = _make_danmaku("短", font_metrics, emoji_cache, gift_cache)
        assert len(dm.rows) == 1

    def test_long_text_wraps(self, font_metrics, emoji_cache, gift_cache):
        """超长文本应触发折行。"""
        dm = _make_danmaku("这是一段非常长的文本" * 10,
                           font_metrics, emoji_cache, gift_cache,
                           max_content_width=200)
        assert len(dm.rows) > 1

    def test_narrow_width_forces_wrap(self, font_metrics, emoji_cache, gift_cache):
        """极窄宽度应强制折行。"""
        dm = _make_danmaku("你好世界", font_metrics, emoji_cache, gift_cache,
                           max_content_width=50)
        assert len(dm.rows) > 1


# =============================================================================
# ActiveDanmaku - 越界检测
# =============================================================================


class TestActiveDanmakuOutOfBounds:
    """测试弹幕越界检测逻辑。"""

    def test_not_out_of_bounds(self, font_metrics, emoji_cache, gift_cache):
        """在边界内的弹幕不应判定为越界。"""
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 100.0
        assert not dm.is_out_of_bounds(0.0)

    def test_out_of_bounds(self, font_metrics, emoji_cache, gift_cache):
        """完全超出顶部边界的弹幕应判定为越界。"""
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = -dm.height - 10
        assert dm.is_out_of_bounds(0.0)

    def test_exactly_at_boundary(self, font_metrics, emoji_cache, gift_cache):
        """恰好位于边界上的弹幕应判定为越界。"""
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = -dm.height
        assert dm.is_out_of_bounds(0.0)


# =============================================================================
# ActiveDanmaku - 预渲染
# =============================================================================


class TestActiveDanmakuPreRender:
    """测试弹幕预渲染到缓存图片。"""

    def test_pre_render_creates_image(self, font_metrics, emoji_cache, gift_cache, font):
        """预渲染应创建有效的缓存图片。"""
        dm = _make_danmaku("测试预渲染", font_metrics, emoji_cache, gift_cache)
        assert dm.cached_image is None
        dm.pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        assert dm.cached_image is not None
        assert not dm.cached_image.isNull()

    def test_pre_render_image_size(self, font_metrics, emoji_cache, gift_cache, font):
        """缓存图片尺寸应与弹幕尺寸一致。"""
        dm = _make_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        assert dm.cached_image is not None
        assert dm.cached_image.width() == dm.total_width
        assert dm.cached_image.height() == dm.height


# =============================================================================
# RenderSegment & TextRow
# =============================================================================


class TestDataClasses:
    """测试渲染段落和文本行数据类。"""

    def test_render_segment(self):
        """RenderSegment 应正确存储类型、内容和宽度。"""
        seg = RenderSegment(type='text', content='hello', width=50, color=None)
        assert seg.type == 'text'
        assert seg.content == 'hello'
        assert seg.width == 50
        assert not seg.has_cache

    def test_text_row(self):
        """TextRow 初始状态应为空行。"""
        row = TextRow()
        assert row.segments == []
        assert row.width == 0