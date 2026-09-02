"""validation.py 单元测试

测试 validate_video_input、validate_xml_input、validate_output_path
的全部分支路径。
"""

import pytest

from danmakupro.utils.validation import (
    validate_video_input,
    validate_xml_input,
    validate_output_path,
    SUPPORTED_VIDEO_EXTS,
    SUPPORTED_OUTPUT_EXTS,
)
from danmakupro.errors import InputError


# =============================================================================
# validate_video_input
# =============================================================================


class TestValidateVideoInput:
    """测试 validate_video_input：视频文件存在性、类型和格式校验。"""

    def test_valid_mp4(self, tmp_path):
        """存在且格式支持的 .mp4 文件应通过校验。"""
        p = tmp_path / "test.mp4"
        p.touch()
        validate_video_input(str(p))

    def test_valid_flv(self, tmp_path):
        """存在且格式支持的 .flv 文件应通过校验。"""
        p = tmp_path / "test.flv"
        p.touch()
        validate_video_input(str(p))

    def test_file_not_exist(self):
        """不存在的文件应抛出 InputError。"""
        with pytest.raises(InputError, match="视频文件不存在"):
            validate_video_input("/nonexistent/path/video.mp4")

    def test_path_is_directory(self, tmp_path):
        """路径是目录时应抛出 InputError。"""
        with pytest.raises(InputError, match="视频路径是目录"):
            validate_video_input(str(tmp_path))

    def test_unsupported_extension(self, tmp_path):
        """不支持的扩展名应抛出 InputError。"""
        p = tmp_path / "test.txt"
        p.touch()
        with pytest.raises(InputError, match="不支持的视频格式"):
            validate_video_input(str(p))

    def test_all_supported_extensions(self, tmp_path):
        """所有 SUPPORTED_VIDEO_EXTS 都应通过校验。"""
        for ext in SUPPORTED_VIDEO_EXTS:
            p = tmp_path / f"test{ext}"
            p.touch()
            validate_video_input(str(p))

    def test_uppercase_extension(self, tmp_path):
        """大写扩展名应被归一化处理（.MP4 → .mp4）。"""
        p = tmp_path / "test.MP4"
        p.touch()
        validate_video_input(str(p))


# =============================================================================
# validate_xml_input
# =============================================================================


class TestValidateXmlInput:
    """测试 validate_xml_input：XML 文件校验。"""

    def test_valid_xml(self, tmp_path):
        """存在且扩展名为 .xml 的文件应通过校验。"""
        p = tmp_path / "danmaku.xml"
        p.touch()
        validate_xml_input(str(p))

    def test_file_not_exist(self):
        """不存在的文件应抛出 InputError。"""
        with pytest.raises(InputError, match="弹幕 XML 文件不存在"):
            validate_xml_input("/nonexistent/path/danmaku.xml")

    def test_path_is_directory(self, tmp_path):
        """路径是目录时应抛出 InputError。"""
        with pytest.raises(InputError, match="弹幕 XML 路径是目录"):
            validate_xml_input(str(tmp_path))

    def test_not_xml_extension(self, tmp_path):
        """非 .xml 扩展名应抛出 InputError。"""
        p = tmp_path / "danmaku.json"
        p.touch()
        with pytest.raises(InputError, match="不支持的弹幕格式"):
            validate_xml_input(str(p))

    def test_uppercase_xml(self, tmp_path):
        """大写 .XML 扩展名应通过校验。"""
        p = tmp_path / "danmaku.XML"
        p.touch()
        validate_xml_input(str(p))


# =============================================================================
# validate_output_path
# =============================================================================


class TestValidateOutputPath:
    """测试 validate_output_path：输出路径校验。"""

    def test_valid_output(self, tmp_path):
        """输出目录存在且格式支持时应通过校验。"""
        p = tmp_path / "output.mp4"
        validate_output_path(str(p))

    def test_parent_dir_not_exist(self):
        """父目录不存在时应抛出 InputError。"""
        with pytest.raises(InputError, match="输出目录不存在"):
            validate_output_path("/nonexistent/dir/output.mp4")

    def test_unsupported_extension(self, tmp_path):
        """不支持的扩展名应抛出 InputError。"""
        p = tmp_path / "output.txt"
        with pytest.raises(InputError, match="不支持的输出格式"):
            validate_output_path(str(p))

    def test_file_exists_no_force(self, tmp_path):
        """文件已存在且未指定 force 时应抛出 InputError。"""
        p = tmp_path / "output.mp4"
        p.touch()
        with pytest.raises(InputError, match="输出文件已存在"):
            validate_output_path(str(p), force=False)

    def test_file_exists_force(self, tmp_path):
        """文件已存在且指定 force 时应通过校验（覆盖警告不抛异常）。"""
        p = tmp_path / "output.mp4"
        p.touch()
        validate_output_path(str(p), force=True)

    def test_all_supported_output_extensions(self, tmp_path):
        """所有 SUPPORTED_OUTPUT_EXTS 都应通过校验。"""
        for ext in SUPPORTED_OUTPUT_EXTS:
            p = tmp_path / f"output{ext}"
            validate_output_path(str(p))

    def test_file_not_exists_no_error(self, tmp_path):
        """文件不存在时不应报错。"""
        p = tmp_path / "new_output.mp4"
        validate_output_path(str(p))