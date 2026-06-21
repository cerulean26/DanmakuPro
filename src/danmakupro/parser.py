"""XML 弹幕解析模块

从 Bilibili 格式的 XML 文件中解析弹幕事件和礼物事件。
"""

from lxml import etree  # type: ignore
from loguru import logger

from .config import MIN_GIFT_PRICE
from .models import DanmakuEvent


def parse_xml(xml_path: str) -> list[DanmakuEvent]:
    """解析 XML 弹幕文件，提取所有弹幕和礼物事件。

    支持两种事件类型：
        - <d> 标签：普通弹幕，包含时间戳、用户名、文本内容
        - <gift> 标签：礼物消息，包含时间戳、用户、礼物名、数量、价格

    使用 iterparse 流式解析以节省内存，适合大文件。

    Args:
        xml_path: XML 文件路径

    Returns:
        按时间排序的弹幕事件列表
    """
    logger.info(f"[1/5] 正在解析 XML 数据: {xml_path}")
    events: list[DanmakuEvent] = []

    for _event, elem in etree.iterparse(
        xml_path, events=('end',), tag=('d', 'gift'),
        recover=True, encoding='utf-8',
    ):
        if elem.tag == 'd':
            # 普通弹幕：<d p="时间,...">文本</d>
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
            # 礼物消息：<gift ts="时间" user="用户" giftname="礼物名" ...>
            try:
                time_val = float(elem.get('ts', 0))
                user = elem.get('user') or elem.get('uid') or "匿名"
                gift_name = elem.get('giftname', '礼物')
                gift_count_val = int(elem.get('giftcount', 1))
                raw_price = elem.get('price') or "0"
                gift_price = float(raw_price) / 1000
                if gift_price >= MIN_GIFT_PRICE:
                    events.append(DanmakuEvent(
                        time=time_val, user=user, text="", is_gift=True,
                        gift_name=gift_name, gift_count=gift_count_val,
                    ))
            except (ValueError, TypeError):
                logger.debug(f"礼物解析失败: {dict(elem.attrib)}")

        # 清理已解析的元素以释放内存（流式解析关键步骤）
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]

    events.sort(key=lambda x: x.time)
    logger.info(f"XML 解析完成 | 总事件数={len(events)}")
    return events