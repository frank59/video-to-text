# Video to Text - 视频转文字工具

支持抖音、B站、YouTube 视频链接，自动生成带时间戳的文字稿，并通过 AI 总结内容、提炼知识点。

## 功能

- **多平台支持**: 抖音、Bilibili、YouTube 视频链接自动识别
- **语音转文字**: 本地 faster-whisper 模型，带段落时间戳，支持中英日韩等语言
- **纯文字稿**: 不含时间戳的纯文本版本，方便阅读和二次编辑
- **语言学习稿**: 非中文视频自动生成逐句中文翻译 + 核心词汇表，适合语言学习
- **AI 内容总结**: 调用阿里百炼 qwen3.5-plus 模型，生成结构化总结（一句话概述、核心要点、详细知识点、金句摘录）
- **流式输出**: 转录进度实时显示，AI 总结与学习稿逐字流式渲染
- **文件导出**: 支持下载 SRT 字幕文件、TXT 纯文字稿、语言学习稿 (Markdown)

## 快速开始

### 环境要求

- Python 3.10+
- ffmpeg（macOS 通过 `brew install ffmpeg` 安装）

### 安装

```bash
git clone https://github.com/frank59/video-to-text.git
cd video-to-text
pip install -r requirements.txt
```

### 配置

复制环境变量模板并填入你的 API Key：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```
DASHSCOPE_API_KEY=sk-your-api-key-here
```

API Key 获取地址: https://dashscope.console.aliyun.com/

### 启动

**Web 界面模式：**

```bash
python app.py
```

浏览器访问 http://localhost:7860

**命令行模式：**

```bash
python app.py "https://www.youtube.com/watch?v=xxx"
python app.py "https://www.bilibili.com/video/BVxxx" --model large-v3 --language zh
```

完整参数：

| 参数 | 说明 |
|------|------|
| `url` | 视频链接（必填） |
| `--model` | Whisper 模型大小 (tiny/base/small/medium/large-v3) |
| `--language` | 语言代码 (auto/zh/en/ja/ko) |
| `--output-dir` | 输出目录 |
| `--api-key` | 覆盖 DASHSCOPE_API_KEY 环境变量 |

## 项目结构

```
video-to-text/
├── app.py                  # 应用入口 (Web + CLI)
├── config.py               # 配置管理
├── requirements.txt        # Python 依赖
├── core/
│   ├── downloader.py       # 视频下载 & 音频提取 (yt-dlp)
│   ├── transcriber.py      # 语音转文字 (faster-whisper)
│   ├── summarizer.py       # AI 内容总结 (OpenAI 兼容接口)
│   └── pipeline.py         # 全流程编排 & 进度管理
├── utils/
│   ├── url_parser.py       # URL 验证 & 平台识别
│   └── formatter.py        # 时间戳格式化 & 文稿渲染
├── prompts/
│   ├── summarize.py        # 中文总结 Prompt 模板
│   └── learning.py         # 语言学习稿 Prompt 模板（逐句翻译 + 词汇表）
└── doc/
    └── processing-flow.md  # 处理流程详解
```

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| Web UI | Gradio | 流式输出、进度条、Tabs 布局 |
| 视频下载 | yt-dlp | 支持 1000+ 视频平台 |
| 语音转文字 | faster-whisper | CTranslate2 加速，内置 VAD 静音检测 |
| 内容总结 | qwen3.5-plus | 阿里百炼平台，OpenAI 兼容接口 |
| 语言学习 | qwen3.5-plus | 逐句翻译 + 核心词汇表（非中文视频） |

## 配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DASHSCOPE_API_KEY` | (必填) | 阿里百炼 API Key |
| `DASHSCOPE_BASE_URL` | `https://coding.dashscope.aliyuncs.com/v1` | API 地址 |
| `DASHSCOPE_MODEL` | `qwen3.5-plus` | LLM 模型 |
| `WHISPER_MODEL_SIZE` | `medium` | Whisper 模型大小 (tiny/base/small/medium/large-v3) |
| `WHISPER_COMPUTE_TYPE` | `int8` | 量化类型 (int8/float16/float32) |
| `MAX_VIDEO_DURATION` | `14400` | 最大视频时长限制 (秒) |

## 性能参考

以 Apple M4 Pro (24GB RAM) 为例，处理一段 15 分钟的视频：

| 阶段 | 耗时 |
|------|------|
| 音频下载 | 10~30 秒 |
| 语音转录 (medium/int8) | 3~5 分钟 |
| 语言学习稿 (非中文视频) | 30~60 秒 |
| AI 总结 | 30~60 秒 |
| **合计** | **约 4~7 分钟** |

## License

MIT
