"""commands 模块单元测试：三条管线的命令行构建。

经 FFmpegManager.build_command 门面进入 —— 门面按 active_pipeline 分发到
commands.build_command，断言留在这一层可以一并守住分发本身。
"""

from danmakupro.config.models import EncodeMode
from danmakupro.layout.params import LayerParams


class TestBuildCommand:
    def test_cpu_command(self, ffmpeg_mgr):
        lp = LayerParams(layer_w=1920, layer_h=1080, layer_x=0, layer_y=0)
        cmd = ffmpeg_mgr.build_command(30, 1920, 1080, lp)
        assert cmd[0] == "ffmpeg"
        assert "libx264" in cmd
        assert "pipe:0" in cmd

    def test_gpu_command(self, ffmpeg_mgr):
        ffmpeg_mgr.active_pipeline = EncodeMode.H264_NVENC
        lp = LayerParams(layer_w=1920, layer_h=1080, layer_x=0, layer_y=0)
        cmd = ffmpeg_mgr.build_command(30, 1920, 1080, lp)
        assert "h264_nvenc" in cmd
        assert "cuda" in cmd

    def test_qsv_command(self, ffmpeg_mgr):
        ffmpeg_mgr.active_pipeline = EncodeMode.H264_QSV
        lp = LayerParams(layer_w=1920, layer_h=1080, layer_x=0, layer_y=0)
        cmd = ffmpeg_mgr.build_command(30, 1920, 1080, lp)
        assert "h264_qsv" in cmd

    def test_gpu_command_does_not_force_input_decoder(self, ffmpeg_mgr):
        """GPU 命令不得在输入侧写死解码器。

        写死 `-c:v h264_cuvid` 时，HEVC / VP9 / MPEG4 输入在绑定 scale_cuda
        前就失败（本机实测 HEVC rc=3199971767、VP9 与 MPEG4 rc=4294967274），
        交给 -hwaccel cuda 自选才算得通。输出编码器仍须是 h264_nvenc。
        """
        ffmpeg_mgr.active_pipeline = EncodeMode.H264_NVENC
        lp = LayerParams(layer_w=1920, layer_h=1080, layer_x=0, layer_y=0)
        cmd = ffmpeg_mgr.build_command(30, 1920, 1080, lp)
        assert "-c:v" not in cmd[: cmd.index("-i")]
        assert "h264_nvenc" in cmd

    def test_qsv_command_does_not_force_input_decoder(self, ffmpeg_mgr):
        """同 GPU：输入侧不写死 h264_qsv，输出侧照旧用 h264_qsv 编码。"""
        ffmpeg_mgr.active_pipeline = EncodeMode.H264_QSV
        lp = LayerParams(layer_w=1920, layer_h=1080, layer_x=0, layer_y=0)
        cmd = ffmpeg_mgr.build_command(30, 1920, 1080, lp)
        assert "-c:v" not in cmd[: cmd.index("-i")]
        assert "h264_qsv" in cmd
