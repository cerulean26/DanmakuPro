"""parser.py 单元测试

测试 XML 弹幕解析的各种场景，包括正常解析、异常分支和边界条件。
"""

import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication

from danmakupro.parser import parse_xml
from danmakupro.models import DanmakuEvent
from danmakupro.config import MIN_GIFT_PRICE


@pytest.fixture(scope="session")
def qapp():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    yield app


def _write_xml(tmp_path: Path, content: str) -> str:
    xml_file = tmp_path / "test.xml"
    xml_file.write_text(content, encoding="utf-8")
    return str(xml_file)


# =============================================================================
# 正常解析
# =============================================================================


class TestParseDanmaku:
    """测试 <d> 标签（普通弹幕）解析"""

    def test_single_danmaku(self, tmp_path):
        xml = '<i><d p="1.5,1,25,16777215,1234567890,0,user1,0" user="user1">你好</d></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 1
        assert events[0].time == 1.5
        assert events[0].user == "user1"
        assert events[0].text == "你好"
        assert not events[0].is_gift

    def test_danmaku_with_uid_attribute(self, tmp_path):
        xml = '<i><d p="2.0,1,25,16777215,0,0,0,0" uid="user2">世界</d></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 1
        assert events[0].user == "user2"

    def test_danmaku_no_user_defaults_anonymous(self, tmp_path):
        xml = '<i><d p="3.0,1,25,16777215,0,0,0,0">无用户</d></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert events[0].user == "匿名"

    def test_danmaku_empty_text(self, tmp_path):
        xml = '<i><d p="4.0,1,25,16777215,0,0,0,0"></d></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 1
        assert events[0].text == ""

    def test_multiple_danmakus_sorted_by_time(self, tmp_path):
        xml = """<i>
            <d p="5.0,1,25,16777215,0,0,a,0">第五秒</d>
            <d p="1.0,1,25,16777215,0,0,b,0">第一秒</d>
            <d p="3.0,1,25,16777215,0,0,c,0">第三秒</d>
        </i>"""
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 3
        assert [e.time for e in events] == [1.0, 3.0, 5.0]


# =============================================================================
# 礼物解析
# =============================================================================


class TestParseGift:
    """测试 <gift> 标签解析"""

    def test_gift_above_min_price(self, tmp_path):
        price_cents = int(MIN_GIFT_PRICE * 1000)
        xml = f"""<i><gift ts="1.0" user="user1" giftname="火箭"
                   giftcount="2" price="{price_cents}"/></i>"""
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 1
        assert events[0].is_gift
        assert events[0].gift_name == "火箭"
        assert events[0].gift_count == 2

    def test_gift_below_min_price_filtered(self, tmp_path):
        price_cents = int((MIN_GIFT_PRICE - 1) * 1000)
        xml = f"""<i><gift ts="1.0" user="user1" giftname="小花"
                   giftcount="1" price="{price_cents}"/></i>"""
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 0

    def test_gift_no_price_defaults_zero(self, tmp_path):
        xml = '<i><gift ts="2.0" user="user1" giftname="小花" giftcount="1"/></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 0

    def test_gift_no_user_defaults_anonymous(self, tmp_path):
        price_cents = int(MIN_GIFT_PRICE * 1000)
        xml = f"""<i><gift ts="1.0" giftname="火箭"
                   giftcount="1" price="{price_cents}"/></i>"""
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert events[0].user == "匿名"

    def test_gift_no_giftname_defaults(self, tmp_path):
        price_cents = int(MIN_GIFT_PRICE * 1000)
        xml = f"""<i><gift ts="1.0" user="user1"
                   giftcount="1" price="{price_cents}"/></i>"""
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert events[0].gift_name == "礼物"


# =============================================================================
# 异常分支
# =============================================================================


class TestParseMalformed:
    """测试畸形 XML 的容错处理"""

    def test_danmaku_missing_p_attr(self, tmp_path):
        xml = '<i><d>没有 p 属性</d></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 0

    def test_danmaku_invalid_p_attr(self, tmp_path):
        xml = '<i><d p="invalid_p_attr">无效 p</d></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 0

    def test_gift_invalid_ts(self, tmp_path):
        xml = '<i><gift ts="abc" user="u" giftname="g" giftcount="1" price="10000"/></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 0

    def test_gift_invalid_price(self, tmp_path):
        xml = '<i><gift ts="1.0" user="u" giftname="g" giftcount="1" price="abc"/></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 0

    def test_empty_xml(self, tmp_path):
        xml = "<i></i>"
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 0

    def test_other_tags_ignored(self, tmp_path):
        xml = '<i><sc ts="1.0" user="u">Super Chat</sc></i>'
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 0


# =============================================================================
# 混合场景
# =============================================================================


class TestParseMixed:
    """测试弹幕和礼物混合解析"""

    def test_danmaku_and_gift_mixed(self, tmp_path):
        price_cents = int(MIN_GIFT_PRICE * 1000)
        xml = f"""<i>
            <d p="1.0,1,25,16777215,0,0,a,0">弹幕1</d>
            <gift ts="2.0" user="b" giftname="火箭" giftcount="1" price="{price_cents}"/>
            <d p="3.0,1,25,16777215,0,0,c,0">弹幕2</d>
        </i>"""
        path = _write_xml(tmp_path, xml)
        events = parse_xml(path)
        assert len(events) == 3
        assert not events[0].is_gift
        assert events[1].is_gift
        assert not events[2].is_gift
        assert [e.time for e in events] == [1.0, 2.0, 3.0]