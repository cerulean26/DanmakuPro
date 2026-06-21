"""通用工具函数"""

import re

from .config import EMOJI_PATTERN


def has_emoji(text: str) -> bool:
    """检测文本是否包含 Emoji 标记。

    Args:
        text: 弹幕文本

    Returns:
        True 如果文本中包含 [emoji_name] 格式的标记
    """
    return bool(EMOJI_PATTERN.search(text))


def extract_emoji_names(text: str) -> list[str]:
    """提取文本中所有 Emoji 名称。

    Args:
        text: 弹幕文本

    Returns:
        Emoji 名称列表（去方括号），按出现顺序排列
    """
    return [m.group(1) for m in EMOJI_PATTERN.finditer(text)]
