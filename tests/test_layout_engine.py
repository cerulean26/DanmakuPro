"""layout_engine.py 单元测试

测试布局引擎的全部静态方法：calculate_params、preload_danmaku_objects、
spawn_new_danmakus、update_positions、handle_collisions、recycle_out_of_bounds。
"""

import pytest
from PySide6.QtGui import QColor

from danmakupro.layout.engine import LayoutEngine, LayoutContext
from danmakupro.layout.params import LayoutParams
from danmakupro.input.event import DanmakuEvent
from danmakupro.layout.active import ActiveDanmaku
from danmakupro.render.layout_builder import DanmakuLayoutBuilder
from danmakupro.config import DEFAULT_CONFIG

MAX_CONTENT_WIDTH = 800
LINE_HEIGHT = 36  # 与 conftest.py 保持一致，QFontMetrics.height() 实测值


# =============================================================================
# 测试辅助函数
# =============================================================================


def _make_active_danmaku(
    text: str,
    font_metrics,
    emoji_cache: dict,
    gift_cache: dict,
    *,
    time: float = 1.0,
    is_gift: bool = False,
    gift_name: str = "",
    gift_count: int = 0,
    max_content_width: int = MAX_CONTENT_WIDTH,
    line_height: int = 36,
) -> ActiveDanmaku:
    """创建 ActiveDanmaku 测试实例。"""
    event = DanmakuEvent(
        time=time, user="用户", text=text,
        is_gift=is_gift, gift_name=gift_name, gift_count=gift_count,
    )
    builder = DanmakuLayoutBuilder(
        fm=font_metrics,
        emoji_cache=emoji_cache,
        gift_cache=gift_cache,
        max_content_width=max_content_width,
        line_height=line_height,
        style=DEFAULT_CONFIG.style,
    )
    layout = builder.build(event)
    return ActiveDanmaku(event=event, layout=layout, x=DEFAULT_CONFIG.style.danmaku_x)


def _make_layout_params(
    w: int = 1920, h: int = 1080, line_height: int = LINE_HEIGHT,
) -> LayoutParams:
    """使用与 calculate_params 相同的公式创建 LayoutParams。"""
    cfg = DEFAULT_CONFIG
    bubble_height = 2 * cfg.style.bubble_padding_y + line_height
    row_height = bubble_height + cfg.style.bubble_vertical_gap
    text_h = cfg.ratio.max_text_rows * row_height
    gift_h = cfg.ratio.max_gift_rows * row_height
    bottom = h - cfg.ratio.bottom_margin
    text_top = bottom - text_h
    gift_top = text_top - gift_h
    text_w = int(w * cfg.ratio.text_width_ratio)
    return LayoutParams(
        bottom=bottom,
        text_h=text_h,
        text_top=text_top,
        text_w=text_w,
        gap=cfg.style.bubble_vertical_gap,
        gift_top=gift_top,
        gift_h=gift_h,
    )


# =============================================================================
# calculate_params
# =============================================================================


class TestCalculateParams:
    """测试 calculate_params：布局参数和渲染层参数计算。"""

    def test_1080p(self):
        lp, layer = LayoutEngine.calculate_params(1920, 1080, line_height=LINE_HEIGHT)
        cfg = DEFAULT_CONFIG
        bubble_height = 2 * cfg.style.bubble_padding_y + LINE_HEIGHT
        row_height = bubble_height + cfg.style.bubble_vertical_gap
        assert lp.bottom == 1080 - cfg.ratio.bottom_margin
        assert lp.text_h == cfg.ratio.max_text_rows * row_height
        assert lp.text_w == int(1920 * cfg.ratio.text_width_ratio)
        assert lp.text_top == lp.bottom - lp.text_h
        assert lp.gap == cfg.style.bubble_vertical_gap

    def test_720p(self):
        lp, layer = LayoutEngine.calculate_params(1280, 720, line_height=LINE_HEIGHT)
        cfg = DEFAULT_CONFIG
        assert lp.bottom == 720 - cfg.ratio.bottom_margin
        assert lp.text_w == int(1280 * cfg.ratio.text_width_ratio)

    def test_layer_params(self):
        lp, layer = LayoutEngine.calculate_params(1920, 1080, line_height=LINE_HEIGHT)
        style = DEFAULT_CONFIG.style
        assert layer.layer_x == style.danmaku_x
        assert layer.layer_y == lp.gift_top
        assert layer.layer_h == lp.bottom - lp.gift_top
        expected_w = lp.text_w + style.layer_width_extra
        assert layer.layer_w == expected_w

    def test_layer_width_clamped(self):
        style = DEFAULT_CONFIG.style
        tiny_w = style.danmaku_x + 10
        lp, layer = LayoutEngine.calculate_params(tiny_w, 1080, line_height=LINE_HEIGHT)
        assert layer.layer_w <= tiny_w - style.danmaku_x

    def test_params_frozen(self):
        lp, layer = LayoutEngine.calculate_params(1920, 1080, line_height=LINE_HEIGHT)
        with pytest.raises(AttributeError):
            setattr(lp, "bottom", 0)

    def test_gift_zone_layout(self):
        """验证礼物区在文本区上方。"""
        lp, layer = LayoutEngine.calculate_params(1920, 1080, line_height=LINE_HEIGHT)
        assert lp.gift_top < lp.text_top
        assert lp.gift_h > 0
        assert lp.gift_top + lp.gift_h == lp.text_top


# =============================================================================
# preload_danmaku_objects
# =============================================================================


class TestPreloadDanmakuObjects:
    """测试 preload_danmaku_objects：弹幕对象预创建。"""

    def test_preload_creates_correct_count(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        events = [
            DanmakuEvent(time=1.0, user="u1", text="弹幕1"),
            DanmakuEvent(time=2.0, user="u2", text="弹幕2"),
            DanmakuEvent(time=3.0, user="u3", text="弹幕3"),
        ]
        lp = _make_layout_params()
        pool = LayoutEngine.preload_danmaku_objects(events, lp, asset_loader)
        assert len(pool) == 3
        for dm in pool:
            assert isinstance(dm, ActiveDanmaku)

    def test_preload_no_render(self, font_metrics, emoji_cache, gift_cache, asset_loader):
        """预创建不应触发预渲染（懒加载）。"""
        events = [DanmakuEvent(time=1.0, user="u", text="测试")]
        lp = _make_layout_params()
        pool = LayoutEngine.preload_danmaku_objects(events, lp, asset_loader)
        assert pool[0].cached_image is None

    def test_preload_empty_events(self, font_metrics, emoji_cache, gift_cache, asset_loader):
        lp = _make_layout_params()
        pool = LayoutEngine.preload_danmaku_objects([], lp, asset_loader)
        assert pool == []

    def test_preload_uses_layout_text_w(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        events = [DanmakuEvent(time=1.0, user="u", text="测试")]
        lp = _make_layout_params(w=1280, h=720)
        pool = LayoutEngine.preload_danmaku_objects(events, lp, asset_loader)
        # 弹幕宽度受 text_w 限制，不会超过它
        assert pool[0].total_width <= lp.text_w + DEFAULT_CONFIG.style.bubble_padding_x * 2


# =============================================================================
# update_positions
# =============================================================================


class TestUpdatePositions:
    """测试 update_positions：目标位置计算与阻尼动画。"""

    def test_new_spawned_sets_target_from_bottom(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 0.0
        dm.target_y = 0.0
        dm.is_first_activation = True

        LayoutEngine.update_positions([dm], True, lp.bottom, lp.gap)

        assert dm.target_y == lp.bottom - dm.height
        assert not dm.is_first_activation

    def test_first_activation_snaps_to_bottom(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 0.0
        dm.target_y = 0.0
        dm.is_first_activation = True

        LayoutEngine.update_positions([dm], True, lp.bottom, lp.gap)

        assert dm.current_y == lp.bottom - dm.height

    def test_damping_moves_toward_target(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.is_first_activation = False
        dm.current_y = 500.0
        dm.target_y = 400.0

        LayoutEngine.update_positions([dm], False, lp.bottom, lp.gap)

        expected = 500.0 + (400.0 - 500.0) * DEFAULT_CONFIG.animation.text_damping_factor
        assert abs(dm.current_y - expected) < 0.01

    def test_multiple_danmakus_stacked(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)
        for dm in (dm1, dm2):
            dm.is_first_activation = True
            dm.current_y = 0.0
            dm.target_y = 0.0

        LayoutEngine.update_positions([dm1, dm2], True, lp.bottom, lp.gap)

        assert dm2.target_y == lp.bottom - dm2.height
        assert dm1.target_y == dm2.target_y - lp.gap - dm1.height

    def test_no_new_spawned_no_target_recalc(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        """无新弹幕时不应重新计算目标位置。"""
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.is_first_activation = False
        dm.current_y = 300.0
        dm.target_y = 200.0
        original_target = dm.target_y

        LayoutEngine.update_positions([dm], False, lp.bottom, lp.gap)

        assert dm.target_y == original_target

    def test_empty_list_no_error(self):
        lp = _make_layout_params()
        LayoutEngine.update_positions([], True, lp.bottom, lp.gap)

    def test_position_threshold_snap(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        """当 diff 小于阈值时不应移动。"""
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.is_first_activation = False
        dm.current_y = 300.0
        dm.target_y = 300.05  # diff = 0.05 < 0.1 threshold

        LayoutEngine.update_positions(
            [dm], False, lp.bottom, lp.gap,
            position_threshold=0.1,
        )

        assert dm.current_y == 300.0


# =============================================================================
# handle_collisions
# =============================================================================


class TestHandleCollisions:
    """测试 handle_collisions：碰撞检测与推挤。"""

    def test_no_collision_single_danmaku(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = lp.bottom - dm.height
        original_y = dm.current_y

        LayoutEngine.handle_collisions([dm], lp.text_top, lp.gap)

        assert dm.current_y == original_y

    def test_overlapping_danmakus_get_pushed(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.current_y = lp.bottom - dm2.height
        dm1.current_y = dm2.current_y  # 完全重叠
        dm1.target_y = dm1.current_y
        dm1.is_locked_to_next = False

        LayoutEngine.handle_collisions([dm1, dm2], lp.text_top, lp.gap)

        expected_top = dm2.current_y - lp.gap - dm1.height
        assert dm1.current_y <= expected_top + 1

    def test_empty_list_no_error(self):
        lp = _make_layout_params()
        LayoutEngine.handle_collisions([], lp.text_top, lp.gap)

    def test_no_overlap_no_push(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        """不重叠的弹幕不应被推挤。"""
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.current_y = lp.bottom - dm2.height
        dm1.current_y = dm2.current_y - lp.gap - dm1.height - 10  # 有足够间距
        original_y1 = dm1.current_y

        LayoutEngine.handle_collisions([dm1, dm2], lp.text_top, lp.gap)

        assert dm1.current_y == original_y1


# =============================================================================
# handle_collisions - 锁定机制
# =============================================================================


class TestHandleCollisionsLocking:
    """测试 handle_collisions 的锁定机制。"""

    def test_locked_danmaku_follows_next(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.current_y = lp.bottom - dm2.height
        dm1.is_locked_to_next = True
        dm1.current_y = dm2.current_y - lp.gap - dm1.height - 50
        dm1.target_y = dm1.current_y

        LayoutEngine.handle_collisions([dm1, dm2], lp.text_top, lp.gap)

        expected_y = dm2.current_y - lp.gap - dm1.height
        assert dm1.current_y == expected_y

    def test_all_invisible_no_collision(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        """全部不可见时不应触发碰撞处理。"""
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm1.current_y = lp.text_top - dm1.height - 200
        dm2.current_y = lp.text_top - dm2.height - 100
        original_y1 = dm1.current_y
        original_y2 = dm2.current_y

        LayoutEngine.handle_collisions([dm1, dm2], lp.text_top, lp.gap)

        assert dm1.current_y == original_y1
        assert dm2.current_y == original_y2

    def test_collision_sets_lock(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        """碰撞推挤后应设置锁定标记。"""
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.current_y = lp.bottom - dm2.height
        dm1.current_y = dm2.current_y  # 重叠
        dm1.target_y = lp.bottom  # 目标在下方
        dm1.is_locked_to_next = False

        LayoutEngine.handle_collisions([dm1, dm2], lp.text_top, lp.gap)

        assert dm1.is_locked_to_next


# =============================================================================
# recycle_out_of_bounds
# =============================================================================


class TestRecycleOutOfBounds:
    """测试 recycle_out_of_bounds：越界回收与时间过期。"""

    def test_in_bounds_danmaku_kept(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = lp.bottom - dm.height
        active = [dm]

        LayoutEngine.recycle_out_of_bounds(active, lp.text_top)

        assert len(active) == 1

    def test_out_of_bounds_danmaku_removed(
        self, font_metrics, emoji_cache, gift_cache, font,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = lp.text_top - dm.height - 100
        dm.pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        assert dm.cached_image is not None
        active = [dm]

        LayoutEngine.recycle_out_of_bounds(active, lp.text_top)

        assert len(active) == 0
        assert dm.cached_image.isNull()

    def test_mixed_danmakus(self, font_metrics, emoji_cache, gift_cache):
        lp = _make_layout_params()
        dm_in = _make_active_danmaku("保留", font_metrics, emoji_cache, gift_cache)
        dm_in.current_y = lp.bottom - dm_in.height

        dm_out = _make_active_danmaku("移除", font_metrics, emoji_cache, gift_cache)
        dm_out.current_y = lp.text_top - dm_out.height - 100

        active = [dm_in, dm_out]

        LayoutEngine.recycle_out_of_bounds(active, lp.text_top)

        assert len(active) == 1
        assert active[0] is dm_in

    def test_expired_by_dwell_time(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        """停留时间过期的弹幕应被回收。"""
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = lp.bottom - dm.height  # 在边界内
        dm.spawn_time = 1.0
        active = [dm]

        LayoutEngine.recycle_out_of_bounds(
            active, lp.text_top, current_time=10.0, dwell_time=5.0,
        )

        assert len(active) == 0

    def test_not_expired_within_dwell_time(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        """未超过停留时间的弹幕应保留。"""
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = lp.bottom - dm.height
        dm.spawn_time = 8.0
        active = [dm]

        LayoutEngine.recycle_out_of_bounds(
            active, lp.text_top, current_time=10.0, dwell_time=5.0,
        )

        assert len(active) == 1


# =============================================================================
# spawn_new_danmakus
# =============================================================================


class TestSpawnNewDanmakus:
    """测试 spawn_new_danmakus：文本弹幕的生成逻辑。"""

    def test_spawn_at_current_time(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache, time=1.0)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache, time=2.0)
        pool = [dm1, dm2]
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        ctx = LayoutContext(event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, text_emitted, gift_emitted = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, pool, active_text, active_gift, asset_loader,
        )

        assert ctx.event_idx == 1
        assert text_new is True
        assert gift_new is False
        assert len(active_text) == 1
        assert active_text[0] is dm1
        assert dm1.cached_image is not None

    def test_no_spawn_before_time(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache, time=5.0)
        pool = [dm1]
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        ctx = LayoutContext(event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, text_emitted, gift_emitted = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, pool, active_text, active_gift, asset_loader,
        )

        assert ctx.event_idx == 0
        assert text_new is False
        assert gift_new is False
        assert len(active_text) == 0

    def test_spawn_respects_batch_size(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        """批量发射不应超过 text_spawn_batch_size。"""
        dm_list = [
            _make_active_danmaku(f"弹幕{i}", font_metrics, emoji_cache, gift_cache, time=1.0)
            for i in range(5)
        ]
        pool = dm_list
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        batch_size = DEFAULT_CONFIG.animation.text_spawn_batch_size
        ctx = LayoutContext(event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, text_emitted, gift_emitted = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, pool, active_text, active_gift, asset_loader,
        )

        assert text_new is True
        assert ctx.event_idx == min(batch_size, len(pool))
        assert len(active_text) <= batch_size

    def test_already_rendered_not_re_rendered(
        self, font_metrics, emoji_cache, gift_cache, font, asset_loader,
    ):
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache, time=1.0)
        dm1.pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        original_image = dm1.cached_image
        pool = [dm1]
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        ctx = LayoutContext(event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, pool, active_text, active_gift, asset_loader,
        )

        assert dm1.cached_image is original_image

    def test_spawn_interval_respected(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        """有积压时，在间隔时间内不应重复发射。

        动态间隔逻辑：无积压（待处理量 <= batch_size）时立即发射；
        有积压时启用时间窗口和批次限制。
        """
        batch_size = DEFAULT_CONFIG.animation.text_spawn_batch_size
        # 创建超过 batch_size 的弹幕以产生积压
        dm_list = [
            _make_active_danmaku(f"弹幕{i}", font_metrics, emoji_cache, gift_cache, time=1.0)
            for i in range(batch_size + 5)
        ]
        pool = dm_list
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        # 第一次发射：batch_size 个弹幕，剩余产生积压
        ctx = LayoutContext(event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, pool, active_text, active_gift, asset_loader,
        )
        assert len(active_text) == batch_size

        # 间隔不足时，有积压的弹幕不应发射
        text_new2, _, _, _ = LayoutEngine.spawn_new_danmakus(
            ctx, 1.1, pool, active_text, active_gift, asset_loader,
        )
        assert text_new2 is False


class TestSpawnNewDanmakusGift:
    """测试 spawn_new_danmakus：礼物弹幕的生成逻辑。"""

    def test_spawn_gift_danmaku(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        dm = _make_active_danmaku(
            "", font_metrics, emoji_cache, gift_cache,
            time=1.0, is_gift=True, gift_name="火箭", gift_count=1,
        )
        pool = [dm]
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        ctx = LayoutContext(event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, _, _ = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, pool, active_text, active_gift, asset_loader,
        )

        assert gift_new is True
        assert text_new is False
        assert len(active_gift) == 1
        assert active_gift[0] is dm

    def test_mixed_text_and_gift(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        dm_text = _make_active_danmaku("文本", font_metrics, emoji_cache, gift_cache, time=1.0)
        dm_gift = _make_active_danmaku(
            "", font_metrics, emoji_cache, gift_cache,
            time=1.0, is_gift=True, gift_name="火箭", gift_count=1,
        )
        pool = [dm_text, dm_gift]
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        ctx = LayoutContext(event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, _, _ = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, pool, active_text, active_gift, asset_loader,
        )

        assert text_new is True
        assert gift_new is True
        assert len(active_text) == 1
        assert len(active_gift) == 1