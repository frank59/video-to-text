# 长视频分片并行转录方案

## 背景

当视频时长超过 1 小时时，当前的顺序处理模式存在以下问题：

| 问题 | 影响 |
|------|------|
| 内存瓶颈 | 4 小时视频 WAV 文件约 1.1GB，可能导致 OOM |
| 处理时长 | 中途失败需重头开始，等待时间过长 |
| 资源利用 | 单线程顺序处理，无法利用多核 CPU |
| 一致性风险 | 长时间运行中网络、API 等不稳定因素累积 |

## 方案概述

```
原始音频 (4小时)
    │
    ▼
┌───────────────────────────────┐
│  1. VAD 检测语音段            │
│     - 快速 skip 非语音段        │
│     - 找出所有语音段起止        │
└───────────────────────────────┘
    │
    ▼
┌───────────────────────────────┐
│  2. 音频分片                  │
│     - 按静音间隔 ≥3秒 切分      │
│     - 每个分片保留 0.5s 上下文  │
│     - 分片时长建议 5-15 分钟    │
└───────────────────────────────┘
    │
    ▼
┌───────────────────────────────┐
│  3. 分片并行转录               │
│     - ThreadPoolExecutor       │
│     - 各分片独立转录           │
│     - 合并时校正时间戳偏移      │
└───────────────────────────────┘
    │
    ▼
┌───────────────────────────────┐
│  4. 分片合并文字稿             │
│     - 按全局时间排序            │
│     - 跨分片句子检测拼接       │
└───────────────────────────────┘
    │
    ▼
┌───────────────────────────────┐
│  5. 分片并行 summarizer         │
│     - 各分片独立总结            │
│     - 最终合并总结              │
└───────────────────────────────┘
```

## 关键设计

### 1. 分片触发条件

- 环境变量：`MAX_CHUNK_DURATION`（默认 600 秒 = 10 分钟）
- 超过阈值启用分片模式

### 2. VAD 语音段分片逻辑

- 静音间隔 ≥3秒 作为分片边界
- 每个分片前后各加 0.5s 上下文，减少跨分片截断
- 分片时长控制在 5-15 分钟

### 3. 并行转录

- 使用 `ThreadPoolExecutor`
- 并行度：`min(4, num_chunks)`
- faster-whisper 模型为线程安全，可共享单例

### 4. 时间戳校正

- 每个分片转录的 `start/end` 需要加上 `chunk.start_time` 偏移
- 合并后按全局时间排序

### 5. summarizer 分片

- 转录完成后，如果合并文字稿 >100k 字，也需要分片总结
- 复用现有的 `_split_transcript` 逻辑
- 各分片总结后，用 `MERGE_SUMMARY_TEMPLATE` 合并

## 文件修改清单

### core/transcriber.py

| 修改 | 说明 |
|------|------|
| 新增 `AudioChunk` dataclass | 分片数据结构 |
| 新增 `split_audio_by_vad()` | VAD 检测 + 音频分片 |
| 新增 `transcribe_chunk()` | 单分片转录，返回带偏移的 segments |
| 修改 `transcribe()` | 检测到长音频时自动分片并行 |

```python
@dataclass
class AudioChunk:
    chunk_index: int
    start_time: float   # 原始音频起始时间
    end_time: float     # 原始音频结束时间
    chunk_audio_path: str  # 临时分片文件路径

def split_audio_by_vad(
    audio_path: str,
    max_chunk_duration: float = 600,
    min_silence_ms: int = 3000,
) -> list[AudioChunk]:
    """按 VAD 语音段分片，返回分片列表"""

def transcribe_chunk(
    chunk: AudioChunk,
    language: str | None,
    model: WhisperModel,
) -> list[TranscriptSegment]:
    """转录单个分片，时间戳已校正为全局偏移"""
```

### core/pipeline.py

| 修改 | 说明 |
|------|------|
| 修改 `process_video()` | 长视频时启用分片模式 |
| 修改 `save_progress` | 支持分片数量和当前分片索引 |
| 新增分片阶段进度计算 | 分片级别 + 整体级别双重进度 |

```python
# 新增环境变量检查
MAX_CHUNK_DURATION = int(os.getenv("MAX_CHUNK_DURATION", "600"))
USE_CHUNKING = result.duration > MAX_CHUNK_DURATION
```

### core/summarizer.py

| 修改 | 说明 |
|------|------|
| 新增 `summarize_chunks_stream()` | 并行总结各分片 |
| 修改 `summarize_stream()` | 检测到超长文字稿时分片处理 |

### utils/formatter.py

| 修改 | 说明 |
|------|------|
| 新增 `merge_segments()` | 合并多分片转录结果 |
| 新增 `merge_summaries()` | 合并多分片总结结果 |

## 实现顺序

### Phase 1: VAD 分片基础
- 实现 `split_audio_by_vad()`
- 实现 `transcribe_chunk()`
- 修改 `transcribe()` 支持分片模式
- 验证分片正确性和时间戳

### Phase 2: 进度追踪
- 修改 `progress.json` 结构支持分片
- 更新 `pipeline.py` 进度计算

### Phase 3: summarizer 分片
- 实现 `summarize_chunks_stream()`
- 更新 prompt 模板

### Phase 4: 测试
- 长视频（>1小时）测试
- 进度追踪验证
- 结果正确性验证

## 配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `MAX_CHUNK_DURATION` | 600 | 触发分片的时长阈值（秒） |
| `MIN_SILENCE_MS` | 3000 | 分片边界：静音间隔（毫秒） |
| `CHUNK_CONTEXT` | 0.5 | 每个分片保留的上下文（秒） |
| `MAX_WORKERS` | 4 | 最大并行数 |

## 验证方式

1. 准备一个 1.5 小时测试视频
2. 设置 `MAX_CHUNK_DURATION=600`
3. 运行 CLI 模式，观察：
   - 分片数量是否正确
   - `progress.json` 分片进度是否更新
   - 最终转录结果时间戳是否连续
   - summarizer 是否正常工作
4. 对比分片模式和普通模式的转录结果（用短视频验证一致性）
