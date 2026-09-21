# 配置

[← 返回 README](../README.md)

**不改配置也能直接用**：不提供配置文件时程序使用内置默认值（即下表「默认值」列），这些值是针对直播素材长期调优的推荐值。需要调整时先生成一份带注释的模板：

```bash
danmakupro --init-config              # 生成到当前目录 ./danmakupro.yaml
danmakupro --init-config -c my.yaml   # 或指定路径；已存在时不覆盖，加 -f 覆盖
```

程序按以下顺序查找配置文件，**只取第一个存在的，不做多文件合并**：

| 优先级 | 位置 |
|---|---|
| 1 | `--config` / `-c` 指定的路径 |
| 2 | 当前工作目录 `./danmakupro.yaml` |
| 3 | 用户目录 `~/danmakupro.yaml` |

> 优先级 2 取决于**当前工作目录**，因此同一条命令在 A 目录与 B 目录可能加载不同配置。每次运行都会在日志中打印实际加载文件的绝对路径；未命中时提示「使用内置默认值」；`-c typo.yaml` 写错路径会给出警告，不会静默回退。

配置文件属用户私有产物：仓库与安装包都**不携带**会被自动加载的 `danmakupro.yaml`，只提供模板 `src/danmakupro/danmakupro.example.yaml`。这样某台机器上的临时调参不会被误提交，也就不会静默改变他人的运行结果。模板与内置默认值的逐字段一致性由测试断言。

## 环境变量

| 变量 | 作用 |
|---|---|
| `DANMAKUPRO_LOG_DIR` | 指定日志目录，优先级最高 |

不设该变量时，日志目录按运行形态自动选择：源码检出写到**仓库根**的 `logs/`；wheel / pip 安装后写到**用户级目录**（Windows `%LOCALAPPDATA%\DanmakuPro\logs`，其它平台 `$XDG_STATE_HOME/DanmakuPro/logs`，未设置时回落 `~/.local/state`）。

日志文件名为 `danmakupro.log`，装的是**全应用**日志（含 CLI、配置加载、画面合成、ffmpeg 子进程各模块，不只 ffmpeg）。每次运行启动时会打印日志文件路径（未设置环境变量时即绝对路径），单文件超过 10 MB 轮转、最多保留 7 个文件。

> 早期实现一律按 `Path(__file__)` 往上数三级猜「项目根」。这在 src 布局的源码检出里恰好成立，但安装后代码在 `site-packages` 下，同样三级得到的是 Python 自己的 `Lib\` —— 日志既看不见，系统级安装时还会因无写权限在启动第一步就 `PermissionError`。

## 参数表

下表列出所有可配置字段及其默认值（40 项，5 个分组）。

> 本表是内置默认值与模板的镜像，供阅读参考；改 `src/danmakupro/config/models.py` 的默认值时请一并更新本表 —— 模板那边有 `tests/test_config_example.py` 守着，本表没有。

### 布局样式 (style)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `danmaku_x` | 35 | 弹幕起始 X 坐标（像素） |
| `layer_width_extra` | 100 | 渲染层额外宽度（像素） |
| `bubble_padding_x` | 14 | 气泡水平内边距（像素） |
| `bubble_padding_y` | 5 | 气泡垂直内边距（像素） |
| `bubble_row_gap` | 5 | 气泡行间距（像素） |
| `bubble_vertical_gap` | 4 | 气泡垂直间距（像素） |
| `bubble_multiline_radius` | 14.0 | 多行气泡圆角半径（像素） |
| `gift_spacing` | 6 | 礼物图标间距（像素） |
| `emoji_spacing` | 4 | Emoji 间距（像素） |
| `font_size` | 25 | 字体大小（pt） |
| `fade_out_zone` | 10.0 | 淡出区域高度（像素）；`0` 表示不淡出（到界即消失）。不得为负 |
| `bubble_bg_color` | `[20, 20, 20, 127]` | 气泡背景 RGBA（0~255） |
| `username_color` | `[135, 206, 250]` | 用户名颜色 RGB（0~255） |
| `text_color` | `[255, 255, 255]` | 正文颜色 RGB（0~255） |
| `gift_color` | `[255, 255, 150]` | 礼物弹幕文字颜色 RGB（0~255） |

### 布局比例 (ratio)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_text_rows` | 8 | 文本弹幕最多显示行数 |
| `max_gift_rows` | 2 | 礼物弹幕最多显示行数 |
| `text_width_ratio` | 0.825 | 文本弹幕最大宽度比例 |
| `bottom_margin` | 22 | 底部边距（像素） |

### 动画参数 (animation)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `text_damping_factor` | 0.25 | 文本弹幕移动阻尼系数（0~1，越大越快） |
| `gift_damping_factor` | 0.25 | 礼物弹幕移动阻尼系数（0~1，越大越快） |
| `text_spawn_interval` | 0.5 | 文本弹幕基础发射间隔（秒） |
| `text_spawn_batch_size` | 3 | 文本弹幕每次发射数量 |
| `gift_spawn_interval` | 0.5 | 礼物弹幕基础发射间隔（秒） |
| `gift_spawn_batch_size` | 2 | 礼物弹幕每次发射数量 |
| `max_spawn_latency` | 2.0 | 有界延迟自适应：积压时按此目标时长收紧间隔（秒），`null` 禁用 |
| `gift_dwell_time` | 5.0 | 礼物停留时间（秒），null=永不消失 |
| `min_gift_price` | 1.0 | 最低礼物价格过滤（元），0 = 不过滤 |

### 编码参数 (encode)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `gpu_preset` | "p4" | NVIDIA NVENC 预设（p1~p7） |
| `gpu_cq` | 23 | NVIDIA NVENC CQ 质量（1~51，越小越好） |
| `qsv_preset` | "medium" | Intel QSV 预设 |
| `qsv_quality` | 23 | Intel QSV 质量（1~51，越小越好） |
| `cpu_preset` | "veryfast" | libx264 / libx265 / libsvtav1 预设 |
| `cpu_crf` | 23 | CPU 编码 CRF 质量（0~51，越小越好） |
| `cpu_min_reserve_threads` | 2 | CPU 编码保留线程数 |

#### `--encode` 与硬解回退

| 取值 | 编码器 | 管线 |
|------|--------|------|
| `h264` | libx264 | CPU（默认） |
| `h264_nvenc` | h264_nvenc | GPU / NVENC |
| `h264_qsv` | h264_qsv | Intel QSV |
| `h265` | libx265 | CPU |
| `h265_nvenc` | hevc_nvenc | GPU / NVENC |
| `h265_qsv` | hevc_qsv | Intel QSV |
| `av1` | libsvtav1 | CPU |
| `av1_nvenc` | av1_nvenc | GPU / NVENC |
| `av1_qsv` | av1_qsv | Intel QSV |

不指定 `--encode` 时默认 `h264`（CPU 软解 + libx264）。硬件管线不可用时**报错退出**而非静默降级。

选中的硬件管线只在**能硬解这份输入**时才真正启用：开跑前用 `ffprobe` 取输入编码格式，和本机 `ffmpeg -decoders` 里的 `*_cuvid` / `*_qsv` 对照。不能硬解时（例如 QSV 对 MPEG-4）自动改用 CPU 并 WARNING。详见 ADR-0002。

> 早期实现在命令里写死 `-c:v h264_cuvid`，等于假定输入永远是 H.264：HEVC 实测 `rc=3199971767`、VP9 与 MPEG-4 `rc=4294967274`。现在交给 ffmpeg 依据 `-hwaccel` 自选解码器，实测 h264 / hevc / vp9 / mpeg4 四种输入均正常，且日志显示走的是 `pixfmt:cuda`（真硬解，不是软解后回拷）。

### 系统参数 (system)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `pipe_buffer_size` | 10000000 | 管道缓冲区大小（字节） |
| `ffmpeg_timeout` | 10 | 编码器探测与 ffprobe 的子进程超时（秒） |
| `stderr_thread_timeout` | 5 | 错误日志线程超时（秒） |
| `video_alignment` | 16 | 视频编码对齐字节数（须为 2 的幂） |
| `assets_dir` | "assets" | Emoji/礼物图片资源目录 |