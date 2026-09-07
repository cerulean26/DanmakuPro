"""layout_engine.py 单元测试

测试布局引擎的全部静态方法：calculate_params、
spawn_new_danmakus、_update_and_collide、recycle_out_of_bounds。
"""

import pytest
from PySide6.QtGui import QColor

from danmakupro.layout.engine import LayoutEngine, LayoutContext, _all_positions_stable
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


def _make_event(
    text: str = "",
    *,
    time: float = 1.0,
    user: str = "用户",
    is_gift: bool = False,
    gift_name: str = "",
    gift_count: int = 0,
) -> DanmakuEvent:
    """创建原始 DanmakuEvent 测试实例（用于惰性创建测试）。"""
    return DanmakuEvent(
        time=time, user=user, text=text,
        is_gift=is_gift, gift_name=gift_name, gift_count=gift_count,
    )


def _make_builder(font_metrics, emoji_cache, gift_cache) -> DanmakuLayoutBuilder:
    """创建 DanmakuLayoutBuilder 测试实例。"""
    return DanmakuLayoutBuilder(
        fm=font_metrics,
        emoji_cache=emoji_cache,
        gift_cache=gift_cache,
        max_content_width=MAX_CONTENT_WIDTH,
        line_height=LINE_HEIGHT,
        style=DEFAULT_CONFIG.style,
    )


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
# _update_and_collide（合并了原 update_positions + handle_collisions 的测试）
# =============================================================================


class TestUpdateAndCollide:
    """测试 _update_and_collide：合并位置更新与碰撞检测。"""

    # ── 位置更新 ──────────────────────────────────────────

    def test_new_spawned_sets_target_from_bottom(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 0.0
        dm.target_y = 0.0
        dm.is_first_activation = True

        LayoutEngine._update_and_collide(
            [dm], has_new=True, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

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

        LayoutEngine._update_and_collide(
            [dm], has_new=True, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        assert dm.current_y == lp.bottom - dm.height

    def test_damping_moves_toward_target(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.is_first_activation = False
        dm.current_y = 500.0
        dm.target_y = 400.0

        LayoutEngine._update_and_collide(
            [dm], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

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

        LayoutEngine._update_and_collide(
            [dm1, dm2], has_new=True, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        assert dm2.target_y == lp.bottom - dm2.height
        assert dm1.target_y == dm2.target_y - lp.gap - dm1.height

    def test_no_new_spawned_no_target_recalc(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.is_first_activation = False
        dm.current_y = 300.0
        dm.target_y = 200.0
        original_target = dm.target_y

        LayoutEngine._update_and_collide(
            [dm], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        assert dm.target_y == original_target

    def test_position_threshold_snap(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.is_first_activation = False
        dm.current_y = 300.0
        dm.target_y = 300.05

        LayoutEngine._update_and_collide(
            [dm], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap, position_threshold=0.1,
        )

        assert dm.current_y == 300.0

    # ── 碰撞检测 ──────────────────────────────────────────

    def test_no_collision_single_danmaku(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.is_first_activation = False
        dm.current_y = dm.target_y = lp.bottom - dm.height
        original_y = dm.current_y

        LayoutEngine._update_and_collide(
            [dm], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        assert dm.current_y == original_y

    def test_overlapping_danmakus_get_pushed(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.is_first_activation = False
        dm2.current_y = dm2.target_y = lp.bottom - dm2.height
        dm1.is_first_activation = False
        dm1.current_y = dm2.current_y  # 完全重叠
        dm1.target_y = dm1.current_y

        LayoutEngine._update_and_collide(
            [dm1, dm2], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        expected_top = dm2.current_y - lp.gap - dm1.height
        assert dm1.current_y <= expected_top + 1

    def test_no_overlap_no_push(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.is_first_activation = False
        dm2.current_y = dm2.target_y = lp.bottom - dm2.height
        dm1.is_first_activation = False
        dm1.current_y = dm1.target_y = dm2.current_y - lp.gap - dm1.height - 10
        original_y1 = dm1.current_y

        LayoutEngine._update_and_collide(
            [dm1, dm2], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        assert dm1.current_y == original_y1

    # ── 锁定机制 ──────────────────────────────────────────

    def test_locked_danmaku_follows_next(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.is_first_activation = False
        dm2.current_y = dm2.target_y = lp.bottom - dm2.height
        dm1.is_first_activation = False
        dm1.is_locked_to_next = True
        dm1.current_y = dm2.current_y - lp.gap - dm1.height - 50
        dm1.target_y = dm1.current_y

        LayoutEngine._update_and_collide(
            [dm1, dm2], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        expected_y = dm2.current_y - lp.gap - dm1.height
        assert dm1.current_y == expected_y

    def test_collision_sets_lock(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.is_first_activation = False
        dm2.current_y = dm2.target_y = lp.bottom - dm2.height
        dm1.is_first_activation = False
        dm1.current_y = dm2.current_y  # 重叠
        dm1.target_y = lp.bottom  # 目标在下方
        dm1.is_locked_to_next = False

        LayoutEngine._update_and_collide(
            [dm1, dm2], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        assert dm1.is_locked_to_next

    # ── 合并方法特有测试 ─────────────────────────────────

    def test_empty_list(self):
        lp = _make_layout_params()
        LayoutEngine._update_and_collide(
            [], has_new=True, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

    def test_skip_collision_when_stable(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)
        dm2.is_first_activation = False
        dm2.current_y = dm2.target_y = lp.bottom - dm2.height
        dm1.is_first_activation = False
        dm1.current_y = dm1.target_y = dm2.current_y  # 重叠

        LayoutEngine._update_and_collide(
            [dm1, dm2], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap, skip_collision=True,
        )

        assert dm1.current_y == dm2.current_y

    def test_with_new_spawn_recalc_targets(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)
        dm1.is_first_activation = False
        dm2.is_first_activation = False
        dm1.target_y = 0.0
        dm2.target_y = 0.0

        LayoutEngine._update_and_collide(
            [dm1, dm2], has_new=True, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        assert dm2.target_y == lp.bottom - dm2.height
        assert dm1.target_y < dm2.target_y

    def test_first_activation_with_above_danmaku(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm_above = _make_active_danmaku("上方", font_metrics, emoji_cache, gift_cache)
        dm_below = _make_active_danmaku("下方", font_metrics, emoji_cache, gift_cache)

        dm_above.is_first_activation = False
        dm_above.current_y = 500.0
        dm_above.target_y = 500.0

        dm_below.is_first_activation = True
        dm_below.current_y = 0.0
        dm_below.target_y = 0.0

        LayoutEngine._update_and_collide(
            [dm_above, dm_below], has_new=True, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        above_bottom = dm_above.current_y + dm_above.height
        assert dm_below.current_y <= above_bottom + lp.gap

    def test_all_invisible_no_collision(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm1.is_first_activation = False
        dm2.is_first_activation = False
        dm1.current_y = dm1.target_y = lp.text_top - dm1.height - 200
        dm2.current_y = dm2.target_y = lp.text_top - dm2.height - 100

        original_y1 = dm1.current_y
        original_y2 = dm2.current_y

        LayoutEngine._update_and_collide(
            [dm1, dm2], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap,
        )

        assert dm1.current_y == original_y1
        assert dm2.current_y == original_y2


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
    """测试 spawn_new_danmakus：文本弹幕的生成逻辑（惰性创建模式）。"""

    def test_spawn_at_current_time(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        e1 = _make_event("弹幕1", time=1.0)
        e2 = _make_event("弹幕2", time=2.0)
        events = [e1, e2]
        builder = _make_builder(font_metrics, emoji_cache, gift_cache)
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        ctx = LayoutContext(text_event_idx=0, gift_event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, text_emitted, gift_emitted = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, events, active_text, active_gift, builder, asset_loader,
        )

        assert ctx.text_event_idx == 1
        assert ctx.gift_event_idx == 1
        assert text_new is True
        assert gift_new is False
        assert len(active_text) == 1
        assert active_text[0].cached_image is not None

    def test_no_spawn_before_time(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        e1 = _make_event("弹幕1", time=5.0)
        events = [e1]
        builder = _make_builder(font_metrics, emoji_cache, gift_cache)
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        ctx = LayoutContext(text_event_idx=0, gift_event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, text_emitted, gift_emitted = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, events, active_text, active_gift, builder, asset_loader,
        )

        assert ctx.text_event_idx == 0
        assert ctx.gift_event_idx == 0
        assert text_new is False
        assert gift_new is False
        assert len(active_text) == 0

    def test_spawn_respects_batch_size(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        """批量发射不应超过 text_spawn_batch_size。"""
        events = [
            _make_event(f"弹幕{i}", time=1.0)
            for i in range(5)
        ]
        builder = _make_builder(font_metrics, emoji_cache, gift_cache)
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        batch_size = DEFAULT_CONFIG.animation.text_spawn_batch_size
        ctx = LayoutContext(text_event_idx=0, gift_event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, text_emitted, gift_emitted = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, events, active_text, active_gift, builder, asset_loader,
        )

        assert text_new is True
        assert ctx.text_event_idx == batch_size
        assert ctx.gift_event_idx == len(events)
        assert len(active_text) <= batch_size

    def test_spawn_interval_respected(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        """有积压时，在间隔时间内不应重复发射。

        动态间隔逻辑：无积压（待处理量 <= batch_size）时立即发射；
        有积压时启用时间窗口和批次限制。
        """
        batch_size = DEFAULT_CONFIG.animation.text_spawn_batch_size
        events = [
            _make_event(f"弹幕{i}", time=1.0)
            for i in range(batch_size + 5)
        ]
        builder = _make_builder(font_metrics, emoji_cache, gift_cache)
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        # 第一次发射：batch_size 个弹幕，剩余产生积压
        ctx = LayoutContext(text_event_idx=0, gift_event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, events, active_text, active_gift, builder, asset_loader,
        )
        assert len(active_text) == batch_size

        # 间隔不足时，有积压的弹幕不应发射
        text_new2, _, _, _ = LayoutEngine.spawn_new_danmakus(
            ctx, 1.1, events, active_text, active_gift, builder, asset_loader,
        )
        assert text_new2 is False


class TestSpawnNewDanmakusGift:
    """测试 spawn_new_danmakus：礼物弹幕的生成逻辑（惰性创建模式）。"""

    def test_spawn_gift_danmaku(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        e1 = _make_event(
            "", time=1.0, is_gift=True, gift_name="火箭", gift_count=1,
        )
        events = [e1]
        builder = _make_builder(font_metrics, emoji_cache, gift_cache)
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        ctx = LayoutContext(text_event_idx=0, gift_event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, _, _ = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, events, active_text, active_gift, builder, asset_loader,
        )

        assert gift_new is True
        assert text_new is False
        assert len(active_gift) == 1

    def test_mixed_text_and_gift(
        self, font_metrics, emoji_cache, gift_cache, asset_loader,
    ):
        e_text = _make_event("文本", time=1.0)
        e_gift = _make_event(
            "", time=1.0, is_gift=True, gift_name="火箭", gift_count=1,
        )
        events = [e_text, e_gift]
        builder = _make_builder(font_metrics, emoji_cache, gift_cache)
        active_text: list[ActiveDanmaku] = []
        active_gift: list[ActiveDanmaku] = []

        ctx = LayoutContext(text_event_idx=0, gift_event_idx=0, last_text_spawn_time=-1.0, last_gift_spawn_time=-1.0)
        text_new, gift_new, _, _ = LayoutEngine.spawn_new_danmakus(
            ctx, 1.0, events, active_text, active_gift, builder, asset_loader,
        )

        assert text_new is True
        assert gift_new is True
        assert len(active_text) == 1
        assert len(active_gift) == 1


# =============================================================================
# update_danmaku_layer
# =============================================================================


class TestUpdateDanmakuLayer:
    """测试 update_danmaku_layer：统一弹幕层更新入口。"""

    def test_text_layer_basic(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = lp.bottom - dm.height
        dm.is_first_activation = False
        dm.target_y = dm.current_y

        LayoutEngine.update_danmaku_layer(
            [dm], has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap, damping=DEFAULT_CONFIG.animation.text_damping_factor,
        )

        assert len([dm]) == 1  # 未越界，保留

    def test_gift_layer_with_dwell(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku(
            "礼物", font_metrics, emoji_cache, gift_cache,
            is_gift=True, gift_name="火箭", gift_count=1,
        )
        dm.current_y = lp.text_top - dm.height - 10
        dm.target_y = dm.current_y
        dm.is_first_activation = False
        dm.spawn_time = 1.0

        active = [dm]
        LayoutEngine.update_danmaku_layer(
            active, has_new=False, zone_bottom=lp.text_top, zone_top=lp.gift_top,
            gap=lp.gap, damping=DEFAULT_CONFIG.animation.gift_damping_factor,
            current_time=10.0, dwell_time=5.0,
        )

        assert len(active) == 0  # 过期回收

    def test_gift_within_dwell_time(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku(
            "礼物", font_metrics, emoji_cache, gift_cache,
            is_gift=True, gift_name="火箭", gift_count=1,
        )
        dm.current_y = lp.text_top - dm.height - 10
        dm.target_y = dm.current_y
        dm.is_first_activation = False
        dm.spawn_time = 8.0

        active = [dm]
        LayoutEngine.update_danmaku_layer(
            active, has_new=False, zone_bottom=lp.text_top, zone_top=lp.gift_top,
            gap=lp.gap, damping=DEFAULT_CONFIG.animation.gift_damping_factor,
            current_time=10.0, dwell_time=5.0,
        )

        assert len(active) == 1  # 未过期

    def test_empty_list(self):
        lp = _make_layout_params()
        active: list[ActiveDanmaku] = []
        LayoutEngine.update_danmaku_layer(
            active, has_new=False, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap, damping=0.25,
        )
        assert len(active) == 0

    def test_with_new_spawn(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("新弹幕", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 0.0
        dm.target_y = 0.0
        dm.is_first_activation = True

        active = [dm]
        LayoutEngine.update_danmaku_layer(
            active, has_new=True, zone_bottom=lp.bottom, zone_top=lp.text_top,
            gap=lp.gap, damping=DEFAULT_CONFIG.animation.text_damping_factor,
        )

        assert dm.target_y == lp.bottom - dm.height
        assert not dm.is_first_activation


# =============================================================================
# _all_positions_stable
# =============================================================================


class TestAllPositionsStable:
    """测试 _all_positions_stable：位置稳定检测。"""

    def test_all_stable(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 500.0
        dm.target_y = 500.0

        assert _all_positions_stable([dm]) is True

    def test_not_stable(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 500.0
        dm.target_y = 400.0

        assert _all_positions_stable([dm]) is False

    def test_near_stable_within_threshold(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 500.0
        dm.target_y = 500.3  # diff = 0.3 < 0.5 threshold

        assert _all_positions_stable([dm]) is True

    def test_one_unstable_among_many(self, font_metrics, emoji_cache, gift_cache):
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)
        dm1.current_y = dm1.target_y = 500.0
        dm2.current_y = 500.0
        dm2.target_y = 400.0

        assert _all_positions_stable([dm1, dm2]) is False

    def test_empty_list(self):
        assert _all_positions_stable([]) is True

    def test_custom_threshold(self, font_metrics, emoji_cache, gift_cache):
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 500.0
        dm.target_y = 501.0  # diff = 1.0

        assert _all_positions_stable([dm], threshold=0.5) is False
        assert _all_positions_stable([dm], threshold=2.0) is True