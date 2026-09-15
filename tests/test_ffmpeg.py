"""FFmpegManager 单元测试"""

from unittest.mock import patch, MagicMock

import pytest

from danmakupro.encode.ffmpeg import FFmpegManager
from danmakupro.config.models import (
    EncodeMode, SystemParams, DEFAULT_CONFIG,
)
from danmakupro.layout.params import LayerParams


@pytest.fixture
def ffmpeg_mgr():
    with patch.object(FFmpegManager, "_resolve_encode_mode"):
        mgr = FFmpegManager("test.mp4", "out.mp4", EncodeMode.CPU)
        mgr.active_pipeline = EncodeMode.CPU
        return mgr


# =============================================================================
# _resolve_encode_mode
# =============================================================================

def _bare_mgr(mode):
    """构造一个绕过 __init__ 的管理器，只填 _resolve_encode_mode 需要的属性。"""
    mgr = FFmpegManager.__new__(FFmpegManager)
    mgr.encode_mode = mode
    mgr.encode_params = DEFAULT_CONFIG.encode
    mgr.system_params = DEFAULT_CONFIG.system
    return mgr


class TestResolveEncodeMode:

    def test_ffmpeg_not_found_raises(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="未找到 FFmpeg"):
                _bare_mgr(EncodeMode.CPU)._resolve_encode_mode()

    def test_cpu_mode(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            mgr = _bare_mgr(EncodeMode.CPU)
            mgr._resolve_encode_mode()
            assert mgr.active_pipeline == EncodeMode.CPU

    def test_gpu_mode_nvenc_available(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(FFmpegManager, "_check_nvenc_available", return_value=True):
                mgr = _bare_mgr(EncodeMode.GPU)
                mgr._resolve_encode_mode()
                assert mgr.active_pipeline == EncodeMode.GPU

    def test_gpu_mode_nvenc_unavailable_raises(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(FFmpegManager, "_check_nvenc_available", return_value=False):
                with pytest.raises(RuntimeError, match="未检测到 NVENC"):
                    _bare_mgr(EncodeMode.GPU)._resolve_encode_mode()

    def test_auto_mode_prefers_nvenc(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(FFmpegManager, "_check_nvenc_available", return_value=True):
                mgr = _bare_mgr(EncodeMode.AUTO)
                mgr._resolve_encode_mode()
                assert mgr.active_pipeline == EncodeMode.GPU

    def test_auto_mode_falls_back_to_qsv(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(FFmpegManager, "_check_nvenc_available", return_value=False):
                with patch.object(FFmpegManager, "_check_qsv_available", return_value=True):
                    mgr = _bare_mgr(EncodeMode.AUTO)
                    mgr._resolve_encode_mode()
                    assert mgr.active_pipeline == EncodeMode.QSV

    def test_auto_mode_falls_back_to_cpu(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(FFmpegManager, "_check_nvenc_available", return_value=False):
                with patch.object(FFmpegManager, "_check_qsv_available", return_value=False):
                    mgr = _bare_mgr(EncodeMode.AUTO)
                    mgr._resolve_encode_mode()
                    assert mgr.active_pipeline == EncodeMode.CPU

    def test_qsv_mode_available(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(FFmpegManager, "_check_qsv_available", return_value=True):
                mgr = _bare_mgr(EncodeMode.QSV)
                mgr._resolve_encode_mode()
                assert mgr.active_pipeline == EncodeMode.QSV


# =============================================================================
# 探测结果缓存
# =============================================================================

class TestProbeCache:
    """探测结果必须缓存：重复构造不应重跑 ffmpeg 子进程。"""

    def test_probe_runs_once_for_repeated_construction(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager, "_check_nvenc_available", return_value=True,
            ) as mock_nvenc:
                for _ in range(3):
                    _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
                assert mock_nvenc.call_count == 1

    def test_probe_reruns_after_cache_clear(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager, "_check_nvenc_available", return_value=True,
            ) as mock_nvenc:
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
                FFmpegManager.clear_probe_cache()
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
                assert mock_nvenc.call_count == 2

    def test_probe_reruns_when_ffmpeg_path_differs(self):
        with patch.object(
            FFmpegManager, "_check_nvenc_available", return_value=True,
        ) as mock_nvenc:
            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
            with patch("shutil.which", return_value="/opt/other/ffmpeg"):
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
            assert mock_nvenc.call_count == 2

    def test_probe_reruns_when_timeout_differs(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager, "_check_nvenc_available", return_value=True,
            ) as mock_nvenc:
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
                fast = _bare_mgr(EncodeMode.AUTO)
                fast.system_params = SystemParams(ffmpeg_timeout=30)
                fast._resolve_encode_mode()
                assert mock_nvenc.call_count == 2

    def test_cpu_mode_never_probes(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager, "_check_nvenc_available", return_value=True,
            ) as mock_nvenc:
                _bare_mgr(EncodeMode.CPU)._resolve_encode_mode()
                assert mock_nvenc.call_count == 0


# =============================================================================
# ffmpeg_timeout 接线
# =============================================================================

class TestTimeoutPlumbing:
    """ffmpeg_timeout 必须真正驱动子进程超时。"""

    def test_check_nvenc_uses_given_timeout(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_nvenc", returncode=0),
                MagicMock(returncode=0),
            ]
            FFmpegManager._check_nvenc_available(7)
            assert [c.kwargs["timeout"] for c in mock_run.call_args_list] == [7, 7]

    def test_ffprobe_uses_configured_timeout(self, ffmpeg_mgr):
        mock_result = MagicMock()
        mock_result.stdout = (
            '{"streams":[{"width":1920,"height":1080,'
            '"r_frame_rate":"30/1","nb_frames":300}],'
            '"format":{"duration":"10.0"}}'
        )
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                ffmpeg_mgr.get_video_info()
                assert mock_run.call_args.kwargs["timeout"] == (
                    ffmpeg_mgr.system_params.ffmpeg_timeout
                )


# =============================================================================
# _check_nvenc_available / _check_qsv_available
# =============================================================================

class TestCheckEncoders:

    def test_nvenc_not_in_encoders(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="h264_amf", returncode=0)
            assert FFmpegManager._check_nvenc_available() is False

    def test_nvenc_available(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_nvenc", returncode=0),
                MagicMock(returncode=0),
            ]
            assert FFmpegManager._check_nvenc_available() is True

    def test_nvenc_test_encode_fails(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_nvenc", returncode=0),
                MagicMock(returncode=1),
            ]
            assert FFmpegManager._check_nvenc_available() is False

    def test_nvenc_file_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert FFmpegManager._check_nvenc_available() is False

    def test_qsv_available(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_qsv", returncode=0),
                MagicMock(returncode=0),
            ]
            assert FFmpegManager._check_qsv_available() is True


# =============================================================================
# get_video_info
# =============================================================================

class TestGetVideoInfo:

    def test_ffprobe_not_found(self, ffmpeg_mgr):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="未找到 ffprobe"):
                ffmpeg_mgr.get_video_info()

    def test_returns_video_info(self, ffmpeg_mgr):
        mock_result = MagicMock()
        mock_result.stdout = (
            '{"streams":[{"width":1920,"height":1080,'
            '"r_frame_rate":"30000/1001","nb_frames":300}],'
            '"format":{"duration":"10.010"}}'
        )
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", return_value=mock_result):
                info = ffmpeg_mgr.get_video_info()
                assert info["w"] == 1920
                assert info["h"] == 1080
                assert info["frames"] == 300

    def test_estimates_frames_from_duration(self, ffmpeg_mgr):
        mock_result = MagicMock()
        mock_result.stdout = (
            '{"streams":[{"width":1280,"height":720,'
            '"r_frame_rate":"30/1","nb_frames":0}],'
            '"format":{"duration":"5.0"}}'
        )
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", return_value=mock_result):
                info = ffmpeg_mgr.get_video_info()
                assert info["frames"] == 150


# =============================================================================
# build_command
# =============================================================================

class TestBuildCommand:

    def test_cpu_command(self, ffmpeg_mgr):
        lp = LayerParams(layer_w=1920, layer_h=1080, layer_x=0, layer_y=0)
        cmd = ffmpeg_mgr.build_command(30, 1920, 1080, lp)
        assert cmd[0] == "ffmpeg"
        assert "libx264" in cmd
        assert "pipe:0" in cmd

    def test_gpu_command(self, ffmpeg_mgr):
        ffmpeg_mgr.active_pipeline = EncodeMode.GPU
        lp = LayerParams(layer_w=1920, layer_h=1080, layer_x=0, layer_y=0)
        cmd = ffmpeg_mgr.build_command(30, 1920, 1080, lp)
        assert "h264_nvenc" in cmd
        assert "cuda" in cmd

    def test_qsv_command(self, ffmpeg_mgr):
        ffmpeg_mgr.active_pipeline = EncodeMode.QSV
        lp = LayerParams(layer_w=1920, layer_h=1080, layer_x=0, layer_y=0)
        cmd = ffmpeg_mgr.build_command(30, 1920, 1080, lp)
        assert "h264_qsv" in cmd


# =============================================================================
# start / submit_frame / cleanup
# =============================================================================

class TestProcessLifecycle:

    def test_start_creates_process(self, ffmpeg_mgr):
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        with patch("subprocess.Popen", return_value=mock_proc):
            ffmpeg_mgr.start(["ffmpeg", "-i", "test.mp4", "out.mp4"])
            assert ffmpeg_mgr.process is not None
            assert ffmpeg_mgr.stderr_thread is not None

    def test_submit_frame_health_check_fails(self, ffmpeg_mgr):
        ffmpeg_mgr.process = None
        with pytest.raises(RuntimeError, match="FFmpeg 进程已死亡"):
            ffmpeg_mgr.submit_frame(memoryview(b"data"))

    def test_submit_frame_writes_data(self, ffmpeg_mgr):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        ffmpeg_mgr.process = mock_proc
        data = memoryview(b"frame_data")
        ffmpeg_mgr.submit_frame(data)
        mock_proc.stdin.write.assert_called_once_with(data)
        mock_proc.stdin.flush.assert_called_once()

    def test_submit_frame_broken_pipe(self, ffmpeg_mgr):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write.side_effect = BrokenPipeError
        ffmpeg_mgr.process = mock_proc
        with pytest.raises(BrokenPipeError):
            ffmpeg_mgr.submit_frame(memoryview(b"data"))

    def test_cleanup_closes_resources(self, ffmpeg_mgr):
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.wait.return_value = 0
        ffmpeg_mgr.process = mock_proc
        ffmpeg_mgr.stderr_thread = MagicMock()
        ffmpeg_mgr.stderr_thread.is_alive.return_value = False
        ffmpeg_mgr.cleanup()
        mock_proc.stdin.close.assert_called_once()
        mock_proc.wait.assert_called_once()

    def test_cleanup_no_process(self, ffmpeg_mgr):
        ffmpeg_mgr.process = None
        ffmpeg_mgr.cleanup()

    def test_health_check_process_dead(self, ffmpeg_mgr):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1
        ffmpeg_mgr.process = mock_proc
        assert ffmpeg_mgr._health_check() is False

    def test_health_check_process_alive(self, ffmpeg_mgr):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        ffmpeg_mgr.process = mock_proc
        assert ffmpeg_mgr._health_check() is True

    def test_current_speed_property(self, ffmpeg_mgr):
        assert ffmpeg_mgr.current_speed == 0.0
        with ffmpeg_mgr._speed_lock:
            ffmpeg_mgr._current_speed = 2.5
        assert ffmpeg_mgr.current_speed == 2.5