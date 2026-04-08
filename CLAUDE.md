# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Video-to-text tool that downloads videos from Douyin, Bilibili, and YouTube, transcribes them locally using faster-whisper, and generates AI-powered summaries and language learning materials using Alibaba's qwen model via the DashScope API.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
# Access at http://localhost:7860

# Environment setup (required)
cp .env.example .env
# Edit .env and add DASHSCOPE_API_KEY

# Docker setup
docker-compose up --build
```

## Architecture

### Pipeline Flow (core/pipeline.py)

The system uses a **generator-driven streaming architecture**. `process_video()` is a generator that yields `PipelineProgress` events during processing and a final `PipelineResult`. The UI updates in real-time via these yields.

**Processing stages:**
1. URL validation (0-2%)
2. Audio download via yt-dlp → 16kHz mono WAV (2-20%)
3. Transcription via faster-whisper with VAD (20-80%)
4. Language learning transcript (non-Chinese only, 60-80%)
5. AI summary via DashScope qwen (80-100%)

**Progress weights are conditional** — Chinese videos skip the learning stage, so transcription gets 20-80% instead of 18-60%. The weights are switched dynamically after language detection.

### Key Modules

| File | Responsibility |
|------|----------------|
| `core/pipeline.py` | Orchestrates the full pipeline, yields progress events |
| `core/downloader.py` | yt-dlp audio extraction, Douyin fallback via iesdouyin.com |
| `core/transcriber.py` | faster-whisper inference, Traditional→Simplified Chinese conversion |
| `core/summarizer.py` | DashScope API calls for streaming summary/learning output |
| `utils/url_parser.py` | URL normalization, short-link resolution, platform detection |
| `utils/formatter.py` | Transcript formatting (Markdown, SRT, plain text, paragraphs) |
| `utils/storage.py` | Saves task output to `output/<task_id>/` |
| `prompts/summarize.py` | Prompt template for video summary |
| `prompts/learning.py` | Prompt template for language learning transcript |

### Data Structures

- `TranscriptSegment`: Individual utterance with `(start, end, text)`
- `TranscriptParagraph`: Merged paragraphs based on 2s silence or 5-segment limit
- `PipelineResult`: Final result containing all transcripts, summaries, metadata
- `PipelineProgress`: Streaming progress event with `percent`, `stage`, `message`, partial content fields

### Key Design Patterns

1. **Singleton models**: WhisperModel and OpenAI client are global singletons loaded once
2. **Streaming output**: Both AI summary and learning transcript stream token-by-token to the UI
3. **Long transcript chunking**: >100k char transcripts are split into 80k char chunks with 2k overlap, summarized per-chunk, then merged
4. **Graceful degradation**: Learning stage failures don't terminate the pipeline; errors are logged and flow continues to summary
5. **Automatic T2S**: Chinese transcripts automatically convert Traditional→Simplified via OpenCC

### Storage

- Audio files: `data/audio/<video_id>.wav` (temporary, deleted after processing)
- Whisper models: `data/cache/models--Systran--faster-whisper-<size>/`
- Task outputs: `output/<task_id>/` with files named after video title

### Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `DASHSCOPE_API_KEY` | (required) | Alibaba DashScope API key |
| `DASHSCOPE_BASE_URL` | `https://coding.dashscope.aliyuncs.com/v1` | API endpoint |
| `DASHSCOPE_MODEL` | `qwen3.5-plus` | LLM model |
| `WHISPER_MODEL_SIZE` | `medium` | tiny/base/small/medium/large-v3 |
| `WHISPER_COMPUTE_TYPE` | `int8` | int8/float16/float32 |
| `MAX_VIDEO_DURATION` | `14400` | Max video length in seconds |
| `COOKIES_FILE` | `cookies.txt` | Netscape-format cookies for authenticated requests |
