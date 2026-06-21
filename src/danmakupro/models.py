"""弹幕数据模型模块

定义弹幕渲染所需的所有数据结构：
    - DanmakuEvent:   弹幕事件（从 XML 解析得到）
    - RenderSegment:  渲染段落（文本、Emoji、礼物图片等）
    - TextRow:        文本行（由多个 RenderSegment 组成）
    - ActiveDanmaku:  活跃弹幕节点（当前屏幕上显示的弹幕）
"""

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics

from .config import (
    DANMAKU_X, BUBBLE_PADDING_X, BUBBLE_PADDING_Y,
    BUBBLE_ROW_GAP, BUBBLE_MULTILINE_RADIUS,
    GIFT_SPACING, EMOJI_SPACING, EMOJI_PATTERN,
)
from .utils import has_emoji


# =============================================================================
# 数据类
# =============================================================================

@dataclass(slots=True)
class DanmakuEvent:
    """弹幕事件：代表一条弹幕或礼物消息"""
    time: float
    user: str
    text: str
    is_gift: bool = False
    gift_name: str = ""
    gift_count: int = 0


@dataclass(slots=True)
class RenderSegment:
    """渲染段落：弹幕中的最小渲染单元（文本/图片/间距）"""
    type: str
    content: str
    width: int
    color: QColor | None = None
    has_cache: bool = False


@dataclass(slots=True)
class TextRow:
    """文本行：由多个 RenderSegment 组成的水平排列"""
    segments: list[RenderSegment] = field(default_factory=list)
    width: int = 0


# =============================================================================
# ActiveDanmaku - 活跃弹幕节点
# =============================================================================

class ActiveDanmaku:
    """活跃弹幕节点：存储和管理当前屏幕上的一条弹幕。

    负责：
        - 解析弹幕文本为渲染段落（_build_raw_segments）
        - 折行处理（_wrap_segments）
        - 计算气泡尺寸（_calc_dimensions）
        - 预渲染到缓存图片（_pre_render）
        - 最终绘制（render）
        - 越界检测（is_out_of_bounds）

    使用 __slots__ 而非 __dict__ 以节省内存（每条弹幕约节省 1KB）。
    """

    __slots__ = [
        'event', 'current_y', 'target_y', 'x', 'max_content_width', 'rows',
        'total_width', 'height', 'padding_x', 'padding_y', 'line_height',
        'row_gap', 'radius', 'is_locked_to_next', 'is_first_activation',
        'text_ascent', 'text_descent', 'vertical_padding', 'cached_image',
    ]

    # 颜色常量
    COLOR_NORMAL_PREFIX = QColor(135, 206, 250)  # 用户名前缀颜色（浅蓝）
    COLOR_WHITE = QColor(255, 255, 255)          # 普通文本颜色（白色）
    COLOR_GIFT_TEXT = QColor(255, 255, 150)      # 礼物文本颜色（浅黄）

    def __init__(
        self,
        event: DanmakuEvent,
        font_metrics: QFontMetrics,
        emoji_cache: dict[str, QImage],
        gift_cache: dict[str, QImage],
        max_content_width: int,
        line_height: int,
    ):
        """初始化活跃弹幕节点。

        Args:
            event: 弹幕事件数据
            font_metrics: 字体度量信息
            emoji_cache: Emoji 图片缓存字典
            gift_cache: 礼物图片缓存字典
            max_content_width: 最大内容宽度（像素）
            line_height: 行高（像素）
        """
        self.event = event
        self.current_y = 0.0          # 当前弹幕 Y 坐标（用于动画）
        self.target_y = 0.0           # 目标弹幕 Y 坐标
        self.x = DANMAKU_X            # 弹幕/渲染层X 偏移
        self.max_content_width = max_content_width
        self.rows: list[TextRow] = []
        self.total_width = 0          # 气泡总宽度
        self.height = 0               # 气泡高度
        self.padding_x = BUBBLE_PADDING_X
        self.padding_y = BUBBLE_PADDING_Y
        self.line_height = line_height
        self.row_gap = BUBBLE_ROW_GAP
        self.radius = BUBBLE_MULTILINE_RADIUS
        self.is_locked_to_next = False     # 是否锁定到下一个弹幕（碰撞处理）
        self.is_first_activation = True    # 是否首次激活（用于入场动画）

        # 构建渲染段落 -> 折行 -> 计算尺寸
        raw_segments = self._build_raw_segments(font_metrics, emoji_cache, gift_cache)
        max_row_width_seen = self._wrap_segments(font_metrics, raw_segments)
        self._calc_dimensions(max_row_width_seen)

        # 文本度量参数（用于绘制基线对齐）
        self.text_ascent = font_metrics.ascent()
        self.text_descent = font_metrics.descent()
        self.vertical_padding = (self.line_height - self.text_ascent - self.text_descent) // 2

        # 预渲染缓存图片（懒加载：首次激活时才渲染）
        self.cached_image: QImage | None = None

    # -------------------------------------------------------------------------
    # 构建原始渲染段落
    # -------------------------------------------------------------------------

    def _build_raw_segments(
        self,
        fm: QFontMetrics,
        emoji_cache: dict[str, QImage],
        gift_cache: dict[str, QImage],
    ) -> list[RenderSegment]:
        """将弹幕文本解析为原始渲染段落（未折行）。

        解析优先级：
            1. 礼物弹幕 -> 用户名 + 礼物名 + 礼物图片 + 数量
            2. 普通弹幕 -> 用户名 + 文本（含 Emoji 替换）

        Args:
            fm: 字体度量信息
            emoji_cache: Emoji 图片缓存
            gift_cache: 礼物图片缓存

        Returns:
            原始渲染段落列表
        """
        raw_segments: list[RenderSegment] = []
        img_target_size = self.line_height

        if self.event.is_gift:
            # 礼物弹幕格式：{用户} 送出 {礼物名} [图片] x {数量}
            user_prefix = f"{self.event.user} "
            raw_segments.append(RenderSegment(
                'text', user_prefix, fm.horizontalAdvance(user_prefix), self.COLOR_NORMAL_PREFIX,
            ))
            action_text = "送出 "
            raw_segments.append(RenderSegment(
                'text', action_text, fm.horizontalAdvance(action_text), self.COLOR_GIFT_TEXT,
            ))
            raw_segments.append(RenderSegment(
                'text', self.event.gift_name, fm.horizontalAdvance(self.event.gift_name),
                self.COLOR_GIFT_TEXT,
            ))
            if self.event.gift_name in gift_cache:
                raw_segments.append(RenderSegment('spacing', '', GIFT_SPACING))
                raw_segments.append(RenderSegment(
                    'gift_image', self.event.gift_name, img_target_size, has_cache=True,
                ))
            count_text = f" x {self.event.gift_count} "
            raw_segments.append(RenderSegment(
                'text', count_text, fm.horizontalAdvance(count_text), self.COLOR_GIFT_TEXT,
            ))
        else:
            # 普通弹幕格式：{用户}: {文本}
            prefix = self.event.user + ': '
            raw_segments.append(RenderSegment(
                'text', prefix, fm.horizontalAdvance(prefix), self.COLOR_NORMAL_PREFIX,
            ))

        # 解析文本内容（处理 Emoji）
        # 只有礼物弹幕且无文本时才跳过，其余情况均解析
        if not self.event.is_gift or self.event.text:
            text = self.event.text
            if not has_emoji(text):
                # 无 Emoji，整段作为纯文本
                raw_segments.append(RenderSegment(
                    'text', text, fm.horizontalAdvance(text), self.COLOR_WHITE,
                ))
            else:
                # 有 Emoji，分段解析
                last_idx = 0
                for match in EMOJI_PATTERN.finditer(text):
                    if match.start() > last_idx:
                        part = text[last_idx:match.start()]
                        raw_segments.append(RenderSegment(
                            'text', part, fm.horizontalAdvance(part), self.COLOR_WHITE,
                        ))
                        raw_segments.append(RenderSegment('spacing', '', EMOJI_SPACING))
                    emoji_name = match.group(1)
                    if emoji_name in emoji_cache:
                        raw_segments.append(RenderSegment(
                            'emoji', emoji_name, img_target_size, has_cache=True,
                        ))
                        raw_segments.append(RenderSegment('spacing', '', EMOJI_SPACING))
                    else:
                        full_string = match.group(0)
                        raw_segments.append(RenderSegment(
                            'text', full_string, fm.horizontalAdvance(full_string), self.COLOR_WHITE,
                        ))
                    last_idx = match.end()
                if last_idx < len(text):
                    part = text[last_idx:]
                    raw_segments.append(RenderSegment(
                        'text', part, fm.horizontalAdvance(part), self.COLOR_WHITE,
                    ))

        return raw_segments

    # -------------------------------------------------------------------------
    # 折行处理
    # -------------------------------------------------------------------------

    def _wrap_segments(
        self,
        fm: QFontMetrics,
        raw_segments: list[RenderSegment],
    ) -> int:
        """将原始渲染段落按最大内容宽度折行为多行。

        使用二分查找确定每行能容纳的最大文本长度，确保中文/英文混合
        文本的折行边界准确。

        Args:
            fm: 字体度量信息
            raw_segments: 原始渲染段落列表

        Returns:
            所有行中的最大宽度
        """
        current_row = TextRow()
        self.rows.append(current_row)
        max_row_width_seen = 0

        for seg in raw_segments:
            if seg.type in ('emoji', 'gift_image', 'spacing'):
                # 图片/间距：不可拆分，超出宽度则换行
                if current_row.width + seg.width > self.max_content_width and current_row.width > 0:
                    max_row_width_seen = max(max_row_width_seen, current_row.width)
                    current_row = TextRow()
                    self.rows.append(current_row)
                current_row.segments.append(seg)
                current_row.width += seg.width
            else:
                # 文本：使用二分查找在最大宽度内尽量多地容纳字符
                text_content = seg.content
                while text_content:
                    remaining_space = self.max_content_width - current_row.width
                    if remaining_space <= 0 or (
                        fm.horizontalAdvance(text_content[0]) > remaining_space and current_row.width > 0
                    ):
                        max_row_width_seen = max(max_row_width_seen, current_row.width)
                        current_row = TextRow()
                        self.rows.append(current_row)
                        remaining_space = self.max_content_width

                    # 快速路径：整段文本能放入当前行，跳过二分查找
                    full_width = fm.horizontalAdvance(text_content)
                    if full_width <= remaining_space:
                        current_row.segments.append(RenderSegment(
                            'text', text_content, full_width, seg.color,
                        ))
                        current_row.width += full_width
                        break

                    # 二分查找最长的可容纳子串
                    low = 1
                    high = len(text_content)
                    sub_len = 0
                    best_w = 0
                    while low <= high:
                        mid = (low + high) // 2
                        current_w = fm.horizontalAdvance(text_content[:mid])
                        if current_w <= remaining_space:
                            sub_len = mid
                            best_w = current_w
                            low = mid + 1
                        else:
                            high = mid - 1

                    if sub_len == 0:
                        sub_len = 1
                        best_w = fm.horizontalAdvance(text_content[:1])

                    current_row.segments.append(RenderSegment(
                        'text', text_content[:sub_len], best_w, seg.color,
                    ))
                    current_row.width += best_w
                    text_content = text_content[sub_len:]

        return max(max_row_width_seen, current_row.width)

    # -------------------------------------------------------------------------
    # 计算弹幕尺寸
    # -------------------------------------------------------------------------

    def _calc_dimensions(self, max_row_width_seen: int):
        """根据折行结果计算气泡的总宽度和高度。

        单行气泡使用半圆角（高度的一半），多行气泡使用固定圆角。

        Args:
            max_row_width_seen: 所有行中的最大宽度
        """
        self.total_width = max_row_width_seen + (self.padding_x * 2)
        num_rows = len(self.rows)
        self.height = (
            (self.padding_y * 2)
            + (num_rows * self.line_height)
            + ((num_rows - 1) * self.row_gap)
        )
        if num_rows == 1:
            self.radius = self.height / 2.0
        else:
            self.radius = BUBBLE_MULTILINE_RADIUS

    # -------------------------------------------------------------------------
    # 预渲染到缓存图片
    # -------------------------------------------------------------------------

    def _pre_render(
        self,
        font: QFont,
        emoji_cache: dict[str, QImage],
        gift_cache: dict[str, QImage],
        bg_color: QColor,
    ) -> None:
        """预渲染弹幕到 QImage 缓存。

        将弹幕的所有渲染工作（文本绘制、图片绘制、背景绘制）一次性完成，
        后续渲染时只需一次 drawImage() 调用，大幅降低每帧绘制开销。

        Args:
            font: 字体对象
            emoji_cache: Emoji 图片缓存
            gift_cache: 礼物图片缓存
            bg_color: 背景颜色（含透明度）
        """
        self.cached_image = QImage(
            self.total_width, self.height, QImage.Format.Format_ARGB32,
        )
        self.cached_image.fill(Qt.GlobalColor.transparent)

        painter = QPainter(self.cached_image)
        painter.setFont(font)
        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            0, 0, self.total_width, self.height, self.radius, self.radius,
        )

        for r_idx, row in enumerate(self.rows):
            curr_row_top = self.padding_y + (r_idx * (self.line_height + self.row_gap))
            text_baseline_y = curr_row_top + self.vertical_padding + self.text_ascent
            curr_x = self.padding_x

            for seg in row.segments:
                if seg.type == 'text':
                    painter.setPen(seg.color)
                    painter.drawText(curr_x, text_baseline_y, seg.content)
                elif seg.type == 'emoji':
                    if seg.has_cache:
                        scaled_img = emoji_cache[seg.content]
                        emoji_y = curr_row_top + (self.line_height - scaled_img.height()) // 2
                        painter.drawImage(curr_x, emoji_y, scaled_img)
                elif seg.type == 'gift_image':
                    if seg.has_cache:
                        scaled_img = gift_cache[seg.content]
                        gift_y = curr_row_top + (self.line_height - scaled_img.height()) // 2
                        painter.drawImage(curr_x, gift_y, scaled_img)
                curr_x += seg.width

        painter.end()

    # -------------------------------------------------------------------------
    # 渲染 & 越界检测
    # -------------------------------------------------------------------------

    def render(self, painter: QPainter, x: int, y: int):
        """使用缓存的预渲染图片绘制弹幕。

        Args:
            painter: QPainter 对象
            x: 绘制 X 坐标
            y: 绘制 Y 坐标
        """
        if self.cached_image:
            painter.drawImage(x, y, self.cached_image)

    def is_out_of_bounds(self, max_y_limit: float) -> bool:
        """判断弹幕是否已经完全飞出屏幕顶部。

        Args:
            max_y_limit: 弹幕区顶部 Y 坐标（低于此值视为越界）

        Returns:
            True 表示弹幕已完全不可见，可以回收
        """
        return self.current_y + self.height <= max_y_limit