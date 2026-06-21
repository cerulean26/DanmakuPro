"""布局引擎模块

负责弹幕布局计算、位置更新、碰撞检测和弹幕生成。
"""

import bisect
from typing import TYPE_CHECKING

from loguru import logger
from tqdm import tqdm

from .config import (
    DANMAKU_X, BUBBLE_VERTICAL_GAP, LAYER_WIDTH_EXTRA,
    CONTAINER_BOTTOM_RATIO, MAX_CONTAINER_HEIGHT_RATIO, MAX_CONTENT_WIDTH_RATIO,
    SPAWN_BACKLOG_DIVISOR, DAMPING_FACTOR, POSITION_THRESHOLD, FADE_OUT_ZONE,
)
from .models import DanmakuEvent, ActiveDanmaku
from .layout_params import LayoutParams, LayerParams

from PySide6.QtGui import QImage

if TYPE_CHECKING:
    from PySide6.QtGui import QColor, QFont
    from .asset_loader import AssetLoader


class LayoutEngine:
    """布局引擎：计算弹幕布局、管理弹幕位置和碰撞检测。

    职责：
        - 根据视频尺寸计算布局参数和渲染层参数
        - 预创建弹幕对象
        - 生成当前帧的新弹幕
        - 更新弹幕位置（含平滑阻尼动画）
        - 碰撞检测与推挤
        - 回收越界弹幕
    """

    def __init__(self, asset_loader: 'AssetLoader'):
        """初始化布局引擎。

        Args:
            asset_loader: 资源加载器（提供字体、图片缓存等）
        """
        self._asset_loader = asset_loader

    @staticmethod
    def calculate_params(w: int, h: int) -> tuple[LayoutParams, LayerParams]:
        """计算弹幕布局参数和渲染层参数。

        Args:
            w: 视频宽度（已对齐到 16 的倍数）
            h: 视频高度（已对齐到 16 的倍数）

        Returns:
            (LayoutParams, LayerParams) 元组
        """
        container_bottom = int(h * CONTAINER_BOTTOM_RATIO)
        max_container_height = int(h * MAX_CONTAINER_HEIGHT_RATIO)
        max_y_limit = container_bottom - max_container_height
        max_content_width = int(w * MAX_CONTENT_WIDTH_RATIO)
        bubble_vertical_gap = BUBBLE_VERTICAL_GAP

        logger.info(
            f"布局参数: 尺寸={w}x{h} | "
            f"弹幕区=底部{max_container_height}px | "
            f"最大内容宽度={max_content_width}"
        )

        layout_params = LayoutParams(
            container_bottom=container_bottom,
            max_container_height=max_container_height,
            max_y_limit=max_y_limit,
            max_content_width=max_content_width,
            bubble_vertical_gap=bubble_vertical_gap,
        )

        layer_x = DANMAKU_X
        layer_w = max_content_width + LAYER_WIDTH_EXTRA
        layer_y = max_y_limit
        layer_h = container_bottom - max_y_limit

        if layer_x + layer_w > w:
            layer_w = max(0, w - layer_x)

        layer_params = LayerParams(
            layer_x=layer_x,
            layer_y=layer_y,
            layer_w=layer_w,
            layer_h=layer_h,
        )

        return layout_params, layer_params

    def preload_danmaku_objects(
        self,
        events: list[DanmakuEvent],
        layout_params: LayoutParams,
    ) -> list[ActiveDanmaku]:
        """预创建所有弹幕对象（懒加载模式）。

        创建 ActiveDanmaku 对象但不立即渲染，等到首次激活时才调用 _pre_render。

        Args:
            events: 弹幕事件列表
            layout_params: 布局参数

        Returns:
            预创建的弹幕对象列表
        """
        logger.info("[4/5] 预创建弹幕对象...")
        loader = self._asset_loader
        danmaku_pool: list[ActiveDanmaku] = []

        for event in tqdm(events, desc="弹幕预创建", unit="条"):
            dm = ActiveDanmaku(
                event,
                loader.fm,
                loader.emoji_cache,
                loader.gift_cache,
                max_content_width=layout_params.max_content_width,
                line_height=loader.line_height,
            )
            danmaku_pool.append(dm)

        logger.info(f"弹幕预创建完成 | 总数={len(danmaku_pool)}")
        return danmaku_pool

    @staticmethod
    def spawn_new_danmakus(
        current_time: float,
        danmaku_pool: list[ActiveDanmaku],
        active_danmakus: list[ActiveDanmaku],
        event_idx: int,
        font: 'QFont',
        emoji_cache: dict,
        gift_cache: dict,
        bg_color: 'QColor',
    ) -> tuple[int, bool]:
        """生成当前时间点的新弹幕。

        使用二分查找定位当前时间点对应的弹幕位置，并根据积压量动态调整
        每帧的生成数量，避免短时间内大量弹幕同时出现导致卡顿。

        Args:
            current_time: 当前视频时间戳
            danmaku_pool: 预创建的弹幕池
            active_danmakus: 当前活跃的弹幕列表
            event_idx: 弹幕池索引指针
            font: 字体对象
            emoji_cache: Emoji 图片缓存
            gift_cache: 礼物图片缓存
            bg_color: 背景颜色

        Returns:
            (新的 event_idx, 是否有新弹幕生成)
        """
        lookahead_idx = bisect.bisect_right(
            danmaku_pool, current_time, key=lambda dm: dm.event.time,
        )
        backlog = lookahead_idx - event_idx
        spawn_limit = 1 + (backlog // SPAWN_BACKLOG_DIVISOR)

        spawned_count = 0
        is_any_new_spawned = False

        while (
            event_idx < len(danmaku_pool)
            and danmaku_pool[event_idx].event.time <= current_time
            and spawned_count < spawn_limit
        ):
            dm = danmaku_pool[event_idx]
            if dm.cached_image is None:
                dm._pre_render(font, emoji_cache, gift_cache, bg_color)
            active_danmakus.append(dm)
            event_idx += 1
            spawned_count += 1
            is_any_new_spawned = True

        return event_idx, is_any_new_spawned

    @staticmethod
    def update_positions(
        active_danmakus: list[ActiveDanmaku],
        is_any_new_spawned: bool,
        layout_params: LayoutParams,
    ) -> None:
        """更新所有活跃弹幕的位置。

        两大职责：
            1. 新弹幕加入时，重新计算所有弹幕的目标位置（从下往上排列）
            2. 每帧对所有弹幕应用平滑阻尼动画（damping），实现丝滑移动

        Args:
            active_danmakus: 当前活跃的弹幕列表
            is_any_new_spawned: 本帧是否有新弹幕生成
            layout_params: 布局参数
        """
        container_bottom = layout_params.container_bottom
        bubble_vertical_gap = layout_params.bubble_vertical_gap

        if is_any_new_spawned and active_danmakus:
            last_target_y = container_bottom
            gap = bubble_vertical_gap
            for dm in reversed(active_danmakus):
                h = dm.height
                dm.target_y = last_target_y - h
                last_target_y = dm.target_y - gap
                dm.is_locked_to_next = False

        damping = DAMPING_FACTOR
        threshold = POSITION_THRESHOLD
        for dm in active_danmakus:
            if dm.is_first_activation:
                dm.current_y = container_bottom - dm.height
                dm.is_first_activation = False
            ty = dm.target_y
            cy = dm.current_y
            diff = ty - cy
            if abs(diff) > threshold:
                dm.current_y = cy + diff * damping

    @staticmethod
    def handle_collisions(
        active_danmakus: list[ActiveDanmaku],
        layout_params: LayoutParams,
    ) -> None:
        """碰撞检测与处理：确保所有弹幕在物理上不重叠。

        从下往上遍历可见弹幕，检查每对相邻弹幕是否重叠。如果重叠，
        将上方的弹幕向上推挤。使用锁定机制防止弹幕在碰撞边界来回抖动。

        Args:
            active_danmakus: 当前活跃的弹幕列表
            layout_params: 布局参数
        """
        n = len(active_danmakus)
        if n <= 1:
            return

        max_y_limit = layout_params.max_y_limit
        bubble_vertical_gap = layout_params.bubble_vertical_gap

        visible_start = 0
        while visible_start < n:
            dm = active_danmakus[visible_start]
            if dm.current_y + dm.height <= max_y_limit:
                visible_start += 1
            else:
                break

        visible_count = n - visible_start
        if visible_count <= 1:
            return

        gap = bubble_vertical_gap

        for i in range(n - 2, visible_start - 1, -1):
            curr_dm = active_danmakus[i]
            next_dm = active_danmakus[i + 1]

            if curr_dm.is_locked_to_next:
                curr_dm.current_y = next_dm.current_y - gap - curr_dm.height
                continue

            max_physical_bottom = next_dm.current_y - gap
            curr_bottom = curr_dm.current_y + curr_dm.height

            if curr_bottom > max_physical_bottom:
                new_y = max_physical_bottom - curr_dm.height
                curr_dm.current_y = new_y

                if curr_dm.target_y > new_y:
                    curr_dm.target_y = new_y
                    curr_dm.is_locked_to_next = True

    @staticmethod
    def recycle_out_of_bounds(
        active_danmakus: list[ActiveDanmaku],
        layout_params: LayoutParams,
    ) -> None:
        """回收超出屏幕范围的弹幕，释放缓存图片以控制内存。

        Args:
            active_danmakus: 当前活跃的弹幕列表（原地修改）
            layout_params: 布局参数
        """
        remaining: list[ActiveDanmaku] = []
        for dm in active_danmakus:
            if dm.is_out_of_bounds(layout_params.max_y_limit):
                dm.cached_image = QImage()  # 显式触发 C++ 析构，立即释放像素缓冲区
            else:
                remaining.append(dm)
        active_danmakus[:] = remaining

    @staticmethod
    def get_fade_out_params(layout_params: LayoutParams) -> tuple[float, float]:
        """计算淡出区域参数。

        Args:
            layout_params: 布局参数

        Returns:
            (fade_out_zone, fade_out_threshold) 元组
        """
        fade_out_zone = FADE_OUT_ZONE
        fade_out_threshold = layout_params.max_y_limit + fade_out_zone
        return fade_out_zone, fade_out_threshold