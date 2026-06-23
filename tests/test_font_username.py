# test_font_username.py
"""测试当前字体是否能渲染特殊 Unicode 字符的用户名

检测原理:
    QFontMetrics.inFont() 在 PySide6 中有 bug，总是返回 True，无法判断字符是否真实存在。
    本测试改用 QRawFont.glyphIndexesForString() 查询每个字体对字符的真实字形索引：
    - 字形索引为 0 表示 .notdef（即豆腐块/方框），字体不支持该字符
    - 字形索引非 0 表示字体有真实字形
    同时结合像素分析作为辅助验证。
"""
import sys
import os

os.environ["QT_LOGGING_RULES"] = "qt.text.font.db=false;qt.qpa.fonts=false"

from PySide6.QtGui import (QGuiApplication, QFont, QFontMetrics, QFontDatabase,
                           QImage, QPainter, QColor, QRawFont)
from PySide6.QtCore import Qt


def _check_font_support(family, char, bold=False):
    """检查单个字体是否真正支持某字符（基于 QRawFont 字形索引）。

    返回 (glyph_index, raw_font_family) 或 (0, None) 表示不支持。
    """
    f = QFont(family, 25)
    if bold:
        f.setBold(True)
    raw = QRawFont.fromFont(f)
    if not raw.isValid():
        return 0, None
    indices = raw.glyphIndexesForString(char)
    if indices and indices[0] != 0:
        return indices[0], raw.familyName()
    return 0, None


def _is_tofu(char, families, bold=False):
    """判断字符在指定字体族链中是否为豆腐块。

    核心方法：用 QRawFont.glyphIndexesForString() 查询每个字体。
    只要有一个字体的字形索引非 0，就不是豆腐块。
    所有字体都返回 0 时，用像素分析做最终确认。

    返回 (is_tofu, detail, supporting_family)
    """
    # 阶段1：QRawFont 字形索引检测
    for family in families:
        glyph_idx, actual_family = _check_font_support(family, char, bold)
        if glyph_idx != 0:
            return False, f"glyph={glyph_idx} in {actual_family}", actual_family

    # 阶段2：所有显式字体都不支持，glyph=0 → 可能是豆腐块
    # 但仍需像素分析确认系统回退是否生效
    font = QFont()
    font.setFamilies(families)
    font.setPointSize(25)
    if bold:
        font.setBold(True)
    font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)

    img = _render_char_to_image(char, font, antialias=True)

    # 像素统计
    w, h = img.width(), img.height()
    img_pixels = 0
    min_x, min_y = w, h
    max_x, max_y = -1, -1
    row_pixels = [0] * h
    col_pixels = [0] * w

    for y in range(h):
        for x in range(w):
            if img.pixelColor(x, y).alpha() > 0:
                img_pixels += 1
                row_pixels[y] += 1
                col_pixels[x] += 1
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if img_pixels == 0:
        return True, "no pixels", None

    bbox_w = max_x - min_x + 1
    bbox_h = max_y - min_y + 1

    # 边框/填充分析
    border = max(1, max(bbox_w, bbox_h) // 16)
    border_pixels = 0
    interior_pixels = 0

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if img.pixelColor(x, y).alpha() > 0:
                is_border = (x - min_x < border or max_x - x < border
                             or y - min_y < border or max_y - y < border)
                if is_border:
                    border_pixels += 1
                else:
                    interior_pixels += 1

    total = border_pixels + interior_pixels
    border_ratio = border_pixels / total if total > 0 else 0
    fill_ratio = total / (bbox_w * bbox_h) if bbox_w * bbox_h > 0 else 0

    # 行/列投影变异系数
    active_rows = [row_pixels[y] for y in range(min_y, max_y + 1) if row_pixels[y] > 0]
    active_cols = [col_pixels[x] for x in range(min_x, max_x + 1) if col_pixels[x] > 0]

    row_cv = col_cv = 0.0
    if len(active_rows) >= 3:
        avg = sum(active_rows) / len(active_rows)
        if avg > 0:
            row_cv = (sum((v - avg) ** 2 for v in active_rows) / len(active_rows)) ** 0.5 / avg
    if len(active_cols) >= 3:
        avg = sum(active_cols) / len(active_cols)
        if avg > 0:
            col_cv = (sum((v - avg) ** 2 for v in active_cols) / len(active_cols)) ** 0.5 / avg

    # 判定：glyph=0 时，像素分析作为辅助
    # 空心框（细边框）：border_ratio 高 + fill_ratio 低
    is_outline = border_ratio > 0.50 and fill_ratio < 0.40
    # 实心方块：fill 高 + 行列投影均匀（CV 低）+ 近似正方形
    aspect = bbox_w / bbox_h if bbox_h > 0 else 1
    is_filled = (fill_ratio > 0.6 and row_cv < 0.25 and col_cv < 0.25
                 and 0.6 < aspect < 1.7)

    is_tofu = is_outline or is_filled

    detail = f"glyph=0 bbox={bbox_w}x{bbox_h} border={border_ratio:.0%} fill={fill_ratio:.0%}"
    if is_tofu:
        detail += f" row_cv={row_cv:.2f} col_cv={col_cv:.2f}"
    else:
        detail += f" (system fallback?)"

    return is_tofu, detail, None


def _render_char_to_image(char, font, size=48, antialias=False):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setFont(font)
    painter.setPen(QColor(0, 0, 0))
    if not antialias:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    fm = QFontMetrics(font)
    painter.drawText(0, fm.ascent(), char)
    painter.end()
    return img


def test_username_font_support():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(script_dir, "..", "assets", "fonts")
    font_map = {
        "Microsoft YaHei": "msyhbd.ttc",
        "Noto Sans Tai Tham": "NotoSansTaiTham-Regular.ttf",
        "Segoe UI Emoji": "seguiemj.ttf",
        "Segoe UI Symbol": "seguisym.ttf",
    }
    for family, filename in font_map.items():
        path = os.path.normpath(os.path.join(font_dir, filename))
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
            print(f"  [加载] {family} ← {path}")
        else:
            print(f"  [跳过] {family} ← {path} (文件不存在)")

    families = ["Microsoft YaHei", "Microsoft Tai Le","Microsoft Himalaya",
                    "Noto Sans Tai Tham", "Leelawadee UI", "Segoe UI Emoji", "Segoe UI Symbol"]
    font = QFont()
    font.setFamilies(families)
    font.setPointSize(25)
    font.setBold(True)
    font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)
    fm = QFontMetrics(font)

    # username = "ᥫᩣ𓂃𓈒𓏸"
    username = "ℳ๓乐莹๓ོ"
    print("=" * 60)
    print("字体渲染能力测试")
    print("=" * 60)
    print(f"有效字体族: {families}")
    print(f"字体大小: {font.pointSize()}pt")
    print(f"测试用户名: {username}")
    print(f"用户名长度: {len(username)} 个字符")
    print()

    # 先打印每个字体对各字符的字形索引（诊断用）
    print("--- QRawFont 字形索引诊断 ---")
    header = f"{'字符':<6} {'U+':<8}"
    for fam in families:
        header += f" {fam[:12]:<14}"
    print(header)
    for char in username:
        row = f"{char!r:<6} U+{ord(char):04X}  "
        for fam in families:
            idx, _ = _check_font_support(fam, char, bold=True)
            row += f" {idx:<14}"
        print(row)
    print()

    tofu_chars = []
    glyph_zero_chars = []
    debug_dir = os.path.join(script_dir, "font_debug")
    os.makedirs(debug_dir, exist_ok=True)
    for i, char in enumerate(username):
        codepoint = ord(char)
        char_name = f"U+{codepoint:04X}"
        advance = fm.horizontalAdvance(char)

        in_primary = fm.inFont(char)

        is_tofu_glyph, tofu_detail, supporting = _is_tofu(char, families, bold=True)

        # 保存检测画面
        _render_char_to_image(char, font, antialias=True).save(
            os.path.join(debug_dir, f"char_{i}_{codepoint:04X}.png"))

        if is_tofu_glyph:
            status = "❌ 豆腐块"
            tofu_chars.append(char)
        elif supporting:
            status = "✅ 正常渲染"
        else:
            status = "⚠️ glyph=0"
            glyph_zero_chars.append(char)

        print(f"  [{i}] {char!r}  {char_name}  advance={advance:>4}px  "
              f"inFont={in_primary}  {status}  ({tofu_detail})")

    print()

    # 模拟实际弹幕前缀: "用户名: "
    prefix = f"{username}: "
    prefix_width = fm.horizontalAdvance(prefix)
    print(f"弹幕前缀文本: '{prefix}'")
    print(f"前缀宽度: {prefix_width}px")
    print(f"对比: 正常中文前缀 '用户名: ' 宽度 = {fm.horizontalAdvance('用户名: ')}px")
    print()

    # 渲染到图片
    w, h = 600, 60
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setFont(font)

    # 画背景
    painter.setBrush(QColor(20, 20, 20, 150))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, w, h, 14, 14)

    # 画用户名（浅蓝色）
    painter.setPen(QColor(135, 206, 250))
    painter.drawText(14, 14 + fm.ascent(), prefix)

    # 画弹幕文本（白色）
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(14 + prefix_width, 14 + fm.ascent(), "小九下个月就满一岁了")
    painter.end()
    out_path = os.path.join(script_dir, "font_test_username.png")
    img.save(out_path)
    print(f"渲染结果已保存到: {out_path}")
    print()

    # 总结
    print("=" * 60)
    if not tofu_chars and not glyph_zero_chars:
        print("✅ 结论: 所有字符在显式字体中均有真实字形")
    elif tofu_chars:
        tofu_str = " ".join(repr(c) for c in tofu_chars)
        print(f"❌ 结论: 检测到 {len(tofu_chars)} 个豆腐块字符: {tofu_str}")
        print("   这些字符在当前字体下无法渲染，将显示为方框")
    else:
        print("✅ 结论: 未检测到豆腐块")

    if glyph_zero_chars:
        gz_str = " ".join(repr(c) for c in glyph_zero_chars)
        print(f"⚠️  警告: {len(glyph_zero_chars)} 个字符在显式字体中字形索引为 0: {gz_str}")
        print("   这些字符可能依赖系统回退字体，建议检查实际渲染效果")
        print()
        print("--- 系统回退字体检查 ---")
        db = QFontDatabase()
        for char in set(glyph_zero_chars):
            sys_fonts = []
            for fam in db.families():
                if fam in families:
                    continue
                idx, _ = _check_font_support(fam, char, bold=True)
                if idx != 0:
                    sys_fonts.append(f"{fam}(glyph={idx})")
            if sys_fonts:
                print(f"  {char!r} (U+{ord(char):04X}): 系统字体支持 → {', '.join(sys_fonts[:5])}"
                      f"{'...' if len(sys_fonts) > 5 else ''}")
            else:
                print(f"  {char!r} (U+{ord(char):04X}): 系统中未找到任何支持字体 ❌ 确定为豆腐块")


if __name__ == "__main__":
    test_username_font_support()