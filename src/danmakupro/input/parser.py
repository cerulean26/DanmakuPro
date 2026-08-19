"""XML 弹幕解析器

从抖音格式的 XML 文件中解析弹幕事件。
"""

from __future__ import annotations

from lxml import etree  # type: ignore
from loguru import logger

from .event import DanmakuEvent


def parse_xml(xml_path: str, min_gift_price: float = 1.0) -> list[DanmakuEvent]:
    """解析 XML 弹幕文件

    Args:
        xml_path: XML 文件路径
        min_gift_price: 最低礼物价格过滤（单位：元）

    Returns:
        按时间排序的弹幕事件列表

    Note:
        XML 中 gift 的 price 属性单位为厘（1元=1000厘），
        解析时自动转换为元。
    """
    events: list[DanmakuEvent] = []

    for _event, elem in etree.iterparse(
        xml_path, events=('end',), tag=('d', 'gift'),
        recover=True, encoding='utf-8',
    ):
        if elem.tag == 'd':
            p_attr = elem.get('p')
            if p_attr:
                try:
                    comma_idx = p_attr.find(',')
                    time_val = float(p_attr[:comma_idx])
                    user = elem.get('user') or elem.get('uid') or "匿名"
                    text = elem.text or ""
                    events.append(DanmakuEvent(time=time_val, user=user, text=text))
                except (ValueError, IndexError):
                    logger.debug(f"弹幕解析失败: p={p_attr}")
        elif elem.tag == 'gift':
            try:
                time_val = float(elem.get('ts', 0))
                user = elem.get('user') or "匿名"
                gift_name = elem.get('giftname') or ""
                gift_count = int(elem.get('giftcount', 1))
                price = float(elem.get('price', 0)) / 1000

                if price >= min_gift_price:
                    events.append(DanmakuEvent(
                        time=time_val, user=user, text=f"{gift_name}x{gift_count}",
                        is_gift=True, gift_name=gift_name, gift_count=gift_count,
                    ))
            except (ValueError, TypeError):
                logger.debug("礼物解析失败")
        
        elem.clear()

    events.sort(key=lambda e: e.time)
    return events