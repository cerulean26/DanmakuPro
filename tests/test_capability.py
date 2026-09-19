"""capability 模块单元测试：编码器可用性与硬解能力的探测。

TestCheckEncoders 从 _check_encoder 模块函数进入 —— 该函数仅薄封装
capability.probe_encoder_available，用例真正锁的是两段判据（列编码器、
lavfi 空源试编）。
"""

import subprocess
from unittest.mock import patch, MagicMock

from danmakupro.config.models import EncodeMode
from danmakupro.encode import capability
from danmakupro.encode.ffmpeg import _check_encoder


#: 仿照 ffmpeg -decoders 的输出（标题行、音频解码器行为干扰项，故意保留）
_DECODERS_OUTPUT = """\
Decoders:
 V..... = Video decoder
 V..... h264_cuvid           Nvidia CUVID H264 decoder (codec h264)
 V..... hevc_cuvid           Nvidia CUVID HEVC decoder (codec hevc)
 V....D vp9_qsv              VP9 video (Intel Quick Sync Video acceleration) (codec vp9)
 A..... mp3                  MP3 decoder (codec mp3)
"""


# =============================================================================
# 硬解清单
# =============================================================================


class TestHardwareDecodableCodecs:
    """从 ffmpeg -decoders 反推「这份 ffmpeg 能硬解哪些编码」。

    不写死「编码 → 解码器」映射，是因为可用解码器取决于 ffmpeg 的构建选项：
    移植性差一层，这里坚持从运行时拿。
    """

    def test_parses_codecs_by_hwaccel(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_DECODERS_OUTPUT)
            cuda = capability.hardware_decodable_codecs("cuda", "/usr/bin/ffmpeg", 5)
            qsv = capability.hardware_decodable_codecs("qsv", "/usr/bin/ffmpeg", 5)
        assert cuda == frozenset({"h264", "hevc"})
        assert qsv == frozenset({"vp9"})

    def test_probe_failure_returns_none(self):
        """探测失败要返回 None 而不是空集合 —— 空集合等于「什么都不支持」，
        会把所有任务一律降级到 CPU；None 才能表达「不知道，别乱降级」。
        """
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)
        ):
            assert (
                capability.hardware_decodable_codecs("cuda", "/usr/bin/ffmpeg", 5)
                is None
            )

    def test_unsupported_hwaccel_returns_none(self):
        assert (
            capability.hardware_decodable_codecs("videotoolbox", "/usr/bin/ffmpeg", 5)
            is None
        )


# =============================================================================
# _check_encoder (取代 _check_nvenc_available / _check_qsv_available)
# =============================================================================


class TestCheckEncoders:
    def test_nvenc_not_in_encoders(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="h264_amf", returncode=0)
            assert _check_encoder(EncodeMode.H264_NVENC, 5) is False

    def test_nvenc_available(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_nvenc", returncode=0),
                MagicMock(returncode=0),
            ]
            assert _check_encoder(EncodeMode.H264_NVENC, 5) is True

    def test_nvenc_test_encode_fails(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_nvenc", returncode=0),
                MagicMock(returncode=1),
            ]
            assert _check_encoder(EncodeMode.H264_NVENC, 5) is False

    def test_nvenc_file_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _check_encoder(EncodeMode.H264_NVENC, 5) is False

    def test_qsv_available(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_qsv", returncode=0),
                MagicMock(returncode=0),
            ]
            assert _check_encoder(EncodeMode.H264_QSV, 5) is True

    def test_nvenc_test_encode_timeout(self):
        """探测第二段（真实编码试探）超时要判为不可用，且不能往上抛。"""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_nvenc", returncode=0),
                subprocess.TimeoutExpired("ffmpeg", 5),
            ]
            assert _check_encoder(EncodeMode.H264_NVENC, 5) is False

    def test_qsv_not_in_encoders(self):
        """encoders 列表里没有 h264_qsv：第一段就返回，不进入试探。"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="h264_nvenc", returncode=0)
            assert _check_encoder(EncodeMode.H264_QSV, 5) is False
            assert mock_run.call_count == 1

    def test_qsv_test_encode_fails(self):
        """编码器在列表里但真实试探返回非 0（驱动缺失等）：判不可用。"""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_qsv", returncode=0),
                MagicMock(returncode=1),
            ]
            assert _check_encoder(EncodeMode.H264_QSV, 5) is False

    def test_qsv_ffmpeg_missing(self):
        """ffmpeg 不存在：直接判不可用，不抛异常打断启动流程。"""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _check_encoder(EncodeMode.H264_QSV, 5) is False

    def test_qsv_probe_timeout(self):
        """列编码器这一步超时（机器卡顿）：同样判不可用而非抛出。"""
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)
        ):
            assert _check_encoder(EncodeMode.H264_QSV, 5) is False

    def test_qsv_test_encode_timeout(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_qsv", returncode=0),
                subprocess.TimeoutExpired("ffmpeg", 5),
            ]
            assert _check_encoder(EncodeMode.H264_QSV, 5) is False
