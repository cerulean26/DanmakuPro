"""probe 模块单元测试：视频元数据探测与帧率口径。

纯函数（parse_frame_rate / resolve_render_fps / probe_packet_count /
probe_input_codec）直接调 probe 的公开名；get_video_info 是 FFmpegManager 的
门面方法，仍从门面进入 —— 门面本身只做参数转发与结果回填，断言留在这一层
可以一并守住回填行为。
"""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from danmakupro.encode import probe


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
        assert probe.parse_frame_rate(raw) == expected


# =============================================================================
# 帧率口径
# =============================================================================


def _probe_json(rate: str, frames: int | None, duration: str) -> str:
    """构造 ffprobe 主探测的输出。"""
    nb = "null" if frames is None else str(frames)
    return (
        '{"streams":[{"width":1920,"height":1080,'
        f'"r_frame_rate":"{rate}","nb_frames":{nb}}}],'
        f'"format":{{"duration":"{duration}"}}}}'
    )


class TestResolveRenderFps:
    """渲染帧率必须满足 frames / fps == duration，否则弹幕时间轴对不上画面。"""

    def test_uses_real_average_when_nominal_differs(self):
        # 标称 30fps、实际 2000 帧/100s = 20fps。按标称渲染，时间轴只有 66.7s，
        # 后 1/3 的弹幕会全部丢失。
        assert probe.resolve_render_fps(30.0, 2000, 100.0) == 20.0

    def test_keeps_nominal_for_cfr_source(self):
        assert probe.resolve_render_fps(29.97, 300, 10.01) == pytest.approx(
            29.97, rel=1e-3
        )

    def test_falls_back_when_duration_unknown(self):
        assert probe.resolve_render_fps(30.0, 2000, 0.0) == 30.0

    def test_falls_back_when_frames_unknown(self):
        assert probe.resolve_render_fps(30.0, 0, 100.0) == 30.0

    def test_falls_back_when_ratio_implausible(self):
        # 300 帧 / 1s = 300fps，与标称差 10 倍，说明 duration 不可信
        assert probe.resolve_render_fps(30.0, 300, 1.0) == 30.0

    def test_falls_back_when_nominal_invalid(self):
        assert probe.resolve_render_fps(0.0, 2000, 100.0) == 0.0

    def test_infinite_duration_falls_back_to_nominal(self):
        """防御分支：duration 为 inf 时 frames/duration == 0.0。

        实测这条分支只有 duration=inf 能触发（300/inf 得到 0.0）；真实的
        ffprobe 不会输出 inf，所以它属于防御性代码而非真实路径。仍写用例是
        为了锁住「宁可回落到标称帧率，也绝不返回 0」这个行为 —— 返回 0 会让
        frame_index / fps 直接除零。
        """
        assert probe.resolve_render_fps(30.0, 300, float("inf")) == 30.0

    def test_nan_duration_falls_back_to_nominal(self):
        """nan 会穿过开头的 `duration <= 0` 检查（nan 与任何数比较都是 False），
        必须依靠后面的比值合理性检查拦下。"""
        assert probe.resolve_render_fps(30.0, 300, float("nan")) == 30.0


# =============================================================================
# 输入编码与包数探测
# =============================================================================


class TestProbeInputCodec:
    def test_returns_codec_name(self):
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="hevc\n")
                assert probe.probe_input_codec("in.mp4", 5) == "hevc"

    def test_ffprobe_missing_returns_none(self):
        with patch("shutil.which", return_value=None):
            assert probe.probe_input_codec("in.mp4", 5) is None

    def test_failure_returns_none(self):
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "ffprobe"),
            ):
                assert probe.probe_input_codec("in.mp4", 5) is None


class TestProbePacketCount:
    """-count_packets 是真实帧数的低成本来源，探测失败必须安静回落。"""

    def test_returns_packet_count(self, ffmpeg_mgr):
        payload = '{"streams":[{"nb_read_packets":"474"}]}'
        with patch("subprocess.run", return_value=MagicMock(stdout=payload)):
            assert probe.probe_packet_count(ffmpeg_mgr.video_in, 10.0) == 474

    def test_uses_count_packets_not_count_frames(self, ffmpeg_mgr):
        """必须用 -count_packets。

        -count_frames 在长素材上比压制本身还慢（实测 1212s 素材 165.7s），
        而 -count_packets 只要 0.53s，两者结果一致。
        """
        payload = '{"streams":[{"nb_read_packets":"1"}]}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=payload)
            probe.probe_packet_count(ffmpeg_mgr.video_in, 10.0)
        cmd = mock_run.call_args[0][0]
        assert "-count_packets" in cmd
        assert "-count_frames" not in cmd

    @pytest.mark.parametrize(
        "stdout",
        [
            '{"streams":[{}]}',  # 字段缺失
            '{"streams":[]}',  # streams 为空
            "not json",  # JSON 畸形
            '{"streams":[{"nb_read_packets":"0"}]}',  # 非正
            '{"streams":[{"nb_read_packets":"abc"}]}',  # 无法转 int
        ],
    )
    def test_returns_none_on_bad_payload(self, ffmpeg_mgr, stdout):
        with patch("subprocess.run", return_value=MagicMock(stdout=stdout)):
            assert probe.probe_packet_count(ffmpeg_mgr.video_in, 10.0) is None

    def test_returns_none_on_process_failure(self, ffmpeg_mgr):
        with patch("subprocess.run", side_effect=OSError):
            assert probe.probe_packet_count(ffmpeg_mgr.video_in, 10.0) is None


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

    def test_codec_name_is_backfilled(self, ffmpeg_mgr):
        """get_video_info 顺手记下 codec_name，硬解判据不必再起一遍 ffprobe。"""
        mock_result = MagicMock()
        mock_result.stdout = (
            '{"streams":[{"width":640,"height":360,"r_frame_rate":"25/1",'
            '"nb_frames":100,"codec_name":"hevc"}],'
            '"format":{"duration":"4.0"}}'
        )
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                ffmpeg_mgr.get_video_info()
                run_count = mock_run.call_count
        assert ffmpeg_mgr._input_codec == "hevc"
        assert ffmpeg_mgr.probe_input_codec() == "hevc"
        assert mock_run.call_count == run_count  # 回填后才不会再探

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

    def test_missing_nb_frames_uses_packet_count(self, ffmpeg_mgr):
        """nb_frames 缺失（FLV 恒如此）时改用 -count_packets 的实测帧数。

        若沿用标称推算，frames 与标称同源、二者之比必然约掉，帧率口径修正
        会退化成只消除 int() 取整误差 —— 标称明显偏离真实均值的素材修不出来。
        """
        side = [
            MagicMock(
                stdout='{"streams":[{"width":640,"height":360,'
                '"r_frame_rate":"25/1","nb_frames":null}],'
                '"format":{"duration":"4.0"}}'
            ),
            MagicMock(stdout='{"streams":[{"nb_read_packets":"97"}]}'),
        ]
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", side_effect=side):
                info = ffmpeg_mgr.get_video_info()
        assert info["frames"] == 97  # 不是 int(4.0 × 25) = 100
        assert info["fps"] == pytest.approx(24.25)  # 97 / 4.0

    def test_packet_count_unavailable_falls_back_to_estimate(self, ffmpeg_mgr):
        """包数探不到时回落到标称推算，且不能因此让整次探测失败。"""
        side = [
            MagicMock(
                stdout='{"streams":[{"width":640,"height":360,'
                '"r_frame_rate":"25/1","nb_frames":null}],'
                '"format":{"duration":"4.0"}}'
            ),
            MagicMock(stdout='{"streams":[{}]}'),
        ]
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", side_effect=side):
                info = ffmpeg_mgr.get_video_info()
        assert info["frames"] == 100
        assert info["fps"] == 25.0


class TestGetVideoInfoFrameRate:
    """get_video_info 返回的 fps 要让弹幕时间轴等于视频真实时长。"""

    def test_vfr_source_gets_real_average_fps(self, ffmpeg_mgr):
        """标称 30fps、真实均值 20fps 的素材：fps 取 frames/duration 而非标称。"""
        mock_result = MagicMock(stdout=_probe_json("30/1", 2000, "100.0"))
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", return_value=mock_result):
                info = ffmpeg_mgr.get_video_info()
        assert info["frames"] == 2000
        assert info["fps"] == 20.0
        assert info["frames"] / info["fps"] == 100.0

    def test_cfr_source_keeps_nominal_fps(self, ffmpeg_mgr):
        """标称与真实均值一致（3000 帧 / 100s = 30fps）时 fps 不变。"""
        mock_result = MagicMock(stdout=_probe_json("30/1", 3000, "100.0"))
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("subprocess.run", return_value=mock_result):
                info = ffmpeg_mgr.get_video_info()
        assert info["fps"] == 30.0


# =============================================================================
# 超时接线
# =============================================================================


class TestTimeoutPlumbing:
    """ffmpeg_timeout 必须真正驱动子进程超时。"""

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
