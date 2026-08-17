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

def _config_search_paths(config_path: str | Path | None = None) -> list[Path]:
    """生成配置文件的搜索路径列表"""
    paths: list[Path] = []
    if config_path is not None:
        paths.append(Path(config_path))
    paths.append(Path("danmakupro.yaml"))
    user_dir = Path.home() / "danmakupro.yaml"
    paths.append(user_dir)
    return paths


# =============================================================================
# 配置转换
# =============================================================================

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

    按优先级搜索配置文件：指定路径 > 当前目录 > 用户目录。
    未找到配置文件时返回默认配置。

    Args:
        config_path: 配置文件路径，为 None 时自动搜索

    Returns:
        DanmakuConfig 实例
    """
    user_data: dict[str, Any] = {}
    for path in _config_search_paths(config_path):
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