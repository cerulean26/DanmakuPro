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
    # 构造不触发探测（见 FFmpegManager.active_pipeline 的惰性说明），
    # 这里显式指定管线，用例便无需真实 ffmpeg。
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
    mgr._active_pipeline = None
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
# 惰性探测
# =============================================================================

class TestLazyProbe:
    """构造 FFmpegManager 不应付探测代价，首次读取 active_pipeline 才探测。

    探测要起 ffmpeg 子进程（auto 模式缓存未命中时约 1.5s）。若构造即探测，
    GUI 里建好对象后用户取消、单测只断言构造参数等场景都会白付这份代价。
    """

    def test_construction_does_not_probe(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._probe_encode_pipeline",
            ) as mock_probe:
                FFmpegManager("test.mp4", "out.mp4", EncodeMode.AUTO)
                assert mock_probe.call_count == 0

    def test_first_access_triggers_probe(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._probe_encode_pipeline",
                return_value=EncodeMode.GPU,
            ) as mock_probe:
                mgr = FFmpegManager("test.mp4", "out.mp4", EncodeMode.AUTO)
                assert mgr.active_pipeline == EncodeMode.GPU
                assert mock_probe.call_count == 1

    def test_probe_runs_once_across_repeated_reads(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._probe_encode_pipeline",
                return_value=EncodeMode.CPU,
            ) as mock_probe:
                mgr = FFmpegManager("test.mp4", "out.mp4", EncodeMode.AUTO)
                for _ in range(3):
                    mgr.active_pipeline
                assert mock_probe.call_count == 1

    def test_missing_ffmpeg_defers_error_to_first_access(self):
        """没装 ffmpeg 时构造不再立刻报错，改为首次读取时抛出。

        RuntimeError 仍会被 CLI 的 except Exception 兜住并 exit 1，
        退出码不变；只是报错时机从「创建 burner」推迟到「执行」。
        """
        with patch("shutil.which", return_value=None):
            mgr = FFmpegManager("test.mp4", "out.mp4", EncodeMode.CPU)
            with pytest.raises(RuntimeError, match="未找到 FFmpeg"):
                mgr.active_pipeline

    def test_explicit_assignment_skips_probe(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._probe_encode_pipeline",
            ) as mock_probe:
                mgr = FFmpegManager("test.mp4", "out.mp4", EncodeMode.AUTO)
                mgr.active_pipeline = EncodeMode.QSV
                assert mgr.active_pipeline == EncodeMode.QSV
                assert mock_probe.call_count == 0


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
# 帧率口径与 VFR 判定
# =============================================================================

def _probe_json(rate: str, frames: int | None, duration: str) -> str:
    """构造 ffprobe 主探测的输出。"""
    nb = "null" if frames is None else str(frames)
    return (
        '{"streams":[{"width":1920,"height":1080,'
        f'"r_frame_rate":"{rate}","nb_frames":{nb}}}],'
        f'"format":{{"duration":"{duration}"}}}}'
    )


def _sample_json(count: int, interval: float) -> str:
    """构造一段采样的 pts_time 列表，count 帧、间隔 interval 秒。"""
    pts = ",".join(f'{{"pts_time":"{i * interval:.4f}"}}' for i in range(count))
    return '{"frames":[' + pts + ']}'


class TestResolveRenderFps:
    """渲染帧率必须满足 frames / fps == duration，否则弹幕时间轴对不上画面。"""

    def test_uses_real_average_when_nominal_differs(self):
        # 标称 30fps、实际 2000 帧/100s = 20fps。按标称渲染，时间轴只有 66.7s，
        # 后 1/3 的弹幕会全部丢失。
        assert FFmpegManager._resolve_render_fps(30.0, 2000, 100.0) == 20.0

    def test_keeps_nominal_for_cfr_source(self):
        assert FFmpegManager._resolve_render_fps(29.97, 300, 10.01) == pytest.approx(
            29.97, rel=1e-3
        )

    def test_falls_back_when_duration_unknown(self):
        assert FFmpegManager._resolve_render_fps(30.0, 2000, 0.0) == 30.0

    def test_falls_back_when_frames_unknown(self):
        assert FFmpegManager._resolve_render_fps(30.0, 0, 100.0) == 30.0

    def test_falls_back_when_ratio_implausible(self):
        # 300 帧 / 1s = 300fps，与标称差 10 倍，说明 duration 不可信
        assert FFmpegManager._resolve_render_fps(30.0, 300, 1.0) == 30.0

    def test_falls_back_when_nominal_invalid(self):
        assert FFmpegManager._resolve_render_fps(0.0, 2000, 100.0) == 0.0


class TestDetectVfr:

    def test_constant_rate_is_not_vfr(self):
        assert FFmpegManager._detect_vfr([20.0, 20.0, 20.0]) is False

    def test_fluctuating_rate_is_vfr(self):
        assert FFmpegManager._detect_vfr([20.0, 24.0, 20.0]) is True

    def test_insufficient_samples_is_not_vfr(self):
        assert FFmpegManager._detect_vfr([20.0]) is False
        assert FFmpegManager._detect_vfr([]) is False

    def test_zero_rate_is_not_vfr(self):
        assert FFmpegManager._detect_vfr([0.0, 0.0]) is False


class TestSampleLocalFrameRates:

    def test_samples_three_segments(self, ffmpeg_mgr):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_sample_json(100, 0.05))
            rates = ffmpeg_mgr._sample_local_frame_rates(100.0)
        assert len(rates) == 3
        assert all(r == pytest.approx(20.0, rel=1e-2) for r in rates)

    def test_skips_short_video(self, ffmpeg_mgr):
        with patch("subprocess.run") as mock_run:
            assert ffmpeg_mgr._sample_local_frame_rates(10.0) == []
            mock_run.assert_not_called()

    def test_returns_empty_on_probe_error(self, ffmpeg_mgr):
        with patch("subprocess.run", side_effect=OSError):
            assert ffmpeg_mgr._sample_local_frame_rates(100.0) == []

    def test_returns_empty_when_too_few_frames(self, ffmpeg_mgr):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_sample_json(1, 0.05))
            assert ffmpeg_mgr._sample_local_frame_rates(100.0) == []

    def test_returns_empty_on_malformed_json(self, ffmpeg_mgr):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="not json")
            assert ffmpeg_mgr._sample_local_frame_rates(100.0) == []


class TestGetVideoInfoFrameRate:
    """get_video_info 返回的 fps 要让弹幕时间轴等于视频真实时长。"""

    def test_vfr_source_gets_real_average_fps(self, ffmpeg_mgr):
        side = [
            MagicMock(stdout=_probe_json("30/1", 2000, "100.0")),
            MagicMock(stdout=_sample_json(100, 0.05)),   # 20fps
            MagicMock(stdout=_sample_json(100, 0.04)),   # 25fps
            MagicMock(stdout=_sample_json(100, 0.05)),   # 20fps
        ]
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", side_effect=side):
                info = ffmpeg_mgr.get_video_info()
        assert info["frames"] == 2000
        assert info["fps"] == 20.0
        assert info["frames"] / info["fps"] == 100.0
        assert info["vfr"] is True

    def test_cfr_source_keeps_nominal_fps(self, ffmpeg_mgr):
        side = [
            MagicMock(stdout=_probe_json("30/1", 3000, "100.0")),
            MagicMock(stdout=_sample_json(150, 0.0333)),
            MagicMock(stdout=_sample_json(150, 0.0333)),
            MagicMock(stdout=_sample_json(150, 0.0333)),
        ]
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", side_effect=side):
                info = ffmpeg_mgr.get_video_info()
        assert info["fps"] == 30.0
        assert info["vfr"] is False


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

    @pytest.mark.parametrize(
        "return_code",
        [
            0,    # 只在 Python 侧中断，FFmpeg 按 stdin EOF 正常收尾
            255,  # 控制台 Ctrl+C 连带杀掉 FFmpeg（Windows 实测码）
        ],
    )
    def test_cleanup_interrupted_not_marked_success(
        self, ffmpeg_mgr, return_code,
    ):
        """中断时无论 FFmpeg 怎么退出，都不能记成压制成功。

        更关键的是也不能记成「压制失败」：那是主动取消，不是故障。
        """
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.wait.return_value = return_code
        ffmpeg_mgr.process = mock_proc
        ffmpeg_mgr.stderr_thread = MagicMock()
        ffmpeg_mgr.stderr_thread.is_alive.return_value = False
        ffmpeg_mgr.interrupted = True

        ffmpeg_mgr.cleanup()
        assert ffmpeg_mgr.encode_succeeded is False

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