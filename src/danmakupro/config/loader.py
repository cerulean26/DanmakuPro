"""配置加载器

负责从 YAML 文件加载配置。
"""

from __future__ import annotations

import typing
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any
import yaml
from loguru import logger

from .models import DanmakuConfig, DEFAULT_CONFIG


# =============================================================================
# 辅助函数
# =============================================================================

def _is_dataclass_type(tp: Any) -> bool:
    """检查类型是否为 dataclass"""
    if isinstance(tp, str):
        return False
    if typing.get_origin(tp) is not None:
        return False
    return is_dataclass(tp)


# =============================================================================
# 配置搜索路径
# =============================================================================

def _config_priority_paths(config_path: str | Path | None = None) -> list[Path]:
    """按优先级返回配置文件候选路径（多选一，不合并）。

    优先级: --config 指定 > 当前目录 > 用户目录
    调用方应取第一个存在的文件，忽略后续路径。
    """
    paths: list[Path] = []
    if config_path is not None:
        paths.append(Path(config_path))
    paths.append(Path("danmakupro.yaml"))
    paths.append(Path.home() / "danmakupro.yaml")
    return paths


# =============================================================================
# 配置转换
# =============================================================================

def _warn_type_mismatch(value: Any, field_path: str) -> None:
    """对 YAML 解析后常见的类型陷阱发出预警。

    YAML 有一些反直觉的隐式转换（如 no → False, yes → True），
    此函数仅对明显可疑的类型不匹配发出警告，不做强制拦截。
    实际值域校验由 dataclass 的 __post_init__ 负责。
    """
    # YAML 把 "no"/"yes"/"on"/"off" 解析为 bool 是常见坑
    if isinstance(value, bool):
        logger.warning(
            "{}: 值为布尔 {}，如果你本意是字符串，请加引号包裹（如 \"yes\"）",
            field_path, value,
        )
    # 纯数字字符串被解析为 int/float 通常符合预期，不警告
    # 其他类型不匹配交给业务逻辑自然报错，此处不做强制校验


def _dict_to_config(data: dict, config_cls: type[Any]) -> Any:
    """递归将字典转换为 dataclass 实例"""
    type_hints = typing.get_type_hints(config_cls)
    field_names = {f.name for f in fields(config_cls)}
    kwargs = {}
    for f in fields(config_cls):
        if f.name not in data:
            continue
        value = data[f.name]
        field_type = type_hints.get(f.name, f.type)
        if _is_dataclass_type(field_type):
            kwargs[f.name] = _dict_to_config(value, typing.cast(type[Any], field_type))
        else:
            _warn_type_mismatch(value, f"{config_cls.__name__}.{f.name}")
            kwargs[f.name] = value

    unknown_keys = set(data) - field_names
    if unknown_keys:
        logger.warning(
            "配置文件包含未知字段将被忽略: {}",
            ", ".join(sorted(unknown_keys)),
        )
    return config_cls(**kwargs)


def load_config(config_path: str | Path | None = None) -> DanmakuConfig:
    """加载配置文件。

    按优先级查找：--config 指定 > 当前目录 > 用户目录。
    取第一个存在的文件，不做多文件合并。未找到时返回默认配置。

    Args:
        config_path: 配置文件路径，为 None 时自动搜索

    Returns:
        DanmakuConfig 实例
    """
    user_data: dict[str, Any] = {}
    for path in _config_priority_paths(config_path):
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                logger.error("配置文件解析失败: {} - {}", path, e)
                raise
            if data is not None:
                user_data = data
                break

    if user_data:
        return _dict_to_config(user_data, DanmakuConfig)
    return DEFAULT_CONFIG