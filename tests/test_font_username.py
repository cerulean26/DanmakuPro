# test_font_username.py
"""测试当前字体是否能渲染特殊 Unicode 字符的用户名"""
import sys
import os

os.environ["QT_LOGGING_RULES"] = "qt.text.font.db=false;qt.qpa.fonts=false"

from PySide6.QtGui import QGuiApplication, QFont, QFontMetrics, QFontDatabase, QImage, QPainter, QColor
from PySide6.QtCore import Qt


def test_username_font_support():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)

    # === 与 danmaku_optimized10.py 完全相同的字体配置 ===
    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(script_dir, "..", "assets", "fonts")
    font_map = {
        "Microsoft YaHei": "msyhbd.ttc",
        "Segoe UI Emoji": "seguiemj.ttf",
        "Segoe UI Symbol": "seguisym.ttf",
        "Noto Sans Tai Tham": "NotoSansTaiTham-Regular.ttf",
    }
    for family, filename in font_map.items():
        path = os.path.normpath(os.path.join(font_dir, filename))
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
            print(f"  [加载] {family} ← {path}")
        else:
            print(f"  [跳过] {family} ← {path} (文件不存在)")

    font = QFont()
    font.setFamilies(["Microsoft YaHei", "Microsoft Tai Le", "Noto Sans Tai Tham", "Segoe UI Emoji", "Segoe UI Symbol"])
    font.setPointSize(25)
    font.setBold(True)
    font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)
    fm = QFontMetrics(font)

    username = "ᥫᩣ𓂃𓈒𓏸"

    print("=" * 60)
    print("字体渲染能力测试")
    print("=" * 60)
    print(f"有效字体族: {font.families()}")
    print(f"字体大小: {font.pointSize()}pt")
    print(f"测试用户名: {username}")
    print(f"用户名长度: {len(username)} 个字符")
    print()

    # 逐个字符检查（实际渲染检测）
    all_in_font = True
    for i, char in enumerate(username):
        codepoint = ord(char)
        char_name = f"U+{codepoint:04X}"
        advance = fm.horizontalAdvance(char)

        # 实际渲染该字符到小图片，检测是否有可见像素
        pad = 4
        char_img = QImage(advance + pad * 2, fm.height() + pad * 2, QImage.Format.Format_ARGB32)
        char_img.fill(Qt.GlobalColor.transparent)
        char_painter = QPainter(char_img)
        char_painter.setFont(font)
        char_painter.setPen(QColor(255, 255, 255))
        char_painter.drawText(pad, pad + fm.ascent(), char)
        char_painter.end()

        has_glyph = False
        for y in range(char_img.height()):
            for x in range(char_img.width()):
                if char_img.pixelColor(x, y).alpha() > 0:
                    has_glyph = True
                    break
            if has_glyph:
                break

        status = "✅ 可渲染" if has_glyph else "❌ 无法渲染"
        if not has_glyph:
            all_in_font = False

        print(f"  [{i}] {char}  {char_name}  advance={advance:>4}px  {status}")
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
    painter.drawText(14 + prefix_width, 14 + fm.ascent(), "小九下个月就满一岁了 哪里小了")
    painter.end()

    out_path = "font_test_username.png"
    img.save(out_path)
    print(f"渲染结果已保存到: {out_path}")
    print()

    # 总结
    print("=" * 60)
    if all_in_font:
        print("✅ 结论: 所有字符均可渲染")
    else:
        print("❌ 结论: 存在字符无法渲染")
        print()
        print("  解决方案：添加覆盖这些 Unicode 区的字体，例如：")
        print("    • Noto Sans Egyptian Hieroglyphs  → 埃及象形文字")
        print("    • Noto Sans Tai Le               → 德宏傣文")
        print("    • Noto Sans Tai Tham             → 老傣文")
        print("  或使用 Windows 系统字体:")
        print("    • Segoe UI Historic              → 埃及象形文字 (Win10+)")
        print("=" * 60)


if __name__ == "__main__":
    test_username_font_support()