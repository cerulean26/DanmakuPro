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

from ..errors import ConfigError
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

    按优先级查找：--config 指定 > 当前目录 > 用户目录。
    取第一个存在的文件，不做多文件合并。未找到时返回默认配置。

    无论命中与否都会在日志中说明配置来源 —— 配置随当前工作目录变化，
    若无声生效，用户很难察觉自己跑的是哪一份配置。

    Args:
        config_path: 配置文件路径，为 None 时自动搜索

    Returns:
        DanmakuConfig 实例

    Raises:
        ConfigError: 文件存在但无法解析，或字段取值非法。
    """
    user_data: dict[str, Any] = {}
    loaded_from: Path | None = None
    for idx, path in enumerate(_config_priority_paths(config_path)):
        # 显式指定的路径不存在时给出警告：否则 `-c typo.yaml` 会悄悄
        # 回退到当前目录/用户目录，用户以为自己指定的配置生效了。
        if idx == 0 and config_path is not None and not path.exists():
            logger.warning("指定的配置文件不存在: {}（继续查找默认位置）", path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise ConfigError(f"配置文件解析失败: {path} - {e}") from e
            if data is not None:
                user_data = data
                loaded_from = path
                break

    if user_data:
        assert loaded_from is not None
        if not isinstance(user_data, dict):
            raise ConfigError(f"配置文件顶层必须是键值映射: {loaded_from}")
        logger.info("已加载配置文件: {}", loaded_from.resolve())
        try:
            return _dict_to_config(user_data, DanmakuConfig)
        except (TypeError, ValueError) as e:
            raise ConfigError(f"配置文件字段非法: {loaded_from} - {e}") from e
    logger.info("未找到配置文件，使用内置默认值")
    return DEFAULT_CONFIG
