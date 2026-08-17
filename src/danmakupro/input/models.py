"""输入数据模型

定义弹幕事件和渲染相关的数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

from ..config.models import LayoutStyle, DEFAULT_CONFIG


# =============================================================================
# 数据类
# =============================================================================

@dataclass(slots=True)
class DanmakuEvent:
    """弹幕事件"""
    time: float
    user: str
    text: str
    is_gift: bool = False
    gift_name: str = ""
    gift_count: int = 0


@dataclass(slots=True)
class RenderSegment:
    """渲染段落"""
    type: str
    content: str
    width: int
    color: QColor | None = None
    has_cache: bool = False


@dataclass(slots=True)
class TextRow:
    """文本行"""
    segments: list[RenderSegment] = field(default_factory=list)
    width: int = 0


def _strip_trailing_spacing(row: TextRow) -> None:
    """移除行尾无用的间距段（spacing 在行尾不可见，浪费空间）。"""
    while row.segments and row.segments[-1].type == 'spacing':
        removed = row.segments.pop()
        row.width -= removed.width


def _find_fit_len(fm: QFontMetrics, text: str, max_width: int) -> tuple[int, int]:
    """二分查找文本中最长的可容纳子串。

    Args:
        fm: 字体度量信息
        text: 文本内容
        max_width: 最大像素宽度
    Returns:
        (sub_len, width): 可容纳的字符数和实际像素宽度
    """
    low, high = 1, len(text)
    sub_len, best_w = 0, 0
    while low <= high:
        mid = (low + high) // 2
        w = fm.horizontalAdvance(text[:mid])
        if w <= max_width:
            sub_len, best_w = mid, w
            low = mid + 1
        else:
            high = mid - 1
    if sub_len == 0:
        # 单个字符宽度超过 max_width，强制取 1 个字符（允许溢出）
        sub_len = 1
        best_w = fm.horizontalAdvance(text[:1])
    return sub_len, best_w


# =============================================================================
# ActiveDanmaku - 活跃弹幕节点
# =============================================================================

class ActiveDanmaku:
    """活跃弹幕节点：存储和管理当前屏幕上的一条弹幕。

    职责：
        - 解析弹幕文本为渲染段落 (_build_raw_segments)
        - 折行处理 (_wrap_segments)
        - 计算气泡尺寸 (_calc_dimensions)
        - 预渲染到缓存图片 (_pre_render)
        - 最终绘制 (render)
        - 越界检测 (is_out_of_bounds)

    使用 __slots__ 而非 __dict__ 以节省内存（每条弹幕约节省 1KB）。
    """

    __slots__ = [
        'event', 'current_y', 'target_y', 'x', 'max_content_width', 'rows',
        'total_width', 'height', 'padding_x', 'padding_y', 'line_height',
        'row_gap', 'radius', 'is_locked_to_next', 'is_first_activation',
        'text_ascent', 'vertical_padding', 'cached_image',
        'spawn_time',
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
        style: LayoutStyle = DEFAULT_CONFIG.style,
    ):
        """初始化活跃弹幕节点。

        Args:
            event: 弹幕事件数据
            font_metrics: 字体度量信息
            emoji_cache: Emoji 图片缓存字典
            gift_cache: 礼物图片缓存字典
            max_content_width: 最大内容宽度（像素）
            line_height: 行高（像素）
            style: 布局样式配置
        """
        self.event = event
        self.current_y = 0.0          # 当前弹幕 Y 坐标（用于动画）
        self.target_y = 0.0           # 目标弹幕 Y 坐标
        self.x = style.danmaku_x      # 弹幕/渲染层 X 偏移
        self.max_content_width = max_content_width
        self.rows: list[TextRow] = []
        self.total_width = 0          # 气泡总宽度
        self.height = 0               # 气泡高度
        self.padding_x = style.bubble_padding_x
        self.padding_y = style.bubble_padding_y
        self.line_height = line_height
        self.row_gap = style.bubble_row_gap
        self.radius = style.bubble_multiline_radius
        self.is_locked_to_next = False     # 是否锁定到下一个弹幕（碰撞处理）
        self.is_first_activation = True    # 是否首次激活（用于入场动画）
        self.spawn_time = 0.0              # 生成时间（用于礼物停留计时）

        # 构建渲染段落 -> 折行 -> 计算尺寸
        raw_segments = self._build_raw_segments(font_metrics, emoji_cache, gift_cache)
        max_row_width_seen = self._wrap_segments(font_metrics, raw_segments)
        self._calc_dimensions(max_row_width_seen)

        # 文本度量参数（用于绘制基线对齐）
        text_ascent = font_metrics.ascent()
        text_descent = font_metrics.descent()
        self.text_ascent = text_ascent
        self.vertical_padding = (self.line_height - text_ascent - text_descent) // 2

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
            fm: 字体度量信息，用于计算文本像素宽度
            emoji_cache: Emoji 图片缓存，key 为 emoji 名称，value 为缩放后的 QImage
            gift_cache: 礼物图片缓存，key 为礼物名称，value 为缩放后的 QImage
        Returns:
            原始渲染段落列表（未折行，每个段落包含 type、content、width 等属性）
        """
        img_target_size = self.line_height

        if self.event.is_gift:
            return self._build_gift_segments(fm, gift_cache, img_target_size)

        return self._build_text_segments(fm, emoji_cache, img_target_size)

    def _build_gift_segments(
        self,
        fm: QFontMetrics,
        gift_cache: dict[str, QImage],
        img_target_size: int,
    ) -> list[RenderSegment]:
        """构建礼物弹幕的渲染段落。

        格式：{用户} 送出 {礼物名} [图片] x {数量}
        Args:
            fm: 字体度量信息
            gift_cache: 礼物图片缓存
            img_target_size: 图片目标尺寸（像素）
        Returns:
            礼物弹幕的渲染段落列表
        """
        raw_segments: list[RenderSegment] = []

        user_prefix = f"{self.event.user} "
        raw_segments.append(RenderSegment(
            'text', user_prefix, fm.horizontalAdvance(user_prefix), self.COLOR_NORMAL_PREFIX
        ))
        action_text = "送出 "
        raw_segments.append(RenderSegment(
            'text', action_text, fm.horizontalAdvance(action_text), self.COLOR_GIFT_TEXT
        ))
        raw_segments.append(RenderSegment(
            'text', self.event.gift_name, fm.horizontalAdvance(self.event.gift_name),
            self.COLOR_GIFT_TEXT
        ))
        if self.event.gift_name in gift_cache:
            raw_segments.append(RenderSegment('spacing', '', DEFAULT_CONFIG.style.gift_spacing))
            raw_segments.append(RenderSegment(
                'gift_image', self.event.gift_name, img_target_size, has_cache=True
            ))
        count_text = f" x {self.event.gift_count} "
        raw_segments.append(RenderSegment(
            'text', count_text, fm.horizontalAdvance(count_text), self.COLOR_GIFT_TEXT
        ))
        return raw_segments

    def _build_text_segments(
        self,
        fm: QFontMetrics,
        emoji_cache: dict[str, QImage],
        img_target_size: int,
    ) -> list[RenderSegment]:
        """解析弹幕文本为渲染段落，处理 Emoji 替换。

        连续普通字符合并为一个段，Emoji 替换为图片段。
        不再使用 has_emoji 预检查，统一 while 循环解析。
        Args:
            fm: 字体度量信息
            emoji_cache: Emoji 图片缓存
            img_target_size: 图片目标尺寸（像素）
        Returns:
            普通弹幕的渲染段落列表
        """
        raw_segments: list[RenderSegment] = []

        prefix = self.event.user + ': '
        raw_segments.append(RenderSegment(
            'text', prefix, fm.horizontalAdvance(prefix), self.COLOR_NORMAL_PREFIX
        ))

        text = self.event.text
        i = 0
        buffer: list[str] = []

        def flush_buffer():
            if buffer:
                merged = ''.join(buffer)
                raw_segments.append(RenderSegment(
                    'text', merged, fm.horizontalAdvance(merged), self.COLOR_WHITE
                ))
                buffer.clear()

        while i < len(text):
            if text[i] == '[':
                end = text.find(']', i)
                if end != -1:
                    name = text[i + 1:end]
                    if name in emoji_cache:
                        flush_buffer()
                        if raw_segments and raw_segments[-1].type != 'spacing':
                            raw_segments.append(RenderSegment(
                                'spacing', '', DEFAULT_CONFIG.style.emoji_spacing
                            ))
                        raw_segments.append(RenderSegment(
                            'emoji', name, img_target_size, has_cache=True
                        ))
                        i = end + 1
                        continue
            buffer.append(text[i])
            i += 1

        flush_buffer()
        return raw_segments

    # -------------------------------------------------------------------------
    # 折行处理
    # -------------------------------------------------------------------------
    def _wrap_segments(
        self,
        fm: QFontMetrics,
        raw_segments: list[RenderSegment],
    ) -> int:
        """将原始段落按最大宽度折行。

        折行策略：
            - 优先整段保留（不拆分 Emoji 或礼物图片）
            - 文本段落过长时，使用二分查找拆分
        Args:
            fm: 字体度量信息，用于计算文本像素宽度（二分查找拆分点）
            raw_segments: 原始渲染段落列表（由 _build_raw_segments 生成）
        Returns:
            所有行中的最大宽度（像素），用于后续计算气泡总宽度
        """
        self.rows = []
        current_row = TextRow()
        current_width = 0
        max_row_width_seen = 0

        def settle_row():
            """结算当前行：去尾空格、追加到行列表、更新最大宽度。"""
            nonlocal current_row, current_width, max_row_width_seen
            if not current_row.segments:
                return
            _strip_trailing_spacing(current_row)
            if current_row.segments:
                self.rows.append(current_row)
                max_row_width_seen = max(max_row_width_seen, current_row.width)
            current_row = TextRow()
            current_width = 0

        for seg in raw_segments:
            seg_w = seg.width

            # 整段能放下，直接追加
            if current_width + seg_w <= self.max_content_width:
                current_row.segments.append(seg)
                current_width += seg_w
                current_row.width = current_width
                continue

            # 整段放不下：文本优先拆分紧跟当前行（如用户名后紧跟文本）
            if seg.type == 'text' and current_row.segments:
                remaining_space = self.max_content_width - current_width
                if remaining_space > 0:
                    sub_len, best_w = _find_fit_len(fm, seg.content, remaining_space)
                    if sub_len > 0:
                        current_row.segments.append(RenderSegment(
                            'text', seg.content[:sub_len], best_w, seg.color
                        ))
                        current_row.width += best_w
                        settle_row()
                        remaining = seg.content[sub_len:]
                        seg = RenderSegment(
                            'text', remaining, fm.horizontalAdvance(remaining), seg.color
                        )
                        seg_w = seg.width

            settle_row()

            # spacing 在行首无意义，跳过
            if seg.type == 'spacing':
                continue

            # 不可拆分的段落（Emoji、图片）独占一行
            if seg.type in ('emoji', 'gift_image'):
                current_row.segments.append(seg)
                current_row.width = seg_w
                self.rows.append(current_row)
                max_row_width_seen = max(max_row_width_seen, seg_w)
                current_row = TextRow()
                current_width = 0
                continue

            # 文本段落可拆分
            text_content = seg.content
            text_color = seg.color
            while text_content:
                remaining_space = self.max_content_width - current_width
                if remaining_space <= 0:
                    settle_row()
                    remaining_space = self.max_content_width

                sub_len, best_w = _find_fit_len(fm, text_content, remaining_space)
                current_row.segments.append(RenderSegment(
                    'text', text_content[:sub_len], best_w, text_color
                ))
                current_row.width += best_w
                current_width += best_w
                text_content = text_content[sub_len:]

        settle_row()
        return max_row_width_seen

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
            self.radius = int(self.height // 2)
        else:
            self.radius = int(DEFAULT_CONFIG.style.bubble_multiline_radius)

    # -------------------------------------------------------------------------
    # 预渲染到缓存图片
    # -------------------------------------------------------------------------
    def pre_render(
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
            self.total_width, self.height, QImage.Format.Format_ARGB32
        )
        self.cached_image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.cached_image)
        painter.setFont(font)
        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            0, 0, self.total_width, self.height, self.radius, self.radius
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