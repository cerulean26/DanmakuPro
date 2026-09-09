"""弹幕布局构建器

负责将 DanmakuEvent 解析为 DanmakuLayout（段落解析、折行、尺寸计算），
并提供预渲染和最终绘制能力。

将原 ActiveDanmaku 中的构造阶段逻辑（_build_raw_segments、_wrap_segments、
_calc_dimensions）和渲染逻辑（pre_render、render）提取为独立单元。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

from ..config.models import LayoutStyle, DEFAULT_CONFIG
from ..input.event import DanmakuEvent
from .segments import RenderSegment, TextRow


# =============================================================================
# 辅助函数
# =============================================================================

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
    return sub_len, best_w


# =============================================================================
# DanmakuLayout - 布局数据 + 渲染
# =============================================================================

class DanmakuLayout:
    """弹幕布局数据：折行结果、尺寸、渲染缓存。

    职责：
        - 存储折行后的渲染行列表和气泡尺寸
        - 预渲染到缓存图片 (pre_render)
        - 最终绘制 (render)

    使用 __slots__ 以节省内存。
    """

    __slots__ = [
        'rows', 'total_width', 'height', 'padding_x', 'padding_y',
        'line_height', 'row_gap', 'radius', 'text_ascent', 'vertical_padding',
        'cached_image',
    ]

    def __init__(
        self,
        rows: list[TextRow],
        total_width: int,
        height: int,
        padding_x: int,
        padding_y: int,
        line_height: int,
        row_gap: int,
        radius: float,
        text_ascent: int,
        vertical_padding: int,
    ):
        self.rows = rows
        self.total_width = total_width
        self.height = height
        self.padding_x = padding_x
        self.padding_y = padding_y
        self.line_height = line_height
        self.row_gap = row_gap
        self.radius = radius
        self.text_ascent = text_ascent
        self.vertical_padding = vertical_padding
        self.cached_image: QImage | None = None

    def pre_render(
        self,
        font: QFont,
        emoji_cache: dict[str, QImage],
        gift_cache: dict[str, QImage],
        bg_color: tuple[int, int, int, int],
    ) -> None:
        """预渲染弹幕到 QImage 缓存。

        将弹幕的所有渲染工作（文本绘制、图片绘制、背景绘制）一次性完成，
        后续渲染时只需一次 drawImage() 调用，大幅降低每帧绘制开销。
        Args:
            font: 字体对象
            emoji_cache: Emoji 图片缓存
            gift_cache: 礼物图片缓存
            bg_color: 背景颜色 (r, g, b, a)
        """
        self.cached_image = QImage(
            self.total_width, self.height, QImage.Format.Format_ARGB32
        )
        self.cached_image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.cached_image)
        painter.setFont(font)
        painter.setBrush(QColor(*bg_color))
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
                    painter.setPen(QColor(*seg.color))
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

    def render(self, painter: QPainter, x: int, y: int) -> None:
        """使用缓存的预渲染图片绘制弹幕。
        Args:
            painter: QPainter 对象
            x: 绘制 X 坐标
            y: 绘制 Y 坐标
        """
        if self.cached_image:
            painter.drawImage(x, y, self.cached_image)


# =============================================================================
# DanmakuLayoutBuilder - 布局构建器
# =============================================================================

class DanmakuLayoutBuilder:
    """弹幕布局构建器：将 DanmakuEvent 解析为 DanmakuLayout。

    职责：
        - 段落解析（_build_segments）
        - 折行处理（_wrap_segments）
        - 尺寸计算（_calc_dimensions）

    将原 ActiveDanmaku.__init__ 中的三步构造逻辑提取为独立可测试的单元。
    """

    def __init__(
        self,
        fm: QFontMetrics,
        emoji_cache: dict[str, QImage],
        gift_cache: dict[str, QImage],
        max_content_width: int,
        line_height: int,
        style: LayoutStyle = DEFAULT_CONFIG.style,
    ):
        """初始化构建器。

        Args:
            fm: 字体度量信息
            emoji_cache: Emoji 图片缓存
            gift_cache: 礼物图片缓存
            max_content_width: 最大内容宽度（像素）
            line_height: 行高（像素）
            style: 布局样式配置
        """
        self.fm = fm
        self.emoji_cache = emoji_cache
        self.gift_cache = gift_cache
        self.max_content_width = max_content_width
        self.line_height = line_height
        self.style = style

    def build(self, event: DanmakuEvent) -> DanmakuLayout:
        """构建弹幕布局。

        三步流程：段落解析 → 折行 → 尺寸计算。
        Args:
            event: 弹幕事件数据
        Returns:
            完整的 DanmakuLayout 实例
        """
        raw_segments = self._build_segments(event)
        rows, max_row_width = self._wrap_segments(raw_segments)
        return self._calc_dimensions(rows, max_row_width)

    # -------------------------------------------------------------------------
    # 段落解析
    # -------------------------------------------------------------------------
    def _build_segments(self, event: DanmakuEvent) -> list[RenderSegment]:
        """将弹幕文本解析为原始渲染段落（未折行）。

        解析优先级：
            1. 礼物弹幕 -> 用户名 + 礼物名 + 礼物图片 + 数量
            2. 普通弹幕 -> 用户名 + 文本（含 Emoji 替换）
        """
        if event.is_gift:
            return self._build_gift_segments(event)
        return self._build_text_segments(event)

    def _build_gift_segments(self, event: DanmakuEvent) -> list[RenderSegment]:
        """构建礼物弹幕的渲染段落。

        格式：{用户} 送出 {礼物名} [图片] x {数量}
        """
        raw_segments: list[RenderSegment] = []

        user_prefix = f"{event.user} "
        raw_segments.append(RenderSegment(
            'text', user_prefix, self.fm.horizontalAdvance(user_prefix), self.style.username_color
        ))
        action_text = "送出 "
        raw_segments.append(RenderSegment(
            'text', action_text, self.fm.horizontalAdvance(action_text), self.style.gift_color
        ))
        raw_segments.append(RenderSegment(
            'text', event.gift_name, self.fm.horizontalAdvance(event.gift_name),
            self.style.gift_color
        ))
        if event.gift_name in self.gift_cache:
            raw_segments.append(RenderSegment('spacing', '', self.style.gift_spacing))
            raw_segments.append(RenderSegment(
                'gift_image', event.gift_name,
                self.gift_cache[event.gift_name].width(), has_cache=True
            ))
        count_text = f" x {event.gift_count} "
        raw_segments.append(RenderSegment(
            'text', count_text, self.fm.horizontalAdvance(count_text), self.style.gift_color
        ))
        return raw_segments

    def _build_text_segments(self, event: DanmakuEvent) -> list[RenderSegment]:
        """解析弹幕文本为渲染段落，处理 Emoji 替换。

        连续普通字符合并为一个段，Emoji 替换为图片段。
        """
        raw_segments: list[RenderSegment] = []

        raw_segments.append(RenderSegment(
            'text', event.user, self.fm.horizontalAdvance(event.user), self.style.username_color
        ))
        raw_segments.append(RenderSegment('spacing', '', 5, None))
        raw_segments.append(RenderSegment(
            'text', ':', self.fm.horizontalAdvance(':'), self.style.username_color
        ))
        raw_segments.append(RenderSegment('spacing', '', 19, None))

        text = event.text
        i = 0
        buffer: list[str] = []

        def flush_buffer():
            if buffer:
                merged = ''.join(buffer)
                raw_segments.append(RenderSegment(
                    'text', merged, self.fm.horizontalAdvance(merged), self.style.text_color
                ))
                buffer.clear()

        while i < len(text):
            if text[i] == '[':
                end = text.find(']', i)
                if end != -1:
                    name = text[i + 1:end]
                    if name in self.emoji_cache:
                        flush_buffer()
                        if raw_segments and raw_segments[-1].type != 'spacing':
                            raw_segments.append(RenderSegment(
                                'spacing', '', self.style.emoji_spacing
                            ))
                        raw_segments.append(RenderSegment(
                            'emoji', name,
                            self.emoji_cache[name].width(), has_cache=True
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
        self, raw_segments: list[RenderSegment]
    ) -> tuple[list[TextRow], int]:
        """将原始段落按最大宽度折行。

        折行策略：
            - 优先整段保留（不拆分 Emoji 或礼物图片）
            - 文本段落过长时，使用二分查找拆分
        Args:
            raw_segments: 原始渲染段落列表
        Returns:
            (rows, max_row_width): 折行后的行列表和最大行宽
        """
        rows: list[TextRow] = []
        current_row = TextRow()
        current_width = 0
        max_row_width_seen = 0

        def settle_row():
            nonlocal current_row, current_width, max_row_width_seen
            if not current_row.segments:
                return
            _strip_trailing_spacing(current_row)
            if current_row.segments:
                rows.append(current_row)
                max_row_width_seen = max(max_row_width_seen, current_row.width)
            current_row = TextRow()
            current_width = 0

        for seg in raw_segments:
            if seg.type == 'spacing':
                if current_width + seg.width <= self.max_content_width:
                    current_row.segments.append(seg)
                    current_width += seg.width
                    current_row.width = current_width
                else:
                    settle_row()
                continue

            if seg.type in ('emoji', 'gift_image'):
                if current_width + seg.width <= self.max_content_width:
                    current_row.segments.append(seg)
                    current_width += seg.width
                    current_row.width = current_width
                else:
                    settle_row()
                    current_row.segments.append(seg)
                    current_row.width = seg.width
                    current_width = seg.width
                continue

            if seg.type == 'text':
                text_content = seg.content
                text_color = seg.color
                while text_content:
                    remaining_space = self.max_content_width - current_width
                    if remaining_space <= 0:
                        settle_row()
                        continue

                    sub_len, best_w = _find_fit_len(self.fm, text_content, remaining_space)
                    if sub_len == 0:
                        if current_width == 0:
                            sub_len = 1
                            best_w = self.fm.horizontalAdvance(text_content[:1])
                        else:
                            settle_row()
                            continue

                    current_row.segments.append(RenderSegment(
                        'text', text_content[:sub_len], best_w, text_color
                    ))
                    current_row.width += best_w
                    current_width += best_w
                    text_content = text_content[sub_len:]

        settle_row()
        return rows, max_row_width_seen

    # -------------------------------------------------------------------------
    # 尺寸计算
    # -------------------------------------------------------------------------
    def _calc_dimensions(
        self, rows: list[TextRow], max_row_width_seen: int
    ) -> DanmakuLayout:
        """根据折行结果计算气泡的总宽度和高度。

        单行气泡使用半圆角（高度的一半），多行气泡使用固定圆角。
        Args:
            rows: 折行后的行列表
            max_row_width_seen: 所有行中的最大宽度
        Returns:
            完整的 DanmakuLayout 实例
        """
        total_width = max_row_width_seen + (self.style.bubble_padding_x * 2)
        num_rows = len(rows)
        height = (
            (self.style.bubble_padding_y * 2)
            + (num_rows * self.line_height)
            + ((num_rows - 1) * self.style.bubble_row_gap)
        )
        if num_rows == 1:
            radius = float(height // 2)
        else:
            radius = float(self.style.bubble_multiline_radius)

        text_ascent = self.fm.ascent()
        text_descent = self.fm.descent()
        vertical_padding = (self.line_height - text_ascent - text_descent) // 2

        return DanmakuLayout(
            rows=rows,
            total_width=total_width,
            height=height,
            padding_x=self.style.bubble_padding_x,
            padding_y=self.style.bubble_padding_y,
            line_height=self.line_height,
            row_gap=self.style.bubble_row_gap,
            radius=radius,
            text_ascent=text_ascent,
            vertical_padding=vertical_padding,
        )