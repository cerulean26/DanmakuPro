"""FFmpeg 进程管理器

负责构建 FFmpeg 命令行、启动进程、写入帧数据、清理资源。
"""

import json
import subprocess
import threading
from pathlib import Path

from loguru import logger

from .config import PIPE_BUFFER_SIZE, FFMPEG_TIMEOUT, STDERR_THREAD_TIMEOUT
from .layout_params import LayerParams


class FFmpegManager:
    """FFmpeg 进程管理器：构建命令、启动进程、写入帧数据、清理资源。

    GPU 加速管线：
        1. CUDA 硬件解码 (h264_cuvid)
        2. CUDA 缩放 (scale_cuda + lanczos)
        3. 弹幕层叠加 (overlay)
        4. NVENC 硬件编码 (h264_nvenc, CQP 恒定质量)
    """

    def __init__(self, video_in: str, video_out: str):
        """初始化 FFmpeg 管理器。

        Args:
            video_in: 输入视频文件路径
            video_out: 输出视频文件路径
        """
        self.video_in = video_in
        self.video_out = video_out
        self.process: subprocess.Popen | None = None
        self.stderr_thread: threading.Thread | None = None

    def get_video_info(self) -> dict[str, int | float]:
        """使用 ffprobe 获取视频的宽度、高度、帧率和总帧数。

        Returns:
            包含 w, h, fps, frames 的字典
        """
        logger.info("[3/5] 正在获取视频元数据...")
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,nb_frames:format=duration",
            "-of", "json", self.video_in,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        info = data["streams"][0]
        num, den = map(int, info["r_frame_rate"].split('/'))
        fps = num / den
        frames = int(info.get("nb_frames", 0))

        if frames == 0:
            dur = float(data["format"]["duration"])
            frames = int(dur * fps)

        logger.info(
            f"视频元数据: 尺寸={int(info['width'])}x{int(info['height'])} "
            f"| fps={fps:.2f} | 总帧数={frames}"
        )
        return {
            "w": int(info["width"]),
            "h": int(info["height"]),
            "fps": fps,
            "frames": frames,
        }

    def build_command(
        self,
        fps: float,
        w: int,
        h: int,
        layer_params: LayerParams,
    ) -> list[str]:
        """构建 FFmpeg 命令行参数。

        Args:
            fps: 视频帧率
            w: 视频宽度
            h: 视频高度
            layer_params: 渲染层参数

        Returns:
            FFmpeg 命令参数列表
        """
        lp = layer_params

        return [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-hwaccel_output_format", "cuda",
            "-c:v", "h264_cuvid",
            "-i", self.video_in,
            "-f", "rawvideo",
            "-pix_fmt", "bgra",
            "-s", f"{lp.layer_w}x{lp.layer_h}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-filter_complex",
            (
                f"[0:v]scale_cuda=w={w}:h={h}:format=yuv420p:interp_algo=lanczos,"
                f"hwdownload,format=yuv420p[bg];"
                f"[1:v]format=yuva420p[fg];"
                f"[bg][fg]overlay=x={lp.layer_x}:y={lp.layer_y}[out]"
            ),
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-cq:v", "23",
            "-rc:v", "constqp",
            "-c:a", "copy",
            self.video_out,
        ]

    def start(self, ffmpeg_cmd: list[str]) -> None:
        """启动 FFmpeg 进程和 stderr 读取线程。

        Args:
            ffmpeg_cmd: FFmpeg 命令参数列表
        """
        self.process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=PIPE_BUFFER_SIZE,
        )

        def _read_stderr():
            assert self.process is not None
            assert self.process.stderr is not None
            for line in self.process.stderr:
                line_str = line.decode("utf-8", errors="replace").rstrip("\n\r")
                if line_str:
                    logger.debug(line_str)

        self.stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        self.stderr_thread.start()
        logger.info("FFmpeg 进程已启动")

    def write_frame(self, data: memoryview) -> None:
        """向 FFmpeg 管道写入一帧数据。

        Args:
            data: 帧的原始像素数据

        Raises:
            RuntimeError: FFmpeg 进程的 stdin 未初始化
        """
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("FFmpeg 进程的 stdin 未初始化")
        self.process.stdin.write(data)

    def cleanup(self) -> None:
        """清理资源：关闭 FFmpeg 进程并等待日志线程。"""
        if self.process:
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except (OSError, BrokenPipeError) as e:
                    logger.warning(f"关闭 FFmpeg stdin 时出错: {e}")

            return_code = -255
            try:
                return_code = self.process.wait(timeout=FFMPEG_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg 进程未在预期时间内退出，强制终止...")
                try:
                    self.process.kill()
                    return_code = self.process.wait()
                except ProcessLookupError:
                    logger.warning("FFmpeg 进程已不存在")
                except Exception as e:
                    logger.error(f"强制终止 FFmpeg 进程时出错: {e}")
            except Exception as e:
                logger.error(f"等待 FFmpeg 进程结束时出错: {e}")

            if return_code == 0:
                logger.success(f"压制圆满完成！输出文件: {self.video_out}")
                out_path = Path(self.video_out)
                if out_path.exists():
                    file_size = out_path.stat().st_size
                    logger.info(f"文件大小: {file_size / (1024 * 1024):.2f} MB")
            else:
                logger.error("压制失败！请检查 ffmpeg.log 获取详细错误信息")

        if self.stderr_thread and self.stderr_thread.is_alive():
            self.stderr_thread.join(timeout=STDERR_THREAD_TIMEOUT)