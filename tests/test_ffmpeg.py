"""FFmpegManager 单元测试"""

import contextlib
import io
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from danmakupro.encode.ffmpeg import FFmpegManager, _probe_encode_pipeline
from danmakupro.config.models import (
    EncodeMode,
    SystemParams,
    DEFAULT_CONFIG,
)
from danmakupro.layout.params import LayerParams


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
            with patch.object(
                FFmpegManager, "_check_nvenc_available", return_value=True
            ):
                mgr = _bare_mgr(EncodeMode.GPU)
                mgr._resolve_encode_mode()
                assert mgr.active_pipeline == EncodeMode.GPU

    def test_gpu_mode_nvenc_unavailable_raises(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager, "_check_nvenc_available", return_value=False
            ):
                with pytest.raises(RuntimeError, match="未检测到 NVENC"):
                    _bare_mgr(EncodeMode.GPU)._resolve_encode_mode()

    def test_auto_mode_prefers_nvenc(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager, "_check_nvenc_available", return_value=True
            ):
                mgr = _bare_mgr(EncodeMode.AUTO)
                mgr._resolve_encode_mode()
                assert mgr.active_pipeline == EncodeMode.GPU

    def test_auto_mode_falls_back_to_qsv(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager, "_check_nvenc_available", return_value=False
            ):
                with patch.object(
                    FFmpegManager, "_check_qsv_available", return_value=True
                ):
                    mgr = _bare_mgr(EncodeMode.AUTO)
                    mgr._resolve_encode_mode()
                    assert mgr.active_pipeline == EncodeMode.QSV

    def test_auto_mode_falls_back_to_cpu(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager, "_check_nvenc_available", return_value=False
            ):
                with patch.object(
                    FFmpegManager, "_check_qsv_available", return_value=False
                ):
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
                FFmpegManager,
                "_check_nvenc_available",
                return_value=True,
            ) as mock_nvenc:
                for _ in range(3):
                    _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
                assert mock_nvenc.call_count == 1

    def test_probe_reruns_after_cache_clear(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager,
                "_check_nvenc_available",
                return_value=True,
            ) as mock_nvenc:
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
                FFmpegManager.clear_probe_cache()
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
                assert mock_nvenc.call_count == 2

    def test_probe_reruns_when_ffmpeg_path_differs(self):
        with patch.object(
            FFmpegManager,
            "_check_nvenc_available",
            return_value=True,
        ) as mock_nvenc:
            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
            with patch("shutil.which", return_value="/opt/other/ffmpeg"):
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
            assert mock_nvenc.call_count == 2

    def test_probe_reruns_when_timeout_differs(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager,
                "_check_nvenc_available",
                return_value=True,
            ) as mock_nvenc:
                _bare_mgr(EncodeMode.AUTO)._resolve_encode_mode()
                fast = _bare_mgr(EncodeMode.AUTO)
                fast.system_params = SystemParams(ffmpeg_timeout=30)
                fast._resolve_encode_mode()
                assert mock_nvenc.call_count == 2

    def test_cpu_mode_never_probes(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch.object(
                FFmpegManager,
                "_check_nvenc_available",
                return_value=True,
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

    def test_nvenc_test_encode_timeout(self):
        """探测第二段（真实编码试探）超时要判为不可用，且不能往上抛。"""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_nvenc", returncode=0),
                subprocess.TimeoutExpired("ffmpeg", 5),
            ]
            assert FFmpegManager._check_nvenc_available() is False

    def test_qsv_not_in_encoders(self):
        """encoders 列表里没有 h264_qsv：第一段就返回，不进入试探。"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="h264_nvenc", returncode=0)
            assert FFmpegManager._check_qsv_available() is False
            assert mock_run.call_count == 1

    def test_qsv_test_encode_fails(self):
        """编码器在列表里但真实试探返回非 0（驱动缺失等）：判不可用。"""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_qsv", returncode=0),
                MagicMock(returncode=1),
            ]
            assert FFmpegManager._check_qsv_available() is False

    def test_qsv_ffmpeg_missing(self):
        """ffmpeg 不存在：直接判不可用，不抛异常打断启动流程。"""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert FFmpegManager._check_qsv_available() is False

    def test_qsv_probe_timeout(self):
        """列编码器这一步超时（机器卡顿）：同样判不可用而非抛出。"""
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)
        ):
            assert FFmpegManager._check_qsv_available() is False

    def test_qsv_test_encode_timeout(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="h264_qsv", returncode=0),
                subprocess.TimeoutExpired("ffmpeg", 5),
            ]
            assert FFmpegManager._check_qsv_available() is False


# =============================================================================
# _probe_encode_pipeline
# =============================================================================


class TestProbeEncodePipeline:
    """显式指定硬件编码器但不可用时必须报错，不能静默退回 CPU。

    静默退回会让用户以为在用 GPU 加速 —— 实际慢数倍，且日志里看不出原因。
    """

    def test_gpu_unavailable_raises(self):
        with patch.object(FFmpegManager, "_check_nvenc_available", return_value=False):
            with pytest.raises(RuntimeError, match="未检测到 NVENC"):
                _probe_encode_pipeline(EncodeMode.GPU, "/usr/bin/ffmpeg", 5)

    def test_qsv_unavailable_raises(self):
        with patch.object(FFmpegManager, "_check_qsv_available", return_value=False):
            with pytest.raises(RuntimeError, match="未检测到 QSV"):
                _probe_encode_pipeline(EncodeMode.QSV, "/usr/bin/ffmpeg", 5)

    def test_cpu_never_probes_encoders(self):
        """CPU 是兜底路径，任何探测都不该发生（否则每次构造白等 1.5s）。"""
        with patch.object(FFmpegManager, "_check_nvenc_available") as mock_nvenc:
            with patch.object(FFmpegManager, "_check_qsv_available") as mock_qsv:
                resolved = _probe_encode_pipeline(
                    EncodeMode.CPU,
                    "/usr/bin/ffmpeg",
                    5,
                )
                assert resolved == EncodeMode.CPU
                mock_nvenc.assert_not_called()
                mock_qsv.assert_not_called()


# =============================================================================
# _parse_frame_rate
# =============================================================================


class TestParseFrameRate:
    """r_frame_rate 是 "num/den" 字符串，任何畸形都要回落到 0.0。

    返回 0.0 而非抛异常，是为了让调用方走「无法解析标称帧率 → 换别的口径」，
    而不是让整个 get_video_info 崩掉。分母为 0 尤其要拦：不拦就是除零。
    """

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("30/1", 30.0),
            ("30000/1001", pytest.approx(29.97, rel=1e-4)),
            ("25", 25.0),  # 无分母，按 /1 处理
            (None, 0.0),  # 字段缺失
            ("", 0.0),  # 空串
            ("abc/1", 0.0),  # 分子非数字
            ("30/abc", 0.0),  # 分母非数字
            ("30/0", 0.0),  # 分母为 0
        ],
    )
    def test_parse(self, raw, expected):
        assert FFmpegManager._parse_frame_rate(raw) == expected


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

    def test_nb_frames_na_falls_back_to_duration_estimate(self, ffmpeg_mgr):
        """nb_frames 写成 "N/A" 时必须估算，不能让整次探测失败。

        这不是假想输入：FLV 容器（本项目主用格式）的 nb_frames 常常是
        "N/A"，此时 int("N/A") 抛 ValueError，若不接住整个压制都起不来。
        """
        mock_result = MagicMock()
        mock_result.stdout = (
            '{"streams":[{"width":640,"height":360,'
            '"r_frame_rate":"25/1","nb_frames":"N/A"}],'
            '"format":{"duration":"4.0"}}'
        )
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", return_value=mock_result):
                info = ffmpeg_mgr.get_video_info()
        assert info["frames"] == 100  # 4.0s × 25fps 估算
        assert info["fps"] == 25.0

    def test_missing_nb_frames_falls_back_to_duration_estimate(self, ffmpeg_mgr):
        """nb_frames 为 null（部分 mp4 如此）走同一条估算路径。"""
        mock_result = MagicMock()
        mock_result.stdout = (
            '{"streams":[{"width":640,"height":360,'
            '"r_frame_rate":"25/1","nb_frames":null}],'
            '"format":{"duration":"4.0"}}'
        )
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", return_value=mock_result):
                info = ffmpeg_mgr.get_video_info()
        assert info["frames"] == 100

    def test_missing_duration_falls_back_to_nominal_fps(self, ffmpeg_mgr):
        """format 段没有 duration：不能崩，fps 回落到标称帧率。"""
        mock_result = MagicMock()
        mock_result.stdout = (
            '{"streams":[{"width":640,"height":360,'
            '"r_frame_rate":"25/1","nb_frames":100}],'
            '"format":{}}'
        )
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", return_value=mock_result):
                info = ffmpeg_mgr.get_video_info()
        assert info["frames"] == 100
        assert info["fps"] == 25.0
        assert info["vfr"] is False  # duration 未知时不该报 VFR


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
    return '{"frames":[' + pts + "]}"


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

    def test_infinite_duration_falls_back_to_nominal(self):
        """防御分支：duration 为 inf 时 frames/duration == 0.0。

        实测这条分支只有 duration=inf 能触发（300/inf 得到 0.0）；真实的
        ffprobe 不会输出 inf，所以它属于防御性代码而非真实路径。仍写用例是
        为了锁住「宁可回落到标称帧率，也绝不返回 0」这个行为 —— 返回 0 会让
        frame_index / fps 直接除零。
        """
        assert FFmpegManager._resolve_render_fps(30.0, 300, float("inf")) == 30.0

    def test_nan_duration_falls_back_to_nominal(self):
        """nan 会穿过开头的 `duration <= 0` 检查（nan 与任何数比较都是 False），
        必须依靠后面的比值合理性检查拦下。"""
        assert FFmpegManager._resolve_render_fps(30.0, 300, float("nan")) == 30.0


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

    def test_skips_entries_with_bad_pts_time(self, ffmpeg_mgr):
        """单条 pts_time 畸形只跳过该条，不能让整段采样作废。

        这里逐条 try/except 而非整体包住，正是为了保留有效样本；一旦退化成
        抛异常，VFR 判定会被外层吞成「无法判定」而永久失灵 —— 静默失效。
        """
        payload = (
            '{"frames":['
            '{"pts_time":"0.0000"},'
            '{"no_pts":1},'  # KeyError
            '{"pts_time":"abc"},'  # ValueError
            '{"pts_time":null},'  # TypeError
            '{"pts_time":"0.1000"}'
            "]}"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=payload)
            rates = ffmpeg_mgr._sample_local_frame_rates(100.0)
        # 三段各自只剩 2 个有效 pts，跨 0.1s → 10fps
        assert len(rates) == 3
        assert all(r == pytest.approx(10.0) for r in rates)

    def test_returns_empty_when_span_is_zero(self, ffmpeg_mgr):
        """所有 pts 相同 → span=0；不提前返回的话 (n-1)/0 会算出 inf，
        一个无穷大的局部帧率会污染后面的极差判定。"""
        payload = '{"frames":[{"pts_time":"1.0000"},{"pts_time":"1.0000"}]}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=payload)
            assert ffmpeg_mgr._sample_local_frame_rates(100.0) == []


class TestGetVideoInfoFrameRate:
    """get_video_info 返回的 fps 要让弹幕时间轴等于视频真实时长。"""

    def test_vfr_source_gets_real_average_fps(self, ffmpeg_mgr):
        side = [
            MagicMock(stdout=_probe_json("30/1", 2000, "100.0")),
            MagicMock(stdout=_sample_json(100, 0.05)),  # 20fps
            MagicMock(stdout=_sample_json(100, 0.04)),  # 25fps
            MagicMock(stdout=_sample_json(100, 0.05)),  # 20fps
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
            0,  # 只在 Python 侧中断，FFmpeg 按 stdin EOF 正常收尾
            255,  # 控制台 Ctrl+C 连带杀掉 FFmpeg（Windows 实测码）
        ],
    )
    def test_cleanup_interrupted_not_marked_success(
        self,
        ffmpeg_mgr,
        return_code,
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


# =============================================================================
# stderr 读取线程
# =============================================================================


class TestStderrReader:
    """stderr 逐行解析 —— 编码速度与故障日志都只在这条路径上产生。

    这条路径出错不会抛异常，只会让 current_speed 永远为 0、或把 ffmpeg 的
    错误行降级成 debug，属于典型的静默失效，因此值得逐分支钉住。
    """

    def test_extracts_speed_from_progress_line(self, ffmpeg_mgr):
        payload = b"frame= 120 fps=30 q=28.0 size=1kB time=00:00:04.00 speed=1.85x\n"
        with _stderr_reader(ffmpeg_mgr, payload) as read:
            read()
        assert ffmpeg_mgr.current_speed == pytest.approx(1.85)

    def test_progress_line_without_speed_keeps_previous_value(self, ffmpeg_mgr):
        """首帧的 frame= 行通常还没有 speed= 字段，不能把速度抹回 0。"""
        with ffmpeg_mgr._speed_lock:
            ffmpeg_mgr._current_speed = 3.0
        payload = b"frame= 1 fps=0.0 q=0.0 size=0kB time=00:00:00.00\n"
        with _stderr_reader(ffmpeg_mgr, payload) as read:
            read()
        assert ffmpeg_mgr.current_speed == 3.0

    def test_logs_lines_by_severity(self, ffmpeg_mgr):
        """error 行必须记 error 级：降级成 debug 后用户看不到失败原因。"""
        payload = (
            b"[h264 @ 0x1] Error while decoding stream #0:0\n"
            b"[swscaler @ 0x2] Warning: data is not aligned\n"
            b"  Stream mapping:\n"
            b"\n"
        )
        with patch("danmakupro.encode.ffmpeg.logger") as mock_logger:
            with _stderr_reader(ffmpeg_mgr, payload) as read:
                read()
        assert mock_logger.error.call_count == 1
        assert "Error while decoding" in mock_logger.error.call_args[0][0]
        assert mock_logger.warning.call_count == 1
        assert "Warning: data is not aligned" in mock_logger.warning.call_args[0][0]
        # 空行被 continue 掉，普通行只剩 1 条
        assert mock_logger.debug.call_count == 1
        assert "Stream mapping" in mock_logger.debug.call_args[0][0]

    def test_progress_line_is_not_also_logged(self, ffmpeg_mgr):
        """frame= 行只用于取速度，不能同时漏进日志 —— 否则每帧刷一行。"""
        payload = b"frame= 120 fps=30 speed=2.00x\n"
        with patch("danmakupro.encode.ffmpeg.logger") as mock_logger:
            with _stderr_reader(ffmpeg_mgr, payload) as read:
                read()
        mock_logger.debug.assert_not_called()
        mock_logger.error.assert_not_called()
        mock_logger.warning.assert_not_called()

    def test_noop_when_process_already_cleared(self, ffmpeg_mgr):
        """cleanup() 可能在线程读到第一行之前就把 process 置空（真实竞态），
        此时必须安静返回，而不是抛 AttributeError 把线程打死。"""
        with _stderr_reader(ffmpeg_mgr, b"frame= 1 speed=1x\n") as read:
            ffmpeg_mgr.process = None
            read()
        assert ffmpeg_mgr.current_speed == 0.0


# =============================================================================
# 进程收尾的异常路径
# =============================================================================


class TestCleanupFailures:
    """收尾阶段任何一步出问题都不能让清理半途而废（残留产物、残留管道）。"""

    def test_submit_frame_process_alive_but_stdin_missing(self, ffmpeg_mgr):
        """进程活着但 stdin 已不可用（收尾竞态）：明确报「未启动」。"""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # 健康检查通过
        mock_proc.stdin = None  # 但管道没了
        ffmpeg_mgr.process = mock_proc
        with pytest.raises(RuntimeError, match="FFmpeg 未启动"):
            ffmpeg_mgr.submit_frame(memoryview(b"data"))

    def test_cleanup_waits_for_stderr_thread(self, ffmpeg_mgr):
        """必须等 stderr 线程读完再关管道，否则会丢日志。"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.wait.return_value = 0
        ffmpeg_mgr.process = mock_proc
        ffmpeg_mgr.stderr_thread = MagicMock()
        ffmpeg_mgr.stderr_thread.is_alive.return_value = True
        ffmpeg_mgr.cleanup()
        ffmpeg_mgr.stderr_thread.join.assert_called_once_with(
            timeout=ffmpeg_mgr.system_params.stderr_thread_timeout,
        )

    def test_cleanup_swallows_stdin_close_error(self, ffmpeg_mgr):
        """stdin 可能已被 FFmpeg 侧关掉，close() 报错不能中断后续收尾。"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.close.side_effect = OSError("already closed")
        mock_proc.stderr = MagicMock()
        mock_proc.wait.return_value = 0
        ffmpeg_mgr.process = mock_proc
        ffmpeg_mgr.stderr_thread = None
        ffmpeg_mgr.cleanup()
        mock_proc.wait.assert_called_once()  # 后续步骤照常执行

    def test_cleanup_swallows_stderr_close_error(self, ffmpeg_mgr):
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.close.side_effect = OSError("already closed")
        mock_proc.wait.return_value = 0
        ffmpeg_mgr.process = mock_proc
        ffmpeg_mgr.stderr_thread = None
        ffmpeg_mgr.cleanup()
        assert ffmpeg_mgr.process is None  # 结尾的置空仍发生

    def test_failed_encode_is_logged_as_error(self, ffmpeg_mgr):
        """非中断且非 0 退出 = 真失败：记 error，且不能置 encode_succeeded。"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.wait.return_value = 1
        ffmpeg_mgr.process = mock_proc
        ffmpeg_mgr.stderr_thread = None
        with patch("danmakupro.encode.ffmpeg.logger") as mock_logger:
            ffmpeg_mgr.cleanup()
        assert ffmpeg_mgr.encode_succeeded is False
        assert "压制失败" in mock_logger.error.call_args[0][0]

    def test_encode_timeout_kills_process(self, ffmpeg_mgr):
        """wait 超时（600s）不能把主进程挂死：强杀后再回收。"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired("ffmpeg", 600),
            0,
        ]
        ffmpeg_mgr.process = mock_proc
        ffmpeg_mgr.stderr_thread = None
        with patch("danmakupro.encode.ffmpeg.logger") as mock_logger:
            ffmpeg_mgr.cleanup()
        mock_proc.kill.assert_called_once()
        assert mock_proc.wait.call_count == 2  # 第一次超时，第二次回收
        assert mock_logger.warning.call_count == 1
        assert ffmpeg_mgr.process is None
