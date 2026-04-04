# 视频转文字 -- 处理流程详解

本文档详细记录了当用户在 Web 界面提交一个视频链接后，系统内部的完整函数调用过程。

---

## 整体流程概览

```
用户点击"开始处理"
       │
       ▼
 ┌─ app.py ──────────────────────────────────────────────────────────────┐
 │  run_pipeline(url, model_size, language)                             │
 │       │                                                              │
 │       ▼                                                              │
 │  ┌─ core/pipeline.py ──────────────────────────────────────────────┐ │
 │  │  process_video(url, model_size, language)  [生成器函数]          │ │
 │  │       │                                                         │ │
 │  │       ├── 阶段1: validate_url()            ← utils/url_parser   │ │
 │  │       ├── 阶段2: download_audio()          ← core/downloader    │ │
 │  │       ├── 阶段3: transcribe()              ← core/transcriber   │ │
 │  │       ├──        格式化转录结果              ← utils/formatter    │ │
 │  │       └── 阶段4: summarize_stream()        ← core/summarizer    │ │
 │  │                                                                  │ │
 │  │  每个阶段通过 yield 向 UI 层发送进度事件                          │ │
 │  └──────────────────────────────────────────────────────────────────┘ │
 │       │                                                              │
 │       ▼                                                              │
 │  Gradio 接收 yield 的值，实时更新界面组件                             │
 └──────────────────────────────────────────────────────────────────────┘
```

---

## 阶段 0: 用户交互入口

### 文件: `app.py`

当用户在界面上点击 **"开始处理"** 按钮或在输入框按回车时，Gradio 的事件绑定触发：

```python
# app.py:167-178
submit_btn.click(
    fn=run_pipeline,                              # 绑定的处理函数
    inputs=[url_input, model_dropdown, lang_dropdown],  # 三个输入参数
    outputs=[                                     # 六个输出组件
        status_text,       # 状态文本 (Markdown)
        transcript_output, # 文字稿 (Markdown)
        summary_output,    # 内容总结 (Markdown)
        srt_download,      # SRT 字幕文件 (File)
        txt_download,      # TXT 文本文件 (File)
        result_state,      # 完整结果对象 (State)
    ],
)
```

Gradio 将用户输入的三个值传给 `run_pipeline()`，该函数是一个**生成器**，每次 `yield` 都会实时更新对应的 6 个界面组件。

### 函数: `run_pipeline()`

```
run_pipeline(url, model_size, language, progress)
  │
  ├── 空输入检查: url.strip() 为空则直接 yield 错误提示并 return
  │
  ├── 调用 process_video(url, model_size, language) 获取生成器
  │     │
  │     └── 遍历生成器产出的每个事件 (event):
  │           │
  │           ├── 如果是 PipelineProgress:
  │           │     ├── 调用 progress(percent, desc=message) 更新进度条
  │           │     ├── 从 event.transcript_md 获取文字稿 (转录完成后有值)
  │           │     ├── 从 event.partial_summary 获取流式总结 (总结阶段实时更新)
  │           │     ├── 检查 message 中是否含"错误"/"失败" → 若有则终止
  │           │     └── yield 6个组件的更新值给 Gradio
  │           │
  │           └── 如果是 PipelineResult:
  │                 └── 保存最终的完整结果对象
  │
  └── 生成导出文件:
        ├── 将 result.transcript_srt 写入临时 .srt 文件
        ├── 将 result.transcript_plain 写入临时 .txt 文件
        └── yield 最终结果（含下载文件路径）给 Gradio
```

---

## 阶段 1: URL 验证与平台识别 (进度 0% ~ 2%)

### 文件: `utils/url_parser.py`
### 调用链:

```
pipeline.process_video()
  │
  └── validate_url(url)                        # url_parser.py:54
        │
        ├── normalize_url(url)                 # url_parser.py:35
        │     │
        │     ├── urlparse(url) 解析 URL 结构
        │     ├── 如果没有 scheme，补上 "https://"
        │     ├── 检查是否为短链域名 (b23.tv, v.douyin.com)
        │     │     └── 是 → requests.head(url, allow_redirects=True)
        │     │           跟随 301/302 重定向，获取最终完整 URL
        │     └── 返回规范化后的 URL
        │
        ├── detect_platform(url)               # url_parser.py:25
        │     │
        │     └── 遍历 PLATFORM_PATTERNS 字典:
        │           ├── youtube: youtube.com/watch, youtu.be/, youtube.com/shorts/ ...
        │           ├── bilibili: bilibili.com/video/, b23.tv/
        │           └── douyin:   douyin.com/video/, v.douyin.com/, iesdouyin.com/
        │           对每个平台的正则列表做 re.search()
        │           命中则返回平台名 ("youtube"/"bilibili"/"douyin")
        │           全部未命中则返回 None
        │
        ├── platform 为 None → raise ValueError("不支持的视频链接...")
        │
        └── 返回 (normalized_url, platform)
```

**产出事件:**

| 时机 | yield 的事件 |
|------|-------------|
| 开始验证 | `PipelineProgress(percent=0%, stage="validate", message="正在验证链接...")` |
| 验证成功 | `PipelineProgress(percent=2%, stage="validate", message="识别为 youtube 视频")` |
| 验证失败 | `PipelineProgress(message="错误: 不支持的视频链接...")` → 流程终止 |

---

## 阶段 2: 视频下载与音频提取 (进度 2% ~ 20%)

### 文件: `core/downloader.py`
### 调用链:

```
pipeline.process_video()
  │
  └── download_audio(normalized_url, platform)        # downloader.py:77
        │
        ├── output_dir = config.AUDIO_OUTPUT_DIR      # 即 data/audio/
        │
        ├── _build_ydl_opts(output_dir, platform)     # downloader.py:26
        │     │
        │     ├── 设置 yt-dlp 参数:
        │     │     format: "bestaudio/best"           # 只下载最佳音频流
        │     │     outtmpl: "data/audio/%(id)s.%(ext)s"
        │     │     postprocessors:
        │     │       └── FFmpegExtractAudio → wav     # 用 ffmpeg 转为 WAV
        │     │     postprocessor_args:
        │     │       └── "-ar 16000 -ac 1"            # 16kHz 单声道 (Whisper 最优)
        │     │
        │     ├── 如果 platform == "douyin":
        │     │     └── 设置移动端 User-Agent (模拟 iPhone Safari)
        │     │
        │     └── 返回配置字典 opts
        │
        ├── 重试循环 (最多 3 次):
        │     │
        │     └── yt_dlp.YoutubeDL(opts) as ydl:
        │           │
        │           ├── ydl.extract_info(url, download=True)
        │           │     │
        │           │     ├── yt-dlp 内部流程:
        │           │     │     1. 解析 URL，识别视频平台和 ID
        │           │     │     2. 提取视频元信息 (title, duration, formats...)
        │           │     │     3. 选择最佳音频格式
        │           │     │     4. 下载音频流到 data/audio/{video_id}.{ext}
        │           │     │     5. FFmpeg 后处理: 转换为 16kHz 单声道 WAV
        │           │     │        → data/audio/{video_id}.wav
        │           │     │
        │           │     └── 返回 info 字典 (含 title, duration, id 等)
        │           │
        │           ├── 检查 duration > MAX_VIDEO_DURATION → 超限则报错
        │           │
        │           ├── 定位音频文件: data/audio/{video_id}.wav
        │           │
        │           └── 返回 DownloadResult(
        │                   audio_path="data/audio/xxx.wav",
        │                   title="视频标题",
        │                   duration=180.0,  # 秒
        │                   platform="youtube"
        │                 )
        │
        └── 失败处理:
              ├── 视频私密/不存在 → DownloadError("视频不存在或无法访问")
              ├── 地域限制       → DownloadError("该视频受地域限制")
              └── 网络错误       → 等待 2^attempt 秒后重试
```

**产出事件:**

| 时机 | yield 的事件 |
|------|-------------|
| 开始下载 | `PipelineProgress(percent=2%, stage="download", message="正在下载音频...")` |
| 下载完成 | `PipelineProgress(percent=20%, stage="download", message="下载完成: 视频标题")` |
| 下载失败 | `PipelineProgress(message="下载失败: ...")` → 流程终止 |

---

## 阶段 3: 语音转文字 (进度 20% ~ 80%)

### 文件: `core/transcriber.py`
### 调用链:

```
pipeline.process_video()
  │
  └── transcribe(audio_path, language, model_size, total_duration, progress_callback)
        │                                                         # transcriber.py:50
        │
        ├── get_model(model_size)                                 # transcriber.py:14
        │     │
        │     ├── 全局单例 _model，首次调用时加载:
        │     │     WhisperModel(
        │     │       model_size_or_path="medium",
        │     │       device="cpu",
        │     │       compute_type="int8",           # int8 量化，M4 Pro 上最快
        │     │       download_root="data/cache/"    # 模型缓存目录
        │     │     )
        │     │     (首次运行会自动从 HuggingFace 下载 ~1.5GB 模型文件)
        │     │
        │     └── 返回 WhisperModel 实例
        │
        ├── 构建转录参数:
        │     transcribe_opts = {
        │       "vad_filter": True,                  # 启用语音活动检测
        │       "vad_parameters": {
        │         "min_silence_duration_ms": 500      # 500ms 以上的静音视为断句
        │       },
        │       "language": "zh"                     # 仅在用户手动指定时设置
        │     }
        │
        ├── model.transcribe(audio_path, **transcribe_opts)
        │     │
        │     ├── faster-whisper 内部流程:
        │     │     1. ffmpeg 加载 WAV 音频到内存
        │     │     2. VAD (Silero VAD) 检测语音段，跳过静音
        │     │     3. 对每个语音段执行 Whisper 推理
        │     │     4. 返回 (segments_generator, info)
        │     │
        │     ├── info 包含:
        │     │     - language: "zh"          # 自动检测到的语言
        │     │     - language_probability: 0.95
        │     │     - duration: 180.0         # 音频总时长
        │     │
        │     └── segments_generator 是一个惰性生成器
        │           每次 next() 返回一个 Segment:
        │             Segment(start=0.0, end=3.5, text="大家好...")
        │
        ├── 遍历 segments_generator，逐个收集:
        │     for seg in result_segments:
        │       │
        │       ├── 创建 TranscriptSegment(start, end, text)
        │       │     加入 segments 列表
        │       │
        │       └── 调用 progress_callback(pct, msg):
        │             pct = seg.end / total_duration   # 当前进度
        │             msg = "正在转录... (45 段)"
        │             → 回调被 pipeline 捕获，映射到全局进度 20%~80%
        │
        ├── group_segments_into_paragraphs(segments)     # formatter.py:39
        │     │
        │     ├── 分段合并规则:
        │     │     1. 相邻 segment 间停顿 >= 2.0 秒 → 分段
        │     │     2. 累积 >= 5 个 segment → 分段
        │     │     取两者中先触发的条件
        │     │
        │     ├── 合并后生成 TranscriptParagraph:
        │     │     TranscriptParagraph(
        │     │       start=0.0,           # 段落起始时间
        │     │       end=15.3,            # 段落结束时间
        │     │       text="大家好，今天..."  # 多个 segment 的文本拼接
        │     │     )
        │     │
        │     └── 返回 List[TranscriptParagraph]
        │
        └── 返回 (segments, paragraphs)
```

### 转录完成后的格式化 (仍在 pipeline.py 中)

```
pipeline.process_video() (续)
  │
  ├── segments_to_markdown(paragraphs, always_hours)   # formatter.py:79
  │     → "**[03:45]** 大家好，今天我们来聊一下...\n\n**[04:12]** 第一个知识点是..."
  │
  ├── segments_to_plain_text(paragraphs, always_hours)  # formatter.py:102
  │     → "[03:45] 大家好，今天我们来聊一下...\n\n[04:12] 第一个知识点是..."
  │
  └── segments_to_srt(segments)                         # formatter.py:91
        → "1\n00:03:45,000 --> 00:04:11,500\n大家好...\n\n2\n..."
```

**产出事件:**

| 时机 | yield 的事件 |
|------|-------------|
| 开始转录 | `PipelineProgress(percent=20%, stage="transcribe", message="正在加载语音识别模型...")` |
| 转录完成 | `PipelineProgress(percent=80%, message="转录完成: 120 个片段, 35 个段落", transcript_md="**[00:00]** ...")` |

---

## 阶段 4: 内容总结与知识点提炼 (进度 80% ~ 100%)

### 文件: `core/summarizer.py` + `prompts/summarize.py`
### 调用链:

```
pipeline.process_video() (续)
  │
  ├── segments_to_llm_input(paragraphs, always_hours)  # formatter.py:114
  │     │
  │     └── 生成紧凑格式 (节省 token):
  │           "[03:45] 大家好，今天我们来聊一下...\n[04:12] 第一个知识点是..."
  │
  └── summarize_stream(llm_input)                      # summarizer.py:85
        │
        ├── _init_api_key()                            # summarizer.py:26
        │     └── dashscope.api_key = config.DASHSCOPE_API_KEY
        │
        ├── 判断文稿长度:
        │     │
        │     ├── 【常规路径】len(transcript) <= 100,000 字:
        │     │     │
        │     │     ├── 组装 prompt:
        │     │     │     user_prompt = SUMMARIZE_TEMPLATE.format(transcript=llm_input)
        │     │     │     ┌──────────────────────────────────────────────┐
        │     │     │     │ SUMMARIZE_TEMPLATE 内容:                     │
        │     │     │     │                                              │
        │     │     │     │ 以下是一段视频的转录文本（含时间戳）：          │
        │     │     │     │ ---                                          │
        │     │     │     │ {transcript}                                 │
        │     │     │     │ ---                                          │
        │     │     │     │ 请按以下格式对视频内容进行全面总结：            │
        │     │     │     │ ## 一句话概述                                 │
        │     │     │     │ ## 核心要点 (3-7个)                           │
        │     │     │     │ ## 详细知识点 (按主题分类，标注时间)            │
        │     │     │     │ ## 金句摘录 (3-5句，标注时间戳)               │
        │     │     │     └──────────────────────────────────────────────┘
        │     │     │
        │     │     └── _call_stream(SYSTEM_PROMPT, user_prompt)   # summarizer.py:32
        │     │           │
        │     │           ├── Generation.call(
        │     │           │     model="qwen-plus",             # 阿里百炼 qwen-plus
        │     │           │     messages=[
        │     │           │       {role: "system", content: "你是专业的视频内容分析助手..."},
        │     │           │       {role: "user",   content: user_prompt}
        │     │           │     ],
        │     │           │     stream=True,                   # 流式输出
        │     │           │     incremental_output=True         # 增量返回
        │     │           │   )
        │     │           │
        │     │           └── for response in responses:
        │     │                 yield response.output.choices[0].message.content
        │     │                 # 每次 yield 一小段文字 (如 "## 一句话概述\n本视频介绍了")
        │     │                 # → pipeline 累积并通过 PipelineProgress.partial_summary
        │     │                 #   传给 UI 实时渲染
        │     │
        │     └── 【长文稿路径】len(transcript) > 100,000 字:
        │           │
        │           ├── _split_transcript(transcript)          # summarizer.py:74
        │           │     │
        │           │     └── 按 80,000 字一块，2,000 字重叠，切分为多个 chunk
        │           │           chunk_1: transcript[0:80000]
        │           │           chunk_2: transcript[78000:158000]
        │           │           ...
        │           │
        │           ├── 逐块总结:
        │           │     for i, chunk in enumerate(chunks):
        │           │       │
        │           │       ├── yield "正在分析第 1/3 部分..."  # UI 提示
        │           │       │
        │           │       └── _call_full(SYSTEM_PROMPT, CHUNK_SUMMARIZE_TEMPLATE)
        │           │             # 非流式调用，获取每块的完整总结
        │           │             → chunk_summaries 列表
        │           │
        │           └── 合并总结:
        │                 yield "正在整合总结..."
        │                 _call_stream(SYSTEM_PROMPT, MERGE_SUMMARY_TEMPLATE)
        │                 # 流式输出最终整合的完整总结
        │
        └── pipeline 中的处理:
              for chunk in summarize_stream(llm_input):
                summary_parts.append(chunk)
                result.summary = "".join(summary_parts)
                yield PipelineProgress(
                  partial_summary=result.summary    # 实时传给 UI
                )
```

**产出事件:**

| 时机 | yield 的事件 |
|------|-------------|
| 开始总结 | `PipelineProgress(percent=80%, stage="summarize", message="正在生成内容总结...")` |
| 流式输出中 | `PipelineProgress(percent=90%, message="正在生成总结...", partial_summary="## 一句话概述\n...")` (多次) |
| 完成 | `PipelineProgress(percent=100%, message="处理完成!")` |
| 最终结果 | `PipelineResult(title, segments, paragraphs, transcript_markdown, summary, ...)` |

---

## 阶段 5: 清理与导出

### 临时文件清理 (pipeline.py)

```
pipeline.process_video() 的 finally 块:
  │
  └── cleanup_audio(audio_path)            # downloader.py:157
        └── Path(audio_path).unlink()      # 删除 data/audio/{video_id}.wav
```

### 导出文件生成 (app.py)

```
run_pipeline() (续):
  │
  ├── 收到 PipelineResult 后:
  │
  ├── SRT 字幕文件:
  │     srt_path = Path(tempfile.mktemp(suffix=".srt"))
  │     srt_path.write_text(result.transcript_srt)
  │     # 内容格式:
  │     # 1
  │     # 00:00:00,000 --> 00:00:03,500
  │     # 大家好，今天我们来聊一下
  │
  ├── TXT 文本文件:
  │     txt_path = Path(tempfile.mktemp(suffix=".txt"))
  │     txt_path.write_text(result.transcript_plain)
  │     # 内容格式:
  │     # [00:00] 大家好，今天我们来聊一下...
  │
  └── yield 最终结果给 Gradio → 用户看到下载按钮
```

---

## 进度映射机制

pipeline 使用分段进度映射，将每个阶段的局部进度 (0~100%) 映射到全局进度：

```
全局进度 = stage_start + local_percent * (stage_end - stage_start)
```

| 阶段 | 全局范围 | 进度来源 |
|------|---------|---------|
| URL 验证 | 0% ~ 2% | 即时完成 |
| 音频下载 | 2% ~ 20% | yt-dlp downloaded_bytes / total_bytes |
| 语音转录 | 20% ~ 80% | segment.end / total_duration |
| 内容总结 | 80% ~ 100% | LLM 流式输出期间固定 90%，完成后 100% |

---

## 数据结构流转

```
原始 URL (str)
    │
    ▼
(normalized_url, platform) ──── validate_url()
    │
    ▼
DownloadResult ─────────────── download_audio()
  ├── audio_path: str
  ├── title: str
  ├── duration: float
  └── platform: str
    │
    ▼
(segments, paragraphs) ─────── transcribe()
  │
  ├── segments: List[TranscriptSegment]      ← Whisper 原始输出
  │     └── TranscriptSegment(start, end, text)
  │                          0.0   3.5  "大家好..."
  │
  └── paragraphs: List[TranscriptParagraph]  ← 按停顿/数量合并后
        └── TranscriptParagraph(start, end, text)
                               0.0   15.3 "大家好...今天我们..."
    │
    ├──→ segments_to_markdown()  → "**[03:45]** 大家好..."  (给UI显示)
    ├──→ segments_to_srt()       → SRT 字幕格式             (给导出)
    ├──→ segments_to_plain_text()→ 纯文本+时间戳            (给导出)
    └──→ segments_to_llm_input() → 紧凑文本                 (给LLM)
    │
    ▼
summary (str, Markdown) ────── summarize_stream()
    │
    ▼
PipelineResult ─────────────── 最终结果对象，包含以上所有数据
```

---

## 关键设计模式

### 1. 生成器驱动的流式架构

整个处理链使用 Python 生成器 (`yield`) 串联。`process_video()` 是一个生成器函数，每完成一步就 `yield` 一个事件，Gradio 的 `run_pipeline()` 遍历这些事件并实时更新界面。这种模式避免了回调地狱，代码线性可读。

### 2. 单例模型加载

Whisper 模型通过全局变量 `_model` 实现单例。首次转录时加载模型（约需 10 秒），后续请求复用，避免重复加载。

### 3. 分块处理长文稿

当转录文稿超过 100,000 字时，summarizer 自动切换为"分块总结 → 合并"的两阶段策略，确保不超出 LLM 的上下文窗口。

### 4. 错误传播与优雅降级

每个模块定义自己的异常类型（`DownloadError`, `SummarizeError`），pipeline 捕获后转为 `PipelineProgress` 事件带给 UI 展示，而不是让程序崩溃。`finally` 块确保临时音频文件始终被清理。
