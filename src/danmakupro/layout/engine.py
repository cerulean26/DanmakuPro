"""布局引擎

负责弹幕布局计算、位置更新、碰撞检测和弹幕生成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..config.models import LayoutStyle, LayoutRatio, AnimationParams, DEFAULT_CONFIG

if TYPE_CHECKING:
    from ..input.event import DanmakuEvent
    from .active import ActiveDanmaku
    from ..render.assets import AssetLoader
    from ..render.layout_builder import DanmakuLayoutBuilder

from PySide6.QtGui import QImage

from .params import LayoutParams, LayerParams


@dataclass
class LayoutContext:
    """布局上下文"""
    animation: AnimationParams = field(default_factory=lambda: DEFAULT_CONFIG.animation)
    text_event_idx: int = 0
    gift_event_idx: int = 0
    # 上次发射文本弹幕的时间。0.0 表示尚未发射过。
    last_text_spawn_time: float = 0.0
    # 上次发射礼物弹幕的时间。0.0 表示尚未发射过。
    last_gift_spawn_time: float = 0.0


class LayoutEngine:
    """布局引擎"""

    @staticmethod
    def calculate_params(
        w: int, h: int,
        style: LayoutStyle = DEFAULT_CONFIG.style,
        ratio: LayoutRatio = DEFAULT_CONFIG.ratio,
        line_height: int = 0,
    ) -> tuple[LayoutParams, LayerParams]:
        """计算布局参数

        基于弹幕行数而非高度比例，用户只需指定"最多显示几行弹幕"。
        Args:
            w: 视频宽度
            h: 视频高度
            style: 布局样式
            ratio: 布局比例
            line_height: 实际行高（像素），由 QFontMetrics.height() 测量得到
        """
        bubble_height = 2 * style.bubble_padding_y + line_height
        row_height = bubble_height + style.bubble_vertical_gap

        text_h = ratio.max_text_rows * row_height
        gift_h = ratio.max_gift_rows * row_height
        bottom = h - ratio.bottom_margin
        text_top = bottom - text_h
        gift_top = text_top - gift_h
        text_w = int(w * ratio.text_width_ratio)

        layout_params = LayoutParams(
            bottom=bottom,
            text_h=text_h,
            text_top=text_top,
            text_w=text_w,
            gap=style.bubble_vertical_gap,
            gift_top=gift_top,
            gift_h=gift_h,
        )

        layer_x = style.danmaku_x
        layer_w = text_w + style.layer_width_extra
        layer_y = gift_top
        layer_h = bottom - gift_top

        if layer_x + layer_w > w:
            layer_w = max(0, w - layer_x)

        layer_params = LayerParams(
            layer_x=layer_x, layer_y=layer_y,
            layer_w=layer_w, layer_h=layer_h,
        )

        return layout_params, layer_params

    @staticmethod
    def spawn_new_danmakus(
        ctx: LayoutContext,
        current_time: float,
        event_pool: list['DanmakuEvent'],
        active_text: list['ActiveDanmaku'],
        active_gift: list['ActiveDanmaku'],
        layout_builder: 'DanmakuLayoutBuilder',
        asset_provider: 'AssetLoader',
        style: LayoutStyle = DEFAULT_CONFIG.style,
    ) -> tuple[bool, bool, int, int]:
        """根据当前时间按需生成新弹幕（惰性创建模式）。

        只扫描原始 DanmakuEvent 列表，弹幕对象在发射时按需构建，
        避免预创建所有 ActiveDanmaku 带来的内存压力。

        文本和礼物使用独立的 event_idx，互不阻塞：
        文本积压不会挡住排在后面的礼物，反之亦然。

        无积压时（待处理量 <= batch_size）立即发射，无需等待间隔；
        有积压时启用时间窗口和批次限制，平滑弹幕密度。
        Returns:
            (text_has_new, gift_has_new, text_emitted, gift_emitted)
        """
        from .active import ActiveDanmaku

        animation = ctx.animation
        pool = event_pool
        n = len(pool)

        # ── 文本弹幕：独立扫描 ──────────────────────────────
        text_pending = 0
        text_scan_end = ctx.text_event_idx
        for i in range(ctx.text_event_idx, n):
            if pool[i].time > current_time:
                break
            if not pool[i].is_gift:
                text_pending += 1
            text_scan_end = i + 1

        text_can = (
            text_pending <= animation.text_spawn_batch_size
            or ctx.last_text_spawn_time == 0.0
            or (current_time - ctx.last_text_spawn_time) >= animation.text_spawn_interval
        )

        text_emitted = 0
        while ctx.text_event_idx < text_scan_end and text_can and text_emitted < animation.text_spawn_batch_size:
            event = pool[ctx.text_event_idx]
            if not event.is_gift:
                dm = ActiveDanmaku(
                    event=event,
                    layout=layout_builder.build(event),
                    x=style.danmaku_x,
                )
                dm.pre_render(
                    asset_provider.font,
                    asset_provider.emoji_cache,
                    asset_provider.gift_cache,
                    asset_provider.bg_color,
                )
                dm.spawn_time = current_time
                active_text.append(dm)
                text_emitted += 1
            ctx.text_event_idx += 1

        if text_emitted > 0:
            ctx.last_text_spawn_time = current_time

        # ── 礼物弹幕：独立扫描 ──────────────────────────────
        gift_pending = 0
        gift_scan_end = ctx.gift_event_idx
        for i in range(ctx.gift_event_idx, n):
            if pool[i].time > current_time:
                break
            if pool[i].is_gift:
                gift_pending += 1
            gift_scan_end = i + 1

        gift_can = (
            gift_pending <= animation.gift_spawn_batch_size
            or ctx.last_gift_spawn_time == 0.0
            or (current_time - ctx.last_gift_spawn_time) >= animation.gift_spawn_interval
        )

        gift_emitted = 0
        while ctx.gift_event_idx < gift_scan_end and gift_can and gift_emitted < animation.gift_spawn_batch_size:
            event = pool[ctx.gift_event_idx]
            if event.is_gift:
                dm = ActiveDanmaku(
                    event=event,
                    layout=layout_builder.build(event),
                    x=style.danmaku_x,
                )
                dm.pre_render(
                    asset_provider.font,
                    asset_provider.emoji_cache,
                    asset_provider.gift_cache,
                    asset_provider.bg_color,
                )
                dm.spawn_time = current_time
                active_gift.append(dm)
                gift_emitted += 1
            ctx.gift_event_idx += 1

        if gift_emitted > 0:
            ctx.last_gift_spawn_time = current_time

        return text_emitted > 0, gift_emitted > 0, text_emitted, gift_emitted

    @staticmethod
    def update_positions(
        active_danmakus: list['ActiveDanmaku'],
        is_any_new_spawned: bool,
        zone_bottom: int,
        gap: int,
        damping: float = 0.25,
        position_threshold: float = 0.1,
    ) -> None:
        """更新所有活跃弹幕的位置。

        两大职责：
            1. 新弹幕加入时，重新计算所有弹幕的目标位置（从下往上排列）
            2. 每帧对所有弹幕应用平滑阻尼动画（damping），实现丝滑移动
        """
        if is_any_new_spawned and active_danmakus:
            last_target_y = zone_bottom
            for dm in reversed(active_danmakus):
                h = dm.height
                dm.target_y = last_target_y - h
                last_target_y = dm.target_y - gap
                dm.is_locked_to_next = False

        for dm in active_danmakus:
            if dm.is_first_activation:
                dm.current_y = zone_bottom - dm.height
                dm.is_first_activation = False
            ty = dm.target_y
            cy = dm.current_y
            diff = ty - cy
            if abs(diff) > position_threshold:
                dm.current_y = cy + diff * damping

    @staticmethod
    def handle_collisions(
        active_danmakus: list['ActiveDanmaku'],
        zone_top: int,
        gap: int,
    ) -> None:
        """碰撞检测与处理：确保所有弹幕在物理上不重叠。

        从下往上遍历可见弹幕，检查每对相邻弹幕是否重叠。如果重叠，
        将上方的弹幕向上推挤。使用锁定机制防止弹幕在碰撞边界来回抖动。
        """
        n = len(active_danmakus)
        if n <= 1:
            return

        # 跳过已经完全越界的弹幕
        visible_start = 0
        while visible_start < n:
            dm = active_danmakus[visible_start]
            if dm.current_y + dm.height <= zone_top:
                visible_start += 1
            else:
                break

        visible_count = n - visible_start
        if visible_count <= 1:
            return

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
        active_danmakus: list['ActiveDanmaku'],
        zone_top: int,
        current_time: float | None = None,
        dwell_time: float | None = None,
    ) -> None:
        """回收超出屏幕范围的弹幕，释放缓存图片以控制内存。"""
        remaining: list['ActiveDanmaku'] = []
        for dm in active_danmakus:
            out = dm.is_out_of_bounds(zone_top)
            expired = (
                dwell_time is not None
                and current_time is not None
                and (current_time - dm.spawn_time) > dwell_time
            )
            if out or expired:
                dm.cached_image = QImage()  # 显式触发 C++ 析构，立即释放像素缓冲区
            else:
                remaining.append(dm)
        active_danmakus[:] = remaining

    @staticmethod
    def update_danmaku_layer(
        active_danmakus: list['ActiveDanmaku'],
        has_new: bool,
        zone_bottom: int,
        zone_top: int,
        gap: int,
        damping: float,
        current_time: float | None = None,
        dwell_time: float | None = None,
    ) -> None:
        """更新单层弹幕：位置更新、越界回收、碰撞处理。

        将文本弹幕和礼物弹幕的共同处理逻辑提取为统一接口。

        Args:
            active_danmakus: 活跃弹幕列表
            has_new: 是否有新弹幕加入
            zone_bottom: 区域底部边界
            zone_top: 区域顶部边界（越界判断）
            gap: 弹幕间距
            damping: 阻尼系数
            current_time: 当前时间（礼物停留计时用，可选）
            dwell_time: 停留时间（礼物用，可选）
        """
        if not has_new and active_danmakus:
            all_stable = _all_positions_stable(active_danmakus)
        else:
            all_stable = False

        LayoutEngine._update_and_collide(
            active_danmakus, has_new, zone_bottom, zone_top, gap, damping,
            skip_collision=all_stable,
        )
        LayoutEngine.recycle_out_of_bounds(
            active_danmakus, zone_top, current_time, dwell_time,
        )

    @staticmethod
    def _update_and_collide(
        active_danmakus: list['ActiveDanmaku'],
        has_new: bool,
        zone_bottom: int,
        zone_top: int,
        gap: int,
        damping: float = 0.25,
        position_threshold: float = 0.1,
        skip_collision: bool = False,
    ) -> None:
        """合并位置更新和碰撞检测为一次遍历。

        原来 update_positions + handle_collisions 需要两次遍历 active_danmakus，
        合并后只需一次遍历即可完成位置更新 + 碰撞检测。

        Args:
            active_danmakus: 活跃弹幕列表
            has_new: 是否有新弹幕加入
            zone_bottom: 区域底部边界
            zone_top: 区域顶部边界
            gap: 弹幕间距
            damping: 阻尼系数
            position_threshold: 位置变化阈值
            skip_collision: 是否跳过碰撞检测（所有弹幕位置已稳定时）
        """
        n = len(active_danmakus)
        if n == 0:
            return

        # ---- 阶段 1：新弹幕加入时重新计算目标位置 ----
        if has_new:
            last_target_y = zone_bottom
            for dm in reversed(active_danmakus):
                dm.target_y = last_target_y - dm.height
                last_target_y = dm.target_y - gap
                dm.is_locked_to_next = False

        # ---- 阶段 2：阻尼动画更新当前位置 ----
        for i, dm in enumerate(active_danmakus):
            if dm.is_first_activation:
                entry_y = float(zone_bottom - dm.height)
                if i > 0:
                    above = active_danmakus[i - 1]
                    above_bottom = above.current_y + above.height
                    entry_y = min(entry_y, above_bottom + gap)
                dm.current_y = entry_y
                dm.is_first_activation = False
            else:
                diff = dm.target_y - dm.current_y
                if abs(diff) > position_threshold:
                    dm.current_y += diff * damping

        # ---- 阶段 3：碰撞检测（稳定期跳过） ----
        if skip_collision or n <= 1:
            return

        visible_start = 0
        while visible_start < n:
            if active_danmakus[visible_start].current_y + active_danmakus[visible_start].height <= zone_top:
                visible_start += 1
            else:
                break

        if n - visible_start <= 1:
            return

        for i in range(n - 2, visible_start - 1, -1):
            curr = active_danmakus[i]
            next_dm = active_danmakus[i + 1]

            if curr.is_locked_to_next:
                curr.current_y = next_dm.current_y - gap - curr.height
                continue

            max_bottom = next_dm.current_y - gap
            curr_bottom = curr.current_y + curr.height

            if curr_bottom > max_bottom:
                new_y = max_bottom - curr.height
                curr.current_y = new_y
                if curr.target_y > new_y:
                    curr.target_y = new_y
                    curr.is_locked_to_next = True


# =============================================================================
# 模块级辅助函数
# =============================================================================

def _all_positions_stable(
    active_danmakus: list[ActiveDanmaku],
    threshold: float = 0.5,
) -> bool:
    """检查所有弹幕位置是否已稳定（目标位置与当前位置差小于阈值）。"""
    for dm in active_danmakus:
        if abs(dm.target_y - dm.current_y) >= threshold:
            return False
    return True