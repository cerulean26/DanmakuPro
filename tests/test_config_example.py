"""随包配置模板与内置默认值的一致性。

`src/danmakupro/danmakupro.example.yaml` 是用户自定义配置的起点，
它列出的值必须**逐字段等于**内置默认值，否则会出现两种都不会报错的
矛盾：pip 装完直接跑得到一套值，照着模板写配置又得到另一套值。

本模块是这条约束的唯一守卫，改动任一侧都会立刻变红。
"""
from __future__ import annotations

from dataclasses import fields

import pytest
import yaml

from danmakupro.cli import EXAMPLE_CONFIG
from danmakupro.config.loader import _dict_to_config
from danmakupro.config.models import (
    AnimationParams,
    DanmakuConfig,
    DEFAULT_CONFIG,
    LayoutRatio,
    LayoutStyle,
)

#: 模板中未注释掉、因而会被解析的段（encode/system 在模板里是注释示例）
SECTIONS = {
    "style": LayoutStyle,
    "ratio": LayoutRatio,
    "animation": AnimationParams,
}


@pytest.fixture(scope="module")
def example_data() -> dict:
    assert EXAMPLE_CONFIG.exists(), f"模板缺失: {EXAMPLE_CONFIG}"
    data = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "模板应解析为映射"
    return data


def test_template_is_packaged_next_to_cli():
    """模板必须位于包内：editable 安装与 wheel 安装都要能取到。"""
    assert EXAMPLE_CONFIG.name == "danmakupro.example.yaml"
    assert EXAMPLE_CONFIG.parent.name == "danmakupro"


def test_example_values_equal_builtin_defaults(example_data):
    """核心约束：模板列出的值 == 内置默认值。"""
    from_template = _dict_to_config(example_data, DanmakuConfig)
    assert from_template == DEFAULT_CONFIG


@pytest.mark.parametrize("section", sorted(SECTIONS))
def test_example_has_no_unknown_keys(example_data, section):
    """段内不得有拼错的键 —— 未知键只会被静默忽略。"""
    assert section in example_data, f"模板缺少 {section} 段"
    known = {f.name for f in fields(SECTIONS[section])}
    unknown = set(example_data[section]) - known
    assert not unknown, f"{section} 段含未知字段: {sorted(unknown)}"


@pytest.mark.parametrize("section", sorted(SECTIONS))
def test_example_lists_every_field(example_data, section):
    """模板应列全该段所有字段，避免用户不知道某个参数存在。"""
    listed = set(example_data[section])
    expected = {f.name for f in fields(SECTIONS[section])}
    assert listed == expected, f"{section} 段缺字段: {sorted(expected - listed)}"


@pytest.fixture
def log_messages():
    """收集 loguru 的日志文本（loguru 不经过标准 logging，caplog 抓不到）。"""
    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


def test_example_loads_without_warnings(example_data, log_messages):
    """解析模板不应触发任何警告。

    两类真实陷阱：段里出现拼错的键（会被静默忽略），
    以及 `yes`/`no`/`on`/`off` 这类被 YAML 解析成布尔的值。
    """
    _dict_to_config(example_data, DanmakuConfig)
    assert not [m for m in log_messages if "未知字段" in m]
    assert not [m for m in log_messages if "值为布尔" in m]
