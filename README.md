# DanmakuPro

抖音直播弹幕压制工具 — 将直播录像与弹幕 XML 合成，以半透明圆角气泡形式将弹幕永久烧录到视频中。

## 特性

- **GPU 硬件加速** — CUDA 解码 (NVDEC) + NVENC 编码，全程 GPU 管线；支持 QSV 和 CPU 回退
- **双区布局** — 礼物区（上方）+ 文本弹幕区（下方），互不干扰
- **空间驱动布局** — 弹幕从底部向上堆叠，含碰撞检测，互不遮挡
- **阻尼动画** — 弹幕/礼物位移带平滑插值过渡，视觉自然流畅
- **礼物停留时间** — 可配置礼物在屏幕上的最大停留时长，超时自动消失
- **Emoji 内联渲染** — 支持 `[笑哭]` `[666]` 等弹幕表情，按需懒加载
- **礼物过滤** — 可按礼物价格阈值过滤，仅保留有价值的礼物弹幕
- **预渲染缓存** — 每条弹幕预渲染为 QImage，后续帧仅需一次 drawImage
- **字体回退** — 多字体族链式匹配，未覆盖字符自动回退到扩展字体

## 环境要求

- **Python** ≥ 3.13
- **FFmpeg**（需编译 CUDA、NVDEC、NVENC 支持以启用 GPU 加速）
- **NVIDIA 显卡**（可选，驱动支持 CUDA 时启用 GPU 编码）
- 依赖包：`lxml` `PySide6` `loguru` `tqdm` `pyyaml`

## 安装

```bash
# 克隆项目
git clone https://github.com/cerulean26/DanmakuPro.git
cd DanmakuPro

# 使用 uv 安装依赖
uv sync

# 或 pip 安装
pip install .
```

## 快速开始

### 1. 准备素材

将直播录像和抖音弹幕 XML 放入 `source/` 目录，Emoji 和礼物图片放入 `assets/` 目录。

### 2. 运行

```bash
# CLI 模式
danmakupro source/视频.mp4 source/弹幕.xml

# 指定编码模式和输出路径
danmakupro source/视频.mp4 source/弹幕.xml --encode gpu -o output.mp4 -f

# 使用自定义配置文件
danmakupro source/视频.mp4 source/弹幕.xml -c danmakupro.yaml
```

## 布局说明

弹幕渲染区域分为上下两个独立区域：

```
┌──────────────────────────────┐
│         礼物区（上方）         │  ← 可配置行数（默认 2 行）
│   礼物弹幕从下往上堆叠        │     独立阻尼、淡出、停留时间
├──────────────────────────────┤
│        文本弹幕区（下方）      │  ← 可配置行数（默认 4 行）
│   文本弹幕从下往上堆叠        │     含碰撞检测与推挤
└──────────────────────────────┘
```

## 配置

通过 `danmakupro.yaml` 配置文件调整行为，未指定的字段使用内置默认值。

### 布局样式 (style)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `danmaku_x` | 30 | 弹幕起始 X 坐标（像素） |
| `layer_width_extra` | 100 | 渲染层额外宽度（像素） |
| `bubble_padding_x` | 14 | 气泡水平内边距（像素） |
| `bubble_padding_y` | 5 | 气泡垂直内边距（像素） |
| `bubble_row_gap` | 5 | 气泡行间距（像素） |
| `bubble_vertical_gap` | 4 | 气泡垂直间距（像素） |
| `bubble_multiline_radius` | 14.0 | 多行气泡圆角半径（像素） |
| `gift_spacing` | 6 | 礼物图标间距（像素） |
| `emoji_spacing` | 4 | Emoji 间距（像素） |
| `font_size` | 25 | 字体大小（pt） |
| `fade_out_zone` | 30.0 | 淡出区域高度（像素） |

### 布局比例 (ratio)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_text_rows` | 4 | 文本弹幕最多显示行数 |
| `max_gift_rows` | 2 | 礼物弹幕最多显示行数 |
| `text_width_ratio` | 0.8 | 文本弹幕最大宽度比例 |
| `bottom_margin` | 22 | 底部边距（像素） |

### 动画参数 (animation)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `text_damping_factor` | 0.25 | 文本弹幕移动阻尼系数（0~1，越大越快） |
| `gift_damping_factor` | 0.25 | 礼物弹幕移动阻尼系数（0~1，越大越快） |
| `text_spawn_interval` | 0.5 | 文本弹幕发射间隔（秒） |
| `text_spawn_batch_size` | 3 | 文本弹幕每次发射数量 |
| `gift_spawn_interval` | 0.5 | 礼物弹幕发射间隔（秒） |
| `gift_spawn_batch_size` | 2 | 礼物弹幕每次发射数量 |
| `gift_dwell_time` | 5.0 | 礼物停留时间（秒），null=永不消失 |
| `min_gift_price` | 1.0 | 最低礼物价格过滤（元） |

### 编码参数 (encode)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `gpu_preset` | "p4" | NVIDIA NVENC 预设（p1~p7） |
| `gpu_cq` | 23 | NVIDIA NVENC CQ 质量（1~51，越小越好） |
| `qsv_preset` | "medium" | Intel QSV 预设 |
| `qsv_quality` | 23 | Intel QSV 质量（1~51，越小越好） |
| `cpu_preset` | "veryfast" | libx264 预设 |
| `cpu_crf` | 23 | libx264 CRF 质量（0~51，越小越好） |
| `cpu_min_reserve_threads` | 2 | CPU 编码保留线程数 |

### 系统参数 (system)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `pipe_buffer_size` | 10000000 | 管道缓冲区大小（字节） |
| `pipe_queue_size` | 16 | 异步写入队列大小 |
| `ffmpeg_timeout` | 10 | FFmpeg 启动超时（秒） |
| `stderr_thread_timeout` | 5 | 错误日志线程超时（秒） |
| `video_alignment` | 16 | 视频编码对齐字节数（须为 2 的幂） |
| `max_queue_frames` | 64 | 异步写入队列最大帧数 |

## 处理流程

```
XML 解析 → 资源加载 → 视频信息获取 → 弹幕布局计算 → 逐帧渲染 → FFmpeg 合成
```

1. 流式解析抖音弹幕 XML，提取 `<d>` 和 `<gift>` 标签
2. 加载 Emoji 和礼物图片资源，按需加载字体
3. 通过 ffprobe 获取视频宽高、帧率、总帧数
4. 预创建所有弹幕对象，计算布局参数
5. 构建 FFmpeg 编码管线（自动检测 GPU / QSV / CPU）
6. 逐帧渲染弹幕气泡图层，通过管道送入 FFmpeg，输出压制视频

## 项目结构

```
DanmakuPro/
├── src/danmakupro/           # 核心包
│   ├── cli.py                # CLI 入口
│   ├── errors.py             # 错误类型与处理
│   ├── logger_config.py      # 日志配置
│   ├── config/               # 配置模块
│   │   ├── models.py         # 配置数据模型
│   │   └── loader.py         # YAML 配置加载
│   ├── core/                 # 核心引擎
│   │   └── burner.py         # 压制引擎（编排管线）
│   ├── input/                # 输入模块
│   │   ├── models.py         # 弹幕事件与渲染数据模型
│   │   └── parser.py         # 抖音 XML 流式解析
│   ├── layout/               # 布局模块
│   │   ├── engine.py         # 布局计算与碰撞检测
│   │   └── params.py         # 布局参数数据类
│   ├── render/               # 渲染模块
│   │   ├── renderer.py       # 画布管理与帧渲染
│   │   └── assets.py         # 资源加载（字体、图片）
│   ├── encode/               # 编码模块
│   │   └── ffmpeg.py         # FFmpeg 进程管理
│   └── utils/                # 工具模块
│       ├── helpers.py        # 通用工具函数
│       └── validation.py     # 输入输出校验
├── tests/                    # 测试
├── assets/                   # Emoji、礼物 PNG 和字体
│   ├── emoji/
│   ├── gift/
│   └── fonts/
├── pyproject.toml
└── README.md
```

## 许可证

GPLv3