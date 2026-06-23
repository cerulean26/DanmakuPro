# DanmakuPro

抖音直播弹幕压制工具 — 将直播录像与弹幕 XML 合成，以半透明圆角气泡形式将弹幕永久烧录到视频中。

## 特性

- **GPU 硬件加速** — CUDA 解码 (NVDEC) + NVENC 编码，全程 GPU 管线
- **双区布局** — 礼物区（上方）+ 文本弹幕区（下方），互不干扰
- **空间驱动布局** — 弹幕从底部向上堆叠，含碰撞检测，互不遮挡
- **阻尼动画** — 弹幕/礼物位移带平滑插值过渡，视觉自然流畅
- **礼物停留时间** — 可配置礼物在屏幕上的最大停留时长，超时自动消失
- **Emoji 内联渲染** — 支持 `[笑哭]` `[666]` 等弹幕表情，按需懒加载
- **礼物过滤** — 可按礼物价格阈值过滤，仅保留有价值的礼物弹幕
- **预渲染缓存** — 每条弹幕预渲染为 QImage，后续帧仅需一次 drawImage
- **字体回退** — 多字体族链式匹配，未覆盖字符自动回退到系统字体

## 环境要求

- **Python** ≥ 3.13
- **FFmpeg** ≥ 8.0（需编译 CUDA、NVDEC、NVENC 支持）
- **NVIDIA 显卡**（驱动支持 CUDA）
- 依赖包：`lxml` `PySide6` `loguru` `tqdm`

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

将直播录像和弹幕 XML 放入 `source/` 目录，Emoji 和礼物图片放入 `assets/` 目录。

### 2. 运行

```bash
# CLI 模式
danmakupro source/视频.mp4 source/弹幕.xml

# GUI 模式（弹出文件选择器）
danmakupro-gui
```

## 布局说明

弹幕渲染区域分为上下两个独立区域：

```
┌──────────────────────────────┐
│         礼物区（上方）         │  ← 12% 屏幕高度
│   礼物弹幕从下往上堆叠        │     独立阻尼、淡出、停留时间
├──────────────────────────────┤
│        文本弹幕区（下方）      │  ← 最多 30% 屏幕高度
│   文本弹幕从下往上堆叠        │     含碰撞检测与推挤
└──────────────────────────────┘
```

## 配置

修改 `src/danmakupro/config.py` 中的常量即可调整行为：

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `FONT_SIZE` | 25 | 弹幕字号 |
| `DANMAKU_X` | 30 | 弹幕左侧边距 |
| `BUBBLE_VERTICAL_GAP` | 8 | 弹幕间距 |
| `MAX_CONTENT_WIDTH_RATIO` | 0.8 | 最大内容宽度比例 |
| `MAX_CONTAINER_HEIGHT_RATIO` | 0.30 | 文本弹幕区高度比例 |
| `GIFT_ZONE_HEIGHT_RATIO` | 0.12 | 礼物区高度比例 |
| `DAMPING_FACTOR` | 0.15 | 文本弹幕阻尼系数 |
| `GIFT_DAMPING_FACTOR` | 0.25 | 礼物阻尼系数 |
| `GIFT_DWELL_TIME` | 5.0 | 礼物停留时间（秒），`None` 禁用 |
| `GIFT_FADE_OUT_ZONE` | 40.0 | 礼物淡出区域高度（像素） |
| `FADE_OUT_ZONE` | 30.0 | 文本弹幕淡出区域高度 |
| `MIN_GIFT_PRICE` | 0.0 | 最低礼物价格过滤（元） |

## 处理流程

```
XML 解析 → 资源加载 → 视频信息获取 → 弹幕布局计算 → 逐帧渲染 → FFmpeg 合成
```

1. 流式解析弹幕 XML，提取 `<d>` 和 `<gift>` 标签
2. 加载 Emoji 和礼物图片资源，初始化字体
3. 通过 ffprobe 获取视频宽高、帧率、总帧数
4. 预创建所有弹幕对象，计算布局参数
5. 构建 FFmpeg GPU 管线（NVDEC 解码 → scale_cuda → overlay → NVENC 编码）
6. 逐帧渲染弹幕气泡图层，通过管道送入 FFmpeg，输出压制视频

## 项目结构

```
DanmakuPro/
├── src/danmakupro/       # 核心包
│   ├── cli.py            # CLI 入口
│   ├── gui.py            # GUI 入口（文件选择器）
│   ├── burner.py         # 压制引擎（编排管线）
│   ├── models.py         # 数据模型与弹幕渲染
│   ├── parser.py         # XML 流式解析
│   ├── layout_engine.py  # 布局计算与碰撞检测
│   ├── layout_params.py  # 布局参数数据类
│   ├── renderer.py       # 画布管理与帧渲染
│   ├── asset_loader.py   # 资源加载（字体、图片）
│   ├── ffmpeg_manager.py # FFmpeg 进程管理
│   ├── config.py         # 全局常量配置
│   ├── logger_config.py  # 日志配置
│   └── utils.py          # 工具函数
├── tests/                # 测试
├── assets/               # Emoji 和礼物 PNG
│   └── fonts/            # 字体文件
├── pyproject.toml
└── README.md
```

## 许可证

GPLv3