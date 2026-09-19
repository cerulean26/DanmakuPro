# ADR-0002：GPU / QSV 的输入解码器不指定，交由 ffmpeg 自选

- **状态**：已采纳并实施
- **日期**：2026-09-16
- **影响模块**：`encode/ffmpeg.py`（`_build_gpu_command`、`_build_qsv_command`、
  `_probe_encode_pipeline`、`probe_input_codec`、`_hardware_decodable_codecs`）

## 背景

原实现在输入侧写死 `-c:v h264_cuvid`（GPU）与 `-c:v h264_qsv`（QSV）。只要输入不是
H.264，命令在把流绑到 `scale_cuda` 之前就失败，且 `--encode auto` 没有回退 CPU 的路径。
而 `validate_video_input` 允许 `.mkv` / `.webm` / `.mov`，`.webm` 几乎必然是 VP8/VP9 ——
属于**声明支持、实际必失败**。

原故障实测（本机 NVENC 与 QSV 均可用）：

| 输入编码 | GPU 路径 | CPU 路径 |
|---|---|---|
| h264 | rc=0 | rc=0 |
| hevc | **rc=3199971767** | rc=0 |
| vp9 | **rc=4294967274** | rc=0 |

ffmpeg 原始报错：

```
[dec:h264_cuvid @ ...] Error while opening decoder: Invalid data found when processing input
[fc#0 @ ...] Error binding an input stream to complex filtergraph input scale_cuda:default.
```

## 决策

1. **不指定输入解码器**，交给 ffmpeg 依据 `-hwaccel` 自选（`_build_*_command` 去掉
   `-c:v <decoder>`）。输出侧编码器不受影响，仍按管线指定 `h264_nvenc` / `h264_qsv`。
2. **开跑前加一道可硬解判据**：`ffprobe` 取输入 `codec_name` + 解析本机
   `ffmpeg -decoders` 里支持该编码的 `*_cuvid` / `*_qsv` 条目；不可硬解则回落到 CPU
   并 WARNING；auto 模式下先试另一条硬件管线。

## 依据（实测）

三条候选里选了「不指定」，而不是审查报告最初建议的「维护编码→解码器映射表」：

| 方案 | 1080p/20s 耗时 | 是否真硬解 |
|---|---|---|
| 自动选择（不写 `-c:v`） | 5.69s | 是，日志 `Selecting decoder 'hevc' because of requested hwaccel method cuda` + `pixfmt:cuda` |
| 显式 `<codec>_cuvid` | 5.80s | 是，同上 |
| CPU | — | — |

（每命令跑两遍取第二遍，消除 CUDA 初始化偏差。）

两者性能无差异，但「不指定」免去维护映射表，也不必假设用户的 ffmpeg 编了哪些
`*_cuvid` —— 这份假设在换机器时最容易失效。

**为什么光靠自动选择不够**：QSV 对 MPEG-4 无硬解，此时两种写法都失败。必须有第二条
防线，即上面的开跑前判据。

**两种「不知道」都选择不降级**：输入编码探不到、硬解清单探测失败时，维持用户请求的
管线，把真正的错误留给后续 `get_video_info()` 抛出 —— 否则会把能走 GPU 的任务一律拖
到 CPU，平白丢掉硬加速。

## 附：ffmpeg 侧「自选」的实际机制（实测）

不写 `-c:v` 之后，选择过程发生在 ffmpeg 内部，共三步：

1. **取通用解码器，不是硬解解码器**。解复用拿到流的 `codec_id`，由
   `avcodec_find_decoder()` 返回通用解码器，名字就是 `h264` / `mpeg4`。
   debug 日志（`source/1.flv`，`-hwaccel cuda`）：
   `[vist#0:0/h264] Selecting decoder 'h264' because of requested hwaccel method cuda`。
2. **问这个解码器有没有对应的硬件实现**。因为指定了 `-hwaccel cuda`，打开解码器时走
   hwaccel 框架，日志：
   `[h264] Format cuda requires hwaccel h264_nvdec initialisation.`
   随后 `Loaded lib: nvcuvid.dll` 并调用 `cuvidCreateDecoder` 等符号 —— 即
   **NVDEC 后端接管了通用解码器**，输出 `pixfmt:cuda`（帧留在显存）。
   换言之：既不是换用 `h264_cuvid`，也不经过上面那张 `*_cuvid` 清单。
3. **找不到后端时静默软解**。这是最需要警惕的一点：ffmpeg 不报错、不改退出码、
   不给任何提示。实测 mpeg4 输入（QSV 无 mpeg4 硬解）配 `-hwaccel qsv`：
   输出 `pixfmt:yuv420p`、`speed=36.4x`、**rc=0**，日志里没有一个 warning。
   只有接上本项目那样的滤镜链才会暴露：同一输入加 `hwdownload,format=nv12` 后
   **rc=4294967256（-40）**，报 `Error reinitializing filters!` /
   `Task finished with error code: -40 (Function not implemented)`。

第 3 步解释了开跑前判据为什么必须存在 —— 失败信息完全指不出「根因是没有硬解」。
判据的正面情形也已实测：mpeg4 + `-hwaccel cuda` 输出 `pixfmt:cuda`，同样走通。

**一处口径差异（本机结论未受影响，但需留意）**：`_hardware_decodable_codecs()` 解析的
是 `ffmpeg -decoders` 里的 `*_cuvid` / `*_qsv` **独立解码器**清单，而第 2 步真正生效的
是通用解码器的 `*_nvdec` 后端 —— `h264_nvdec` 并不出现在 `-decoders` 里（它属于
hwaccel 而非解码器）。两者在 ffmpeg 构建中通常成对出现（同源于 nvcodec），本机核对
h264 / hevc / vp9 / mpeg4 四例结论一致，故判据有效；但严格讲这是两份不同的清单，
换 ffmpeg 构建时若出现只有其一的情形，判据会偏向保守（误判不可硬解 → 落 CPU）。

## 后果

- HEVC / VP9 / MPEG-4 输入在 auto 下要么走成、要么自动落 CPU，不再出现必失败。
- 若在 `_build_gpu_command` 里写死解码器，非 H.264 输入会在绑定 `scale_cuda` 前就失败
  （HEVC 实测 rc=3199971767）；去掉后 h264/hevc/vp9/mpeg4 四种输入均走通，且日志仍是
  `pixfmt:cuda`（真硬解，非软解后回拷）。
- 探测要启动 2~4 个 ffmpeg 子进程，本机实测耗时：auto 1.03s / gpu 1.45s / qsv 2.63s
  （cpu 无需探测，0.04s）。因此 `_active_pipeline` 采用惰性解析 —— 构造对象时不起子进程，
  首次读取属性时才探测，使「只构造不使用」的场景（GUI 建好对象后用户取消、单测只断言
  构造参数）不必白付这份代价。
- 每次压制多一次 ffprobe 子进程 + 一次 `-decoders` 解析（后者参与进程级缓存）。
