"""扫描 test.xml 中所有用户名，检查字体覆盖情况"""
import re
import sys
import os

import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont, QRawFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
XML_PATH = os.path.join(PROJECT_ROOT, "source", "test.xml")

app = QGuiApplication.instance() or QGuiApplication(sys.argv)

FONT_DIR = os.path.join(PROJECT_ROOT, "assets", "fonts")
FONT_MAP = {
    "Microsoft YaHei": "msyh.ttc",
    "Noto Sans CJK SC": "NotoSansCJKsc-Regular.otf",
    "Segoe UI": "segoeui.ttf",
    "Segoe UI Emoji": "seguiemj.ttf",
    "Segoe UI Symbol": "SegoeUISymbol.ttf",
    "Noto Sans Symbols 2": "NotoSansSymbols2-Regular.ttf",
    "Tahoma": "tahoma.ttf",
    "Nirmala UI": "Nirmala.ttc",
    "Microsoft Himalaya": "himalaya.ttf",
    "Leelawadee UI": "LeelawUI.ttf",
    "Microsoft Tai Le": "taile.ttf",
    "Microsoft Yi Baiti": "msyi.ttf",
    "Segoe UI Historic": "seguihis.ttf",
    "Malgun Gothic": "malgun.ttf",
    "Myanmar Text": "mmrtext.ttf",
    "Gadugi": "gadugi.ttf",
    "Noto Sans Canadian Aboriginal": "NotoSansCanadianAboriginal-Regular.ttf",
    "Noto Sans New Tai Lue": "NotoSansNewTaiLue-Regular.ttf",
    "Noto Sans Limbu": "NotoSansLimbu-Regular.ttf",
    "Noto Sans Tai Viet": "NotoSansTaiViet-Regular.ttf",
    "Noto Sans Tagalog": "NotoSansTagalog-Regular.ttf",
    "Noto Sans Tagbanwa": "NotoSansTagbanwa-Regular.ttf",
    "Noto Sans Sundanese": "NotoSansSundanese-Regular.ttf",
    "Noto Sans Lepcha": "NotoSansLepcha-Regular.ttf",
    "Noto Sans Cham": "NotoSansCham-Regular.ttf",
    "Noto Sans Vai": "NotoSansVai-Regular.ttf",
    "Noto Sans Kayah Li": "NotoSansKayahLi-Regular.ttf",
    "Noto Sans Soyombo": "NotoSansSoyombo-Regular.ttf",
    "Noto Sans Samaritan": "NotoSansSamaritan-Regular.ttf",
    "Noto Sans Mandaic": "NotoSansMandaic-Regular.ttf",
    "Noto Sans Math": "NotoSansMath-Regular.ttf",
    "Noto Sans Tai Tham": "NotoSansTaiTham-Regular.ttf",
    "Noto Sans Balinese": "NotoSansBalinese-Regular.ttf",
    "Noto Sans Batak": "NotoSansBatak-Regular.ttf",
    "Noto Sans Javanese": "NotoSansJavanese-Regular.ttf",
}
FAMILIES = list(FONT_MAP.keys())

for family, filename in FONT_MAP.items():
    path = os.path.normpath(os.path.join(FONT_DIR, filename))
    if os.path.exists(path):
        QFontDatabase.addApplicationFont(path)

font = QFont()
font.setFamilies(FAMILIES)
font.setPointSize(25)
font.setBold(True)

raw_fonts = []
for family in FAMILIES:
    f = QFont(family, 25, QFont.Weight.Bold)
    raw_fonts.append(QRawFont.fromFont(f))

def char_diagnosis(c):
    """返回 (支持的字体名, glyph_index) 或 None"""
    cp = ord(c)
    for i, rf in enumerate(raw_fonts):
        indexes = rf.glyphIndexesForString(c)
        if len(indexes) > 0 and indexes[0] != 0:
            return FAMILIES[i], indexes[0]
    return None, None

with open(XML_PATH, "r", encoding="utf-8") as f:
    content = f.read()

usernames = set(re.findall(r'user="([^"]*)"', content))
print(f"共 {len(usernames)} 个唯一用户名\n")

problematic = []
all_missing_chars = {}

for name in sorted(usernames):
    issues = []
    for c in name:
        cp = ord(c)
        if cp == 0x20:
            continue
        fm, idx = char_diagnosis(c)
        if idx is None or idx == 0:
            issues.append(f"U+{cp:04X} {c}")
            all_missing_chars[c] = cp
    if issues:
        problematic.append((name, issues))

if problematic:
    print(f"⚠️  {len(problematic)} 个用户名存在缺失字符:\n")
    for name, issues in problematic:
        print(f"  {name}")
        for iss in issues:
            print(f"    └─ {iss}")
else:
    print("✅ 所有用户名字符均可渲染")

if all_missing_chars:
    print(f"\n缺失字符汇总 ({len(all_missing_chars)} 个):")
    for c, cp in sorted(all_missing_chars.items(), key=lambda x: x[1]):
        try:
            name = unicodedata.name(c, "")
        except:
            name = ""
        print(f"  U+{cp:04X} '{c}' ({name})")