"""检查 XML 文件中所有用户名是否可被当前字体配置渲染"""
import sys
import os
from pathlib import Path
from lxml import etree # type: ignore

os.environ["QT_LOGGING_RULES"] = "qt.text.font.db=false;qt.qpa.fonts=false"

from PySide6.QtGui import QGuiApplication, QFont, QRawFont, QFontDatabase


def load_fonts(font_dir: Path) -> None:
    font_map = {
        "Microsoft YaHei": "msyhbd.ttc",
        "Noto Sans Tai Tham": "NotoSansTaiTham-Regular.ttf",
        "Segoe UI Emoji": "seguiemj.ttf",
        "Segoe UI Symbol": "seguisym.ttf",
    }
    for family, filename in font_map.items():
        path = font_dir / filename
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def check_char(families: list[str], char: str) -> tuple[int, str]:
    for family in families:
        f = QFont(family, 25)
        f.setBold(True)
        raw = QRawFont.fromFont(f)
        if raw.isValid():
            indices = raw.glyphIndexesForString(char)
            if indices and indices[0] != 0:
                return indices[0], family
    return 0, ""


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    font_dir = project_root / "assets" / "fonts"
    xml_path = project_root / "source" / "2026-06-20 16-00-05-993 放黑豹.xml"

    if not xml_path.exists():
        print(f"XML 文件不存在: {xml_path}")
        sys.exit(1)

    load_fonts(font_dir)

    families = [
        "Microsoft YaHei", "Microsoft Himalaya", "Microsoft Tai Le",
        "Noto Sans Tai Tham", "Leelawadee UI", "Malgun Gothic",
        "Segoe UI", "Segoe UI Emoji", "Segoe UI Symbol",
    ]

    tree = etree.parse(str(xml_path))
    root = tree.getroot()

    usernames: set[str] = set()
    for el in root.iter():
        user = el.get("user")
        if user:
            usernames.add(user)

    print(f"XML 文件: {xml_path.name}")
    print(f"唯一用户名: {len(usernames)} 个")
    print(f"字体链: {families}")
    print()

    all_chars: set[str] = set()
    for name in usernames:
        all_chars.update(name)
    print(f"唯一字符: {len(all_chars)} 个")
    print()

    unsupported: dict[str, list[str]] = {}
    for char in sorted(all_chars):
        glyph_idx, supporting_family = check_char(families, char)
        if glyph_idx == 0:
            codepoint = f"U+{ord(char):04X}"
            unsupported.setdefault(codepoint, []).append(char)

    if unsupported:
        print("=" * 60)
        print(f"未覆盖字符: {len(unsupported)} 个")
        print("=" * 60)
        for cp, chars in unsupported.items():
            print(f"  {cp}  {chars[0]!r}  ({len(chars)} 次出现)")
        print()

        affected_users: set[str] = set()
        for name in usernames:
            for char in name:
                if check_char(families, char)[0] == 0:
                    affected_users.add(name)
                    break

        print(f"受影响用户名: {len(affected_users)} 个")
        for u in sorted(affected_users)[:20]:
            bad_chars = [c for c in u if check_char(families, c)[0] == 0]
            print(f"  {u}  →  缺失字符: {''.join(bad_chars)!r}")
        if len(affected_users) > 20:
            print(f"  ... 还有 {len(affected_users) - 20} 个用户名")
    else:
        print("✅ 所有字符均被字体链覆盖，无渲染问题")


if __name__ == "__main__":
    main()