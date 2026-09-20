"""布局引擎

负责弹幕布局计算、位置更新、碰撞检测和弹幕生成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..config.models import LayoutStyle, LayoutRatio, AnimationParams, DEFAULT_CONFIG

if TYPE_CHECKING:
    from ..input.event import DanmakuEvent
    from ..render.assets import AssetLoader
    from ..render.layout_builder import DanmakuLayoutBuilder
    from ..render.active_view import ActiveDanmakuView

from .active import ActiveDanmaku
from .params import LayoutParams, LayerParams


@dataclass
class LayoutContext:
    """布局上下文"""

    animation: AnimationParams = field(default_factory=lambda: DEFAULT_CONFIG.animation)
    text_event_idx: int = 0
    gift_event_idx: int = 0
    # 上次发射文本弹幕的时间。-1.0 表示尚未发射过。
    last_text_spawn_time: float = -1.0
    # 上次发射礼物弹幕的时间。-1.0 表示尚未发射过。
    last_gift_spawn_time: float = -1.0


class LayoutEngine:
    """布局引擎"""

    @staticmethod
    def effective_spawn_interval(
        pending: int,
        batch_size: int,
        spawn_interval: float,
        max_latency: float | None,
    ) -> float:
        """按积压量自适应收紧发射间隔。

        当积压超过一个批次且清空时间超过 ``max_latency`` 时，
        临时提升排空速率至 ``pending / max_latency``，否则沿用基础间隔。

        Args:
            pending: 待发射的同层弹幕数
            batch_size: 单次发射上限
            spawn_interval: 基础发射间隔（秒）
            max_latency: 允许的最大积压等待时长（秒），None 禁用自适应

        Returns:
            本帧发射间隔（秒）
        """
        if max_latency is None or spawn_interval <= 0 or pending <= batch_size:
            return spawn_interval
        base_rate = batch_size / spawn_interval
        need_rate = pending / max_latency
        if need_rate <= base_rate:
            return spawn_interval
        return batch_size / need_rate

    @staticmethod
    def calculate_params(
        w: int,
        h: int,
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
            layer_x=layer_x,
            layer_y=layer_y,
            layer_w=layer_w,
            layer_h=layer_h,
        )

        return layout_params, layer_params

    @staticmethod
    def spawn_new_danmakus(
        ctx: LayoutContext,
        current_time: float,
        event_pool: list["DanmakuEvent"],
        active_text: list["ActiveDanmakuView"],
        active_gift: list["ActiveDanmakuView"],
        layout_builder: "DanmakuLayoutBuilder",
        asset_provider: "AssetLoader",
        style: LayoutStyle = DEFAULT_CONFIG.style,
    ) -> tuple[bool, bool, int, int]:
        """惰性按需生成新弹幕。

        文本和礼物使用独立的 event_idx 互不阻塞。
        无积压时立即发射，有积压时按批次限流，
        间隔由 :meth:`effective_spawn_interval` 自适应收紧。

        Returns:
            (text_has_new, gift_has_new, text_emitted, gift_emitted)
        """
        animation = ctx.animation
        pool = event_pool

        text_emitted = LayoutEngine._spawn_layer(
            ctx=ctx,
            current_time=current_time,
            pool=pool,
            want_gift=False,
            active=active_text,
            batch_size=animation.text_spawn_batch_size,
            spawn_interval=animation.text_spawn_interval,
            max_latency=animation.max_spawn_latency,
            idx_attr="text_event_idx",
            last_spawn_attr="last_text_spawn_time",
            layout_builder=layout_builder,
            asset_provider=asset_provider,
            style=style,
        )

        gift_emitted = LayoutEngine._spawn_layer(
            ctx=ctx,
            current_time=current_time,
            pool=pool,
            want_gift=True,
            active=active_gift,
            batch_size=animation.gift_spawn_batch_size,
            spawn_interval=animation.gift_spawn_interval,
            max_latency=animation.max_spawn_latency,
            idx_attr="gift_event_idx",
            last_spawn_attr="last_gift_spawn_time",
            layout_builder=layout_builder,
            asset_provider=asset_provider,
            style=style,
        )

        return text_emitted > 0, gift_emitted > 0, text_emitted, gift_emitted

    @staticmethod
    def _spawn_layer(
        *,
        ctx: LayoutContext,
        current_time: float,
        pool: list["DanmakuEvent"],
        want_gift: bool,
        active: list["ActiveDanmakuView"],
        batch_size: int,
        spawn_interval: float,
        max_latency: float | None,
        idx_attr: str,
        last_spawn_attr: str,
        layout_builder: "DanmakuLayoutBuilder",
        asset_provider: "AssetLoader",
        style: LayoutStyle,
    ) -> int:
        """发射单层弹幕（文本层与礼物层共用同一套节流逻辑）。

        扫描游标与「上次发射时间」通过属性名定位，因此两层各自独立推进：
        文本积压不会挡住排在后面的礼物，反之亦然。

        Args:
            ctx: 布局上下文（读写其中的游标与上次发射时间）
            current_time: 当前帧时间（秒）
            pool: 全部弹幕事件
            want_gift: True 处理礼物层，False 处理文本层
            active: 该层的活跃弹幕列表（就地追加）
            batch_size: 单次发射上限
            spawn_interval: 有积压时的最小发射间隔（秒）
            max_latency: 积压时的目标清空时长（秒），None 表示禁用自适应
            idx_attr: ctx 上的扫描游标属性名
            last_spawn_attr: ctx 上的上次发射时间属性名
            layout_builder: 弹幕布局构建器
            asset_provider: 资源提供者（字体、emoji/礼物缓存）
            style: 布局样式

        Returns:
            本帧实际发射的条数
        """
        from ..render.active_view import ActiveDanmakuView  # 惰性导入，避免循环依赖

        n = len(pool)
        idx = getattr(ctx, idx_attr)

        # ---- 统计时间窗口内的待处理量，并确定扫描终点 ----
        pending = 0
        scan_end = idx
        for i in range(idx, n):
            if pool[i].time > current_time:
                break
            if pool[i].is_gift == want_gift:
                pending += 1
            scan_end = i + 1

        last_spawn = getattr(ctx, last_spawn_attr)
        effective_interval = LayoutEngine.effective_spawn_interval(
            pending,
            batch_size,
            spawn_interval,
            max_latency,
        )
        can_spawn = (
            pending <= batch_size
            or last_spawn < 0.0
            or (current_time - last_spawn) >= effective_interval
        )

        if not can_spawn:
            return 0

        # ---- 按批次上限发射，游标扫过窗口内全部事件 ----
        emitted = 0
        while idx < scan_end and emitted < batch_size:
            event = pool[idx]
            if event.is_gift == want_gift:
                dm = ActiveDanmaku(
                    event=event,
                    layout=layout_builder.build(event),
                    x=style.danmaku_x,
                )
                view = ActiveDanmakuView(dm)
                view.pre_render(
                    asset_provider.font,
                    asset_provider.emoji_cache,
                    asset_provider.gift_cache,
                    style.bubble_bg_color,
                )
                view.spawn_time = current_time
                active.append(view)
                emitted += 1
            idx += 1

        setattr(ctx, idx_attr, idx)
        if emitted > 0:
            setattr(ctx, last_spawn_attr, current_time)
        return emitted

    @staticmethod
    def recycle_out_of_bounds(
        active_danmakus: list["ActiveDanmakuView"],
        zone_top: int,
        current_time: float | None = None,
        dwell_time: float | None = None,
    ) -> None:
        """回收超出屏幕范围的弹幕，释放缓存图片以控制内存。"""
        remaining: list["ActiveDanmakuView"] = []
        for dm in active_danmakus:
            out = dm.is_out_of_bounds(zone_top)
            expired = (
                dwell_time is not None
                and current_time is not None
                and (current_time - dm.spawn_time) > dwell_time
            )
            if out or expired:
                dm.clear_cache()
            else:
                remaining.append(dm)
        active_danmakus[:] = remaining

    @staticmethod
    def update_danmaku_layer(
        active_danmakus: list["ActiveDanmakuView"],
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
            active_danmakus,
            has_new,
            zone_bottom,
            zone_top,
            gap,
            damping,
            skip_collision=all_stable,
        )
        LayoutEngine.recycle_out_of_bounds(
            active_danmakus,
            zone_top,
            current_time,
            dwell_time,
        )

    @staticmethod
    def _update_and_collide(
        active_danmakus: Sequence["ActiveDanmaku | ActiveDanmakuView"],
        has_new: bool,
        zone_bottom: int,
        zone_top: int,
        gap: int,
        damping: float = 0.25,
        position_threshold: float = 0.1,
        skip_collision: bool = False,
    ) -> None:
        """合并位置更新和碰撞检测为一次遍历。

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
            if (
                active_danmakus[visible_start].current_y
                + active_danmakus[visible_start].height
                <= zone_top
            ):
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
    active_danmakus: Sequence["ActiveDanmaku | ActiveDanmakuView"],
    threshold: float = 0.5,
) -> bool:
    """检查所有弹幕位置是否已稳定（目标位置与当前位置差小于阈值）。"""
    for dm in active_danmakus:
        if abs(dm.target_y - dm.current_y) >= threshold:
            return False
    return True
