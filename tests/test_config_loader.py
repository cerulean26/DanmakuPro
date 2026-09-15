import pytest
import yaml
from danmakupro.config.loader import (
    _is_dataclass_type, _warn_type_mismatch, _dict_to_config,
    _config_priority_paths, load_config,
)
from danmakupro.config.models import DanmakuConfig, AnimationParams, LayoutStyle, DEFAULT_CONFIG


# =============================================================================
# _is_dataclass_type
# =============================================================================

class TestIsDataclassType:

    def test_dataclass_returns_true(self):
        assert _is_dataclass_type(AnimationParams) is True

    def test_builtin_returns_false(self):
        assert _is_dataclass_type(int) is False
        assert _is_dataclass_type(str) is False
        assert _is_dataclass_type(float) is False

    def test_string_returns_false(self):
        assert _is_dataclass_type("AnimationConfig") is False


# =============================================================================
# _warn_type_mismatch
# =============================================================================

class TestWarnTypeMismatch:

    def test_bool_does_not_raise(self):
        _warn_type_mismatch(True, "system.enabled")
        _warn_type_mismatch(False, "style.fade_out")

    def test_non_bool_does_not_raise(self):
        _warn_type_mismatch(42, "style.font_size")
        _warn_type_mismatch("hello", "style.font_name")
        _warn_type_mismatch(3.14, "animation.speed")
        _warn_type_mismatch(None, "system.optional")


# =============================================================================
# _config_priority_paths
# =============================================================================

class TestConfigPriorityPaths:

    def test_no_arg_returns_two_paths(self):
        paths = _config_priority_paths()
        assert len(paths) == 2

    def test_with_arg_returns_three_paths(self):
        paths = _config_priority_paths("my_config.yaml")
        assert len(paths) == 3
        assert paths[0].name == "my_config.yaml"


# =============================================================================
# _dict_to_config
# =============================================================================

class TestDictToConfig:

    def test_returns_default_on_empty(self):
        cfg = _dict_to_config({}, DanmakuConfig)
        assert isinstance(cfg, DanmakuConfig)

    def test_scalar_override(self):
        cfg = _dict_to_config({"font_size": 24}, LayoutStyle)
        assert cfg.font_size == 24

    def test_nested_override(self):
        data = {
            "style": {"font_size": 30, "danmaku_x": 50},
            "animation": {"text_damping_factor": 0.5},
        }
        cfg = _dict_to_config(data, DanmakuConfig)
        assert cfg.style.font_size == 30
        assert cfg.style.danmaku_x == 50
        assert cfg.animation.text_damping_factor == 0.5

    def test_unknown_key_no_error(self):
        cfg = _dict_to_config({"unknown_field": 123}, LayoutStyle)
        assert isinstance(cfg, LayoutStyle)


# =============================================================================
# load_config
# =============================================================================

class TestLoadConfig:

    def test_no_file_returns_default(self):
        cfg = load_config("/nonexistent/config.yaml")
        assert isinstance(cfg, DanmakuConfig)

    def test_load_from_yaml(self, tmp_path):
        yaml_path = tmp_path / "test.yaml"
        yaml_path.write_text("style:\n  font_size: 28\n", encoding="utf-8")
        cfg = load_config(str(yaml_path))
        assert cfg.style.font_size == 28

    def test_empty_yaml_returns_default(self, tmp_path):
        yaml_path = tmp_path / "empty.yaml"
        yaml_path.write_text("", encoding="utf-8")
        cfg = load_config(str(yaml_path))
        assert isinstance(cfg, DanmakuConfig)

    def test_default_when_no_file_found(self, monkeypatch, tmp_path):
        paths = [tmp_path / "nonexistent.yaml"]
        monkeypatch.setattr(
            "danmakupro.config.loader._config_priority_paths",
            lambda *a, **kw: paths,
        )
        cfg = load_config()
        assert cfg is DEFAULT_CONFIG

    def test_invalid_yaml_raises(self, tmp_path):
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text(": : :\n", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            load_config(str(yaml_path))

    def test_yaml_null_returns_default(self, tmp_path):
        yaml_path = tmp_path / "null.yaml"
        yaml_path.write_text("null\n", encoding="utf-8")
        cfg = load_config(str(yaml_path))
        assert isinstance(cfg, DanmakuConfig)


# =============================================================================
# 配置来源可见性
# =============================================================================

@pytest.fixture
def log_messages():
    """收集 loguru 的日志文本（loguru 不经过标准 logging，caplog 抓不到）。"""
    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(m.record["message"]), level="INFO")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


class TestConfigSourceVisibility:
    """配置来源必须可见。

    配置会随当前工作目录变化（`./danmakupro.yaml` 优先于用户目录），
    若不说清实际用了哪一份，用户无从判断自己的修改有没有生效。
    """

    def test_logs_absolute_path_when_loaded(self, tmp_path, log_messages):
        yaml_path = tmp_path / "cfg.yaml"
        yaml_path.write_text("style:\n  font_size: 26\n", encoding="utf-8")
        load_config(str(yaml_path))
        assert any(str(yaml_path.resolve()) in m for m in log_messages)

    def test_logs_default_when_nothing_found(self, monkeypatch, tmp_path, log_messages):
        monkeypatch.setattr(
            "danmakupro.config.loader._config_priority_paths",
            lambda *a, **kw: [tmp_path / "absent.yaml"],
        )
        cfg = load_config()
        assert cfg is DEFAULT_CONFIG
        assert any("内置默认值" in m for m in log_messages)

    def test_warns_when_explicit_path_missing(self, monkeypatch, tmp_path, log_messages):
        """`-c typo.yaml` 不应静默回退到别的配置。"""
        missing = tmp_path / "typo.yaml"
        monkeypatch.setattr(
            "danmakupro.config.loader._config_priority_paths",
            lambda *a, **kw: [missing],
        )
        load_config(str(missing))
        assert any("指定的配置文件不存在" in m for m in log_messages)

    def test_no_warning_when_auto_search_misses(self, monkeypatch, tmp_path, log_messages):
        """未显式指定时找不到文件属正常情况，不应告警。"""
        monkeypatch.setattr(
            "danmakupro.config.loader._config_priority_paths",
            lambda *a, **kw: [tmp_path / "absent.yaml"],
        )
        load_config()
        assert not [m for m in log_messages if "指定的配置文件不存在" in m]
