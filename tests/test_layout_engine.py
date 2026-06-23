"""layout_engine.py 单元测试

测试布局引擎的纯计算方法：calculate_params、update_positions、
handle_collisions、recycle_out_of_bounds、get_fade_out_params。
"""

from pathlib import Path

import pytest
from PySide6.QtGui import QColor

from danmakupro.layout_engine import LayoutEngine
from danmakupro.layout_params import LayoutParams, LayerParams
from danmakupro.models import DanmakuEvent, ActiveDanmaku
from danmakupro.config import (
    DANMAKU_X, BUBBLE_VERTICAL_GAP, LAYER_WIDTH_EXTRA,
    CONTAINER_BOTTOM_RATIO, MAX_CONTAINER_HEIGHT_RATIO, MAX_CONTENT_WIDTH_RATIO,
    GIFT_ZONE_HEIGHT_RATIO,
    DAMPING_FACTOR, FADE_OUT_ZONE,
)

MAX_CONTENT_WIDTH = 800


def _make_active_danmaku(
    text: str,
    font_metrics,
    emoji_cache: dict,
    gift_cache: dict,
    time: float = 1.0,
    max_content_width: int = MAX_CONTENT_WIDTH,
    line_height: int = 36,
) -> ActiveDanmaku:
    event = DanmakuEvent(time=time, user="用户", text=text)
    return ActiveDanmaku(
        event, font_metrics, emoji_cache, gift_cache,
        max_content_width=max_content_width, line_height=line_height,
    )


def _make_layout_params(w: int = 1920, h: int = 1080) -> LayoutParams:
    container_bottom = int(h * CONTAINER_BOTTOM_RATIO)
    max_container_height = int(h * MAX_CONTAINER_HEIGHT_RATIO)
    max_y_limit = container_bottom - max_container_height
    gift_zone_height = int(h * GIFT_ZONE_HEIGHT_RATIO)
    gift_y_limit = max_y_limit - gift_zone_height
    max_content_width = int(w * MAX_CONTENT_WIDTH_RATIO)
    return LayoutParams(
        container_bottom=container_bottom,
        max_container_height=max_container_height,
        max_y_limit=max_y_limit,
        max_content_width=max_content_width,
        bubble_vertical_gap=BUBBLE_VERTICAL_GAP,
        gift_y_limit=gift_y_limit,
        gift_zone_height=gift_zone_height,
    )


# =============================================================================
# calculate_params
# =============================================================================


class TestCalculateParams:
    def test_1080p(self):
        lp, layer = LayoutEngine.calculate_params(1920, 1080)
        assert lp.container_bottom == int(1080 * CONTAINER_BOTTOM_RATIO)
        assert lp.max_container_height == int(1080 * MAX_CONTAINER_HEIGHT_RATIO)
        assert lp.max_content_width == int(1920 * MAX_CONTENT_WIDTH_RATIO)
        assert lp.max_y_limit == lp.container_bottom - lp.max_container_height

    def test_720p(self):
        lp, layer = LayoutEngine.calculate_params(1280, 720)
        assert lp.container_bottom == int(720 * CONTAINER_BOTTOM_RATIO)
        assert lp.max_content_width == int(1280 * MAX_CONTENT_WIDTH_RATIO)

    def test_layer_params(self):
        lp, layer = LayoutEngine.calculate_params(1920, 1080)
        assert layer.layer_x == DANMAKU_X
        assert layer.layer_y == lp.gift_y_limit
        assert layer.layer_h == lp.container_bottom - lp.gift_y_limit
        expected_w = lp.max_content_width + LAYER_WIDTH_EXTRA
        assert layer.layer_w == expected_w

    def test_layer_width_clamped(self):
        tiny_w = DANMAKU_X + 10
        lp, layer = LayoutEngine.calculate_params(tiny_w, 1080)
        assert layer.layer_w <= tiny_w - DANMAKU_X

    def test_params_frozen(self):
        lp, layer = LayoutEngine.calculate_params(1920, 1080)
        with pytest.raises(AttributeError):
            setattr(lp, "container_bottom", 0)


# =============================================================================
# update_positions
# =============================================================================


class TestUpdatePositions:
    def test_new_spawned_sets_target_from_bottom(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 0.0
        dm.target_y = 0.0
        dm.is_first_activation = True

        LayoutEngine.update_positions([dm], True, lp.container_bottom, lp.bubble_vertical_gap)

        assert dm.target_y == lp.container_bottom - dm.height
        assert not dm.is_first_activation

    def test_first_activation_snaps_to_bottom(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = 0.0
        dm.target_y = 0.0
        dm.is_first_activation = True

        LayoutEngine.update_positions([dm], True, lp.container_bottom, lp.bubble_vertical_gap)

        assert dm.current_y == lp.container_bottom - dm.height

    def test_damping_moves_toward_target(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.is_first_activation = False
        dm.current_y = 500.0
        dm.target_y = 400.0

        LayoutEngine.update_positions([dm], False, lp.container_bottom, lp.bubble_vertical_gap)

        expected = 500.0 + (400.0 - 500.0) * DAMPING_FACTOR
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

        LayoutEngine.update_positions([dm1, dm2], True, lp.container_bottom, lp.bubble_vertical_gap)

        assert dm2.target_y == lp.container_bottom - dm2.height
        assert dm1.target_y == dm2.target_y - lp.bubble_vertical_gap - dm1.height


# =============================================================================
# handle_collisions
# =============================================================================


class TestHandleCollisions:
    def test_no_collision_single_danmaku(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = lp.container_bottom - dm.height
        original_y = dm.current_y

        LayoutEngine.handle_collisions([dm], lp.max_y_limit, lp.bubble_vertical_gap)

        assert dm.current_y == original_y

    def test_overlapping_danmakus_get_pushed(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.current_y = lp.container_bottom - dm2.height
        dm1.current_y = dm2.current_y
        dm1.target_y = dm1.current_y
        dm1.is_locked_to_next = False

        LayoutEngine.handle_collisions([dm1, dm2], lp.max_y_limit, lp.bubble_vertical_gap)

        expected_top = dm2.current_y - lp.bubble_vertical_gap - dm1.height
        assert dm1.current_y <= expected_top + 1

    def test_empty_list_no_error(self):
        lp = _make_layout_params()
        LayoutEngine.handle_collisions([], lp.max_y_limit, lp.bubble_vertical_gap)


# =============================================================================
# recycle_out_of_bounds
# =============================================================================


class TestRecycleOutOfBounds:
    def test_in_bounds_danmaku_kept(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = lp.container_bottom - dm.height
        active = [dm]

        LayoutEngine.recycle_out_of_bounds(active, lp.max_y_limit)

        assert len(active) == 1

    def test_out_of_bounds_danmaku_removed(
        self, font_metrics, emoji_cache, gift_cache, font,
    ):
        lp = _make_layout_params()
        dm = _make_active_danmaku("测试", font_metrics, emoji_cache, gift_cache)
        dm.current_y = lp.max_y_limit - dm.height - 100
        dm._pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        assert dm.cached_image is not None
        active = [dm]

        LayoutEngine.recycle_out_of_bounds(active, lp.max_y_limit)

        assert len(active) == 0
        assert dm.cached_image.isNull()

    def test_mixed_danmakus(self, font_metrics, emoji_cache, gift_cache):
        lp = _make_layout_params()
        dm_in = _make_active_danmaku("保留", font_metrics, emoji_cache, gift_cache)
        dm_in.current_y = lp.container_bottom - dm_in.height

        dm_out = _make_active_danmaku("移除", font_metrics, emoji_cache, gift_cache)
        dm_out.current_y = lp.max_y_limit - dm_out.height - 100

        active = [dm_in, dm_out]

        LayoutEngine.recycle_out_of_bounds(active, lp.max_y_limit)

        assert len(active) == 1
        assert active[0] is dm_in


# =============================================================================
# get_fade_out_params
# =============================================================================


class TestGetFadeOutParams:
    def test_returns_correct_values(self):
        lp = _make_layout_params()
        fade_out_zone, fade_out_threshold = LayoutEngine.get_fade_out_params(
            lp.max_y_limit, FADE_OUT_ZONE,
        )

        assert fade_out_zone == FADE_OUT_ZONE
        assert fade_out_threshold == lp.max_y_limit + FADE_OUT_ZONE

    def test_threshold_greater_than_limit(self):
        lp = _make_layout_params()
        _, fade_out_threshold = LayoutEngine.get_fade_out_params(
            lp.max_y_limit, FADE_OUT_ZONE,
        )

        assert fade_out_threshold > lp.max_y_limit


# =============================================================================
# spawn_new_danmakus
# =============================================================================


class TestSpawnNewDanmakus:
    def test_spawn_at_current_time(
        self, font_metrics, emoji_cache, gift_cache, font,
    ):
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache, time=1.0)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache, time=2.0)
        pool = [dm1, dm2]
        active: list[ActiveDanmaku] = []

        idx, spawned = LayoutEngine.spawn_new_danmakus(
            1.0, pool, active, 0, font, emoji_cache, gift_cache,
            QColor(0, 0, 0, 120),
        )

        assert idx == 1
        assert spawned is True
        assert len(active) == 1
        assert active[0] is dm1
        assert dm1.cached_image is not None

    def test_no_spawn_before_time(
        self, font_metrics, emoji_cache, gift_cache, font,
    ):
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache, time=5.0)
        pool = [dm1]
        active: list[ActiveDanmaku] = []

        idx, spawned = LayoutEngine.spawn_new_danmakus(
            1.0, pool, active, 0, font, emoji_cache, gift_cache,
            QColor(0, 0, 0, 120),
        )

        assert idx == 0
        assert spawned is False
        assert len(active) == 0

    def test_spawn_multiple_at_same_time(
        self, font_metrics, emoji_cache, gift_cache, font,
    ):
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache, time=1.0)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache, time=1.0)
        dm3 = _make_active_danmaku("弹幕3", font_metrics, emoji_cache, gift_cache, time=1.0)
        pool = [dm1, dm2, dm3]
        active: list[ActiveDanmaku] = []

        idx, spawned = LayoutEngine.spawn_new_danmakus(
            1.0, pool, active, 0, font, emoji_cache, gift_cache,
            QColor(0, 0, 0, 120),
        )

        assert spawned is True
        assert idx >= 1

    def test_already_rendered_not_re_rendered(
        self, font_metrics, emoji_cache, gift_cache, font,
    ):
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache, time=1.0)
        dm1._pre_render(font, emoji_cache, gift_cache, QColor(0, 0, 0, 120))
        original_image = dm1.cached_image
        pool = [dm1]
        active: list[ActiveDanmaku] = []

        LayoutEngine.spawn_new_danmakus(
            1.0, pool, active, 0, font, emoji_cache, gift_cache,
            QColor(0, 0, 0, 120),
        )

        assert dm1.cached_image is original_image


# =============================================================================
# handle_collisions - 锁定机制
# =============================================================================


class TestHandleCollisionsLocking:
    def test_locked_danmaku_follows_next(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm2.current_y = lp.container_bottom - dm2.height
        dm1.is_locked_to_next = True
        dm1.current_y = dm2.current_y - lp.bubble_vertical_gap - dm1.height - 50
        dm1.target_y = dm1.current_y

        LayoutEngine.handle_collisions([dm1, dm2], lp.max_y_limit, lp.bubble_vertical_gap)

        expected_y = dm2.current_y - lp.bubble_vertical_gap - dm1.height
        assert dm1.current_y == expected_y

    def test_all_invisible_no_collision(
        self, font_metrics, emoji_cache, gift_cache,
    ):
        lp = _make_layout_params()
        dm1 = _make_active_danmaku("弹幕1", font_metrics, emoji_cache, gift_cache)
        dm2 = _make_active_danmaku("弹幕2", font_metrics, emoji_cache, gift_cache)

        dm1.current_y = lp.max_y_limit - dm1.height - 200
        dm2.current_y = lp.max_y_limit - dm2.height - 100

        LayoutEngine.handle_collisions([dm1, dm2], lp.max_y_limit, lp.bubble_vertical_gap)