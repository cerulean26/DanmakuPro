"""FFmpegManager 单元测试：管线解析、惰性探测、探测缓存与进程生命周期。

其余三块分别测在 test_capability.py（编码器可用性与硬解清单）、
test_probe.py（视频元数据与帧率口径）、test_commands.py（命令行构建）。
"""

import contextlib
import io
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from danmakupro.config.models import EncodeMode, SystemParams, DEFAULT_CONFIG
from danmakupro.encode.ffmpeg import (
    FFmpegManager,
    _check_encoder,
    _probe_encode_pipeline,
)


@contextlib.contextmanager
def _stderr_reader(mgr, payload: bytes):
    """跑 mgr.start()，但把 stderr 读取线程的函数体截出来同步调用。

    真起线程会有竞态 —— 断言时线程未必读完，只能靠 sleep 赌。这里直接取出
    闭包执行，测的是同一份代码，却没有时序不确定性。

    Yields:
        读取线程的 target 函数（无参，调用即等价于线程跑一轮）。
    """
    captured: dict = {}
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stderr = io.BytesIO(payload)

    def _fake_thread(target, daemon=None):
        captured["target"] = target
        return MagicMock()

    with patch("subprocess.Popen", return_value=proc):
        with patch("threading.Thread", side_effect=_fake_thread):
            mgr.start(["ffmpeg", "-i", "in.mp4", "out.mp4"])
    yield captured["target"]


# =============================================================================
# _resolve_encode_mode
# =============================================================================


def _bare_mgr(mode, codec="h264"):
    """构造一个绕过 __init__ 的管理器，只填 _resolve_encode_mode 需要的属性。

    codec 默认为常见的 H.264（各硬件都能硬解），想测「不可硬解 → 回退」
    把它传成本机不支持的值即可。
    """
    mgr = FFmpegManager.__new__(FFmpegManager)
    mgr.encode_mode = mode
    mgr.video_in = "test.mp4"
    mgr.encode_params = DEFAULT_CONFIG.encode
    mgr.system_params = DEFAULT_CONFIG.system
    mgr._active_pipeline = None
    mgr._input_codec = codec
    return mgr


@pytest.fixture
def _hw_decoders():
    """避开真实的 `ffmpeg -decoders`：这里只测管线选择，不测本机硬件。

    集合写成 {h264}，与 _bare_mgr 的默认编码配套。
    """
    with patch(
        "danmakupro.encode.capability.hardware_decodable_codecs",
        return_value=frozenset({"h264"}),
    ):
        yield


class TestResolveEncodeMode:
    pytestmark = pytest.mark.usefixtures("_hw_decoders")

    def test_ffmpeg_not_found_raises(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="未找到 FFmpeg"):
                _bare_mgr(EncodeMode.H264)._resolve_encode_mode()

    def test_cpu_mode(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            mgr = _bare_mgr(EncodeMode.H264)
            mgr._resolve_encode_mode()
            assert mgr.active_pipeline == EncodeMode.H264

    def test_nvenc_mode_available(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._check_encoder", return_value=True
            ):
                mgr = _bare_mgr(EncodeMode.H264_NVENC)
                mgr._resolve_encode_mode()
                assert mgr.active_pipeline == EncodeMode.H264_NVENC

    def test_nvenc_mode_unavailable_raises(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._check_encoder", return_value=False
            ):
                with pytest.raises(RuntimeError, match="未检测到 NVENC"):
                    _bare_mgr(EncodeMode.H264_NVENC)._resolve_encode_mode()

    def test_qsv_mode_available(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("danmakupro.encode.ffmpeg._check_encoder", return_value=True):
                mgr = _bare_mgr(EncodeMode.H264_QSV)
                mgr._resolve_encode_mode()
                assert mgr.active_pipeline == EncodeMode.H264_QSV


# =============================================================================
# 硬解判据：不可硬解的输入必须从硬件管线落到 CPU 管线
# =============================================================================


class TestHwDecodeFallback:
    """不可硬解必须落到 CPU 管线：GPU 路径对此类输入是**必然失败**，不是慢一点。"""

    @pytest.fixture(autouse=True)
    def _clean(self):
        FFmpegManager.clear_probe_cache()
        yield
        FFmpegManager.clear_probe_cache()

    @pytest.fixture(autouse=True)
    def _hw(self):
        """只放行 h264：这里测的是降级规则，不该掺本机真实的硬解清单。"""
        with patch(
            "danmakupro.encode.capability.hardware_decodable_codecs",
            return_value=frozenset({"h264"}),
        ):
            yield

    def _resolve(self, mode, codec):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._check_encoder", return_value=True
            ):
                mgr = _bare_mgr(mode, codec=codec)
                mgr._resolve_encode_mode()
        return mgr.active_pipeline

    def test_gpu_undecodable_falls_back_to_cpu(self):
        assert self._resolve(EncodeMode.H264_NVENC, "hevc") == EncodeMode.H264

    def test_qsv_undecodable_falls_back_to_cpu(self):
        assert self._resolve(EncodeMode.H264_QSV, "mpeg4") == EncodeMode.H264

    def test_decodable_keeps_gpu(self):
        assert self._resolve(EncodeMode.H264_NVENC, "h264") == EncodeMode.H264_NVENC

    def test_unknown_codec_keeps_requested_pipeline(self):
        """输入编码探不到时不降级 —— 那会让硬加速平白丢失，真正的错误由
        后续 get_video_info() 给出。
        """
        with patch.object(FFmpegManager, "probe_input_codec", return_value=None):
            assert self._resolve(EncodeMode.H264_NVENC, None) == EncodeMode.H264_NVENC

    def test_unknown_support_set_keeps_requested_pipeline(self):
        with patch(
            "danmakupro.encode.capability.hardware_decodable_codecs", return_value=None
        ):
            assert self._resolve(EncodeMode.H264_NVENC, "hevc") == EncodeMode.H264_NVENC


# =============================================================================
# 惰性探测
# =============================================================================


class TestLazyProbe:
    """构造 FFmpegManager 不应付探测代价，首次读取 active_pipeline 才探测。

    探测要起 ffmpeg 子进程（缓存未命中时约 1.5s）。若构造即探测，
    GUI 里建好对象后用户取消、单测只断言构造参数等场景都会白付这份代价。
    """

    def test_construction_does_not_probe(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._probe_encode_pipeline",
            ) as mock_probe:
                FFmpegManager("test.mp4", "out.mp4", EncodeMode.H264)
                assert mock_probe.call_count == 0

    def test_first_access_triggers_probe(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._probe_encode_pipeline",
                return_value=EncodeMode.H264_NVENC,
            ) as mock_probe:
                mgr = FFmpegManager("test.mp4", "out.mp4", EncodeMode.H264_NVENC)
                assert mgr.active_pipeline == EncodeMode.H264_NVENC
                assert mock_probe.call_count == 1

    def test_probe_runs_once_across_repeated_reads(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._probe_encode_pipeline",
                return_value=EncodeMode.H264,
            ) as mock_probe:
                mgr = FFmpegManager("test.mp4", "out.mp4", EncodeMode.H264)
                for _ in range(3):
                    mgr.active_pipeline
                assert mock_probe.call_count == 1

    def test_missing_ffmpeg_defers_error_to_first_access(self):
        """没装 ffmpeg 时构造不再立刻报错，改为首次读取时抛出。

        RuntimeError 仍会被 CLI 的 except Exception 兜住并 exit 1，
        退出码不变；只是报错时机从「创建 burner」推迟到「执行」。
        """
        with patch("shutil.which", return_value=None):
            mgr = FFmpegManager("test.mp4", "out.mp4", EncodeMode.H264)
            with pytest.raises(RuntimeError, match="未找到 FFmpeg"):
                mgr.active_pipeline

    def test_explicit_assignment_skips_probe(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._probe_encode_pipeline",
            ) as mock_probe:
                mgr = FFmpegManager("test.mp4", "out.mp4", EncodeMode.H264_NVENC)
                mgr.active_pipeline = EncodeMode.H264_QSV
                assert mgr.active_pipeline == EncodeMode.H264_QSV
                assert mock_probe.call_count == 0


# =============================================================================
# 探测结果缓存
# =============================================================================


class TestProbeCache:
    """探测结果必须缓存：重复构造不应重跑 ffmpeg 子进程。"""

    pytestmark = pytest.mark.usefixtures("_hw_decoders")

    def test_probe_runs_once_for_repeated_construction(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._check_encoder",
                return_value=True,
            ) as mock_check:
                for _ in range(3):
                    _bare_mgr(EncodeMode.H264_NVENC)._resolve_encode_mode()
                assert mock_check.call_count == 1

    def test_probe_reruns_after_cache_clear(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._check_encoder",
                return_value=True,
            ) as mock_check:
                _bare_mgr(EncodeMode.H264_NVENC)._resolve_encode_mode()
                FFmpegManager.clear_probe_cache()
                _bare_mgr(EncodeMode.H264_NVENC)._resolve_encode_mode()
                assert mock_check.call_count == 2

    def test_probe_reruns_when_ffmpeg_path_differs(self):
        with patch(
            "danmakupro.encode.ffmpeg._check_encoder",
            return_value=True,
        ) as mock_check:
            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                _bare_mgr(EncodeMode.H264_NVENC)._resolve_encode_mode()
            with patch("shutil.which", return_value="/opt/other/ffmpeg"):
                _bare_mgr(EncodeMode.H264_NVENC)._resolve_encode_mode()
            assert mock_check.call_count == 2

    def test_probe_reruns_when_timeout_differs(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._check_encoder",
                return_value=True,
            ) as mock_check:
                _bare_mgr(EncodeMode.H264_NVENC)._resolve_encode_mode()
                fast = _bare_mgr(EncodeMode.H264_NVENC)
                fast.system_params = SystemParams(ffmpeg_timeout=30)
                fast._resolve_encode_mode()
                assert mock_check.call_count == 2

    def test_cpu_mode_never_probes(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch(
                "danmakupro.encode.ffmpeg._check_encoder",
                return_value=True,
            ) as mock_check:
                _bare_mgr(EncodeMode.H264)._resolve_encode_mode()
                assert mock_check.call_count == 0


# =============================================================================
# _probe_encode_pipeline
# =============================================================================


class TestProbeEncodePipeline:
    """显式指定硬件编码器但不可用时必须报错，不能静默退回 CPU。

    静默退回会让用户以为在用 GPU 加速 —— 实际慢数倍，且日志里看不出原因。
    """

    def test_gpu_unavailable_raises(self):
        with patch(
            "danmakupro.encode.ffmpeg._check_encoder", return_value=False
        ):
            with pytest.raises(RuntimeError, match="未检测到 NVENC"):
                _probe_encode_pipeline(EncodeMode.H264_NVENC, "/usr/bin/ffmpeg", 5)

    def test_qsv_unavailable_raises(self):
        with patch(
            "danmakupro.encode.ffmpeg._check_encoder", return_value=False
        ):
            with pytest.raises(RuntimeError, match="未检测到 QSV"):
                _probe_encode_pipeline(EncodeMode.H264_QSV, "/usr/bin/ffmpeg", 5)

    def test_cpu_never_probes_encoders(self):
        """CPU 是兜底路径，任何探测都不该发生（否则每次构造白等 1.5s）。"""
        with patch(
            "danmakupro.encode.ffmpeg._check_encoder"
        ) as mock_check:
            resolved = _probe_encode_pipeline(
                EncodeMode.H264,
                "/usr/bin/ffmpeg",
                5,
            )
            assert resolved == EncodeMode.H264
            mock_check.assert_not_called()


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
        with pytest.raises(BrokenPipeError, match="FFmpeg 管道断开"):
            ffmpeg_mgr.submit_frame(memoryview(b"data"))

    def test_cleanup_sets_process_to_none(self, ffmpeg_mgr):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        ffmpeg_mgr.process = mock_proc
        ffmpeg_mgr.stderr_thread = MagicMock()
        ffmpeg_mgr.stderr_thread.is_alive.return_value = False
        ffmpeg_mgr.cleanup()
        assert ffmpeg_mgr.process is None
        assert ffmpeg_mgr.encode_succeeded

    def test_cleanup_marks_failure_on_nonzero_return(self, ffmpeg_mgr):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.wait.return_value = 1
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        ffmpeg_mgr.process = mock_proc
        ffmpeg_mgr.stderr_thread = MagicMock()
        ffmpeg_mgr.stderr_thread.is_alive.return_value = False
        ffmpeg_mgr.cleanup()
        assert not ffmpeg_mgr.encode_succeeded


# =============================================================================
# stderr 解析
# =============================================================================


class TestStderrParsing:
    def test_speed_parsed_from_stderr(self, ffmpeg_mgr):
        payload = (
            b"frame=  100 fps=0.0 q=-0.0 size=     256kB time=00:00:04.00 "
            b"bitrate= 524.3kbits/s speed=2.5x\n"
        )
        with _stderr_reader(ffmpeg_mgr, payload) as target:
            target()
            assert ffmpeg_mgr.current_speed == 2.5

    def test_error_line_does_not_set_speed(self, ffmpeg_mgr):
        payload = b"Error: something went wrong\n"
        with _stderr_reader(ffmpeg_mgr, payload) as target:
            target()
            assert ffmpeg_mgr.current_speed == 0.0

    def test_warning_line_does_not_set_speed(self, ffmpeg_mgr):
        payload = b"Warning: deprecated option\n"
        with _stderr_reader(ffmpeg_mgr, payload) as target:
            target()
            assert ffmpeg_mgr.current_speed == 0.0