# ADR-0008：encode.ffmpeg 拆分为四个模块

- **状态**：已采纳并实施
- **日期**：2026-09-17
- **影响模块**：`encode/probe.py`（新建）、`encode/capability.py`（新建）、
  `encode/commands.py`（新建）、`encode/ffmpeg.py`、`encode/__init__.py`、
  `core/burner.py`

## 背景

`encode/ffmpeg.py` 单文件 927 行，承担五类互不相干的职责：视频元数据探测、
硬件能力探测、命令行构建、子进程生命周期管理、管线降级编排。一个文件的改动
理由有五种，`git log -S` 定位一处逻辑要在五个关注点之间翻找。

## 决策

按职责切成四个模块，依赖单向、无环：

```
probe.py      视频元数据探测           （不依赖同包其它模块）
capability.py 硬件能力探测  -> probe
commands.py   命令行构建    -> capability
ffmpeg.py     生命周期 + 编排 -> probe / capability / commands
__init__.py   仅导出 FFmpegManager
```

`FFmpegManager` 保留为**唯一对外门面**：`core/burner.py` 与 `core/pipeline.py`
的使用方式不变，新的三个模块都是无状态函数，可直接单独测试。

### 符号迁移对照

| 原位置（`ffmpeg.py`） | 现位置 |
|---|---|
| `_run_probe` | `probe.run_probe` |
| `_parse_frame_rate` | `probe.parse_frame_rate` |
| `_resolve_render_fps`（含 `_FPS_SANITY_*`） | `probe.resolve_render_fps` |
| `_probe_input_codec` | `probe.probe_input_codec` |
| `_probe_packet_count` | `probe.probe_packet_count` |
| `get_video_info` 的探测主体 | `probe.read_video_info` → `VideoInfo` |
| `_probe_encoder_available` | `capability.probe_encoder_available` |
| `_hardware_decodable_codecs` | `capability.hardware_decodable_codecs` |
| `_can_hw_decode` | `capability.can_hw_decode` |
| `_warn_hw_downgrade` | `capability.warn_hw_downgrade` |
| `_PIPELINE_LABELS` / `_HWACCEL_METHOD` / `_PIPELINE_ENCODERS` / `_HW_ENCODER_LABELS` / `_DECODER_LINE_RE` | `capability.*`（去掉下划线，跨模块引用） |
| `_assemble_command` / `_build_gpu_command` / `_build_qsv_command` / `_build_cpu_command` | `commands` 同名（去下划线） |
| `_PROBE_TIMEOUT_MIN` / `_FPS_LOG_TOLERANCE` | `probe.*` |

**仍留在 `ffmpeg.py`**：`FFmpegManager` 全部 15 个方法，以及模块级
`_check_encoder` 与 `_probe_encode_pipeline`（后者带 `lru_cache`）。

## 依据（实测）

### 规模

| 文件 | 总行 | 代码行 | 顶层定义 |
|---|---|---|---|
| `probe.py` | 281 | 227 | 7 |
| `capability.py` | 169 | 131 | 4 |
| `commands.py` | 202 | 177 | 6 |
| `ffmpeg.py` | **430** | 333 | 3 |
| `__init__.py` | 9 | 6 | 0 |

最大文件 927 → 430 行（−54%）。总行数 927 → 1091（+164），增量来自模块
docstring、跨模块 import 与 `VideoInfo` / `CommandInputs` 两个承载结构。

### 等价性

- **命令行逐字比对**：`.workbuddy/_verify_split_equiv.py` 把工作区的
  `ffmpeg.py` 临时换回 HEAD 版本跑一遍 `build_command`，再换回当前版本跑一遍，
  三条管线输出 **`ALL IDENTICAL`**（GPU 35 / QSV 33 / CPU 31 个 token）。
- **真机压制**：NVENC 自动检测、474 帧、弹幕 37/37 + 礼物 1/1，产物
  1088x1920 / 474 帧 / 23.700s 与输入一致。
- **测试**：435 passed / 97.03%（不含 slow）/ 439 / 97.15%（含 slow），用例数与
  拆前**完全相同**；`probe` / `capability` / `commands` / `ffmpeg` 四个模块均 100% 覆盖。

## 后果

- **测试只改了绑定路径，没改任何断言**：`patch("danmakupro.encode.ffmpeg._x")`
  一类目标随实现迁到新模块，`patch.object(FFmpegManager, ...)` 因为名字仍在类上
  而**一行未动**。
- **为新模块保留了少量薄壳**：`FFmpegManager.get_video_info` / `build_command` /
  `probe_input_codec` 现在是转发。这是有意的 —— 它们是对外 API，且测试有 20 余处
  `patch.object` 打在这些名字上；改成「管线 → 函数」映射表会让引用在导入时固化、
  使 patch 失效。
- **`_probe_encode_pipeline` 与 `_check_encoder` 未迁走**：两者要调用
  `FFmpegManager._check_nvenc_available` 这类**可被运行期替换**的入口（测试靠
  `patch.object` 驱动降级路径）。迁到 `capability.py` 会造成反向依赖或需要依赖
  注入改写缓存键，收益不抵风险。
- **430 行仍高于拆前预估的「约 300 行」**：剩下的是一次压制的完整生命周期
  （启停、写帧、收尾、限速、状态标记）与门面转发，再拆只会产生更多薄壳层。
- 依赖方向单向：`probe ← capability ← commands ← ffmpeg ← __init__`，
  `pyright` / `ruff` 无告警，运行期无循环导入。

## 后续变更

`ADR-0001` / `ADR-0002` 中「影响模块」一栏列的仍是从前的位置，其中
`_resolve_render_fps`、`_probe_packet_count`、`_build_*_command`、
`_hardware_decodable_codecs` 等已按上表迁走；两条 ADR 的决策与论据均继续有效。

**测试文件同步拆分**（2026-09-17）：`test_ffmpeg.py` 原是一份 1162 行的文件，
测着拆后的四个模块，已按「被测实现所在模块」重排为 `test_probe.py` /
`test_capability.py` / `test_commands.py` + `test_ffmpeg.py`（660 行），
用例总数与断言均未变；`ffmpeg_mgr` fixture 因四文件共用上移到 `conftest.py`。
归属取舍与守恒验证见 `.workbuddy/reviews/2026-09-16-project-code-audit.md` §9.10。
