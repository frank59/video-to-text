import logging
from dataclasses import dataclass, field
from typing import Generator

from core.downloader import download_audio, cleanup_audio, DownloadError
from core.transcriber import transcribe
from core.summarizer import summarize_stream, SummarizeError
from utils.url_parser import validate_url
from utils.formatter import (
    TranscriptSegment,
    TranscriptParagraph,
    segments_to_markdown,
    segments_to_srt,
    segments_to_plain_text,
    segments_to_llm_input,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    title: str = ""
    platform: str = ""
    duration: float = 0
    segments: list[TranscriptSegment] = field(default_factory=list)
    paragraphs: list[TranscriptParagraph] = field(default_factory=list)
    transcript_markdown: str = ""
    transcript_plain: str = ""
    transcript_srt: str = ""
    summary: str = ""


@dataclass
class PipelineProgress:
    percent: float  # 0.0 - 1.0
    stage: str  # 'validate', 'download', 'transcribe', 'summarize'
    message: str
    transcript_md: str = ""
    partial_summary: str = ""


# Progress weight mapping: each stage's (start, end) as fractions of total
STAGE_WEIGHTS = {
    "validate": (0.0, 0.02),
    "download": (0.02, 0.20),
    "transcribe": (0.20, 0.80),
    "summarize": (0.80, 1.0),
}


def _map_progress(stage: str, local_pct: float) -> float:
    """Map a stage's local progress (0-1) to global progress (0-1)."""
    start, end = STAGE_WEIGHTS[stage]
    return start + local_pct * (end - start)


def process_video(
    url: str,
    model_size: str | None = None,
    language: str | None = None,
) -> Generator[PipelineProgress | PipelineResult, None, None]:
    """Process a video URL through the full pipeline.

    Yields PipelineProgress events during processing,
    and a final PipelineResult when complete.
    """
    result = PipelineResult()
    audio_path = None

    try:
        # --- Stage 1: Validate URL ---
        yield PipelineProgress(
            percent=_map_progress("validate", 0),
            stage="validate",
            message="正在验证链接...",
        )

        try:
            normalized_url, platform = validate_url(url)
        except ValueError as e:
            yield PipelineProgress(
                percent=0,
                stage="validate",
                message=f"错误: {e}",
            )
            return

        result.platform = platform
        yield PipelineProgress(
            percent=_map_progress("validate", 1.0),
            stage="validate",
            message=f"识别为 {platform} 视频",
        )

        # --- Stage 2: Download audio ---
        yield PipelineProgress(
            percent=_map_progress("download", 0),
            stage="download",
            message="正在下载音频...",
        )

        def download_progress(pct, msg):
            pass  # Progress is yielded from the generator, not a callback

        try:
            dl_result = download_audio(normalized_url, platform)
        except DownloadError as e:
            yield PipelineProgress(
                percent=_map_progress("download", 0),
                stage="download",
                message=f"下载失败: {e}",
            )
            return

        audio_path = dl_result.audio_path
        result.title = dl_result.title
        result.duration = dl_result.duration

        yield PipelineProgress(
            percent=_map_progress("download", 1.0),
            stage="download",
            message=f"下载完成: {result.title}",
        )

        # --- Stage 3: Transcribe ---
        yield PipelineProgress(
            percent=_map_progress("transcribe", 0),
            stage="transcribe",
            message="正在加载语音识别模型...",
        )

        progress_events = []

        def transcribe_progress(pct, msg):
            progress_events.append(PipelineProgress(
                percent=_map_progress("transcribe", pct),
                stage="transcribe",
                message=msg,
            ))

        segments, paragraphs = transcribe(
            audio_path=audio_path,
            language=language,
            model_size=model_size,
            total_duration=result.duration,
            progress_callback=transcribe_progress,
        )

        result.segments = segments
        result.paragraphs = paragraphs

        always_hours = result.duration >= 3600
        result.transcript_markdown = segments_to_markdown(paragraphs, always_hours)
        result.transcript_plain = segments_to_plain_text(paragraphs, always_hours)
        result.transcript_srt = segments_to_srt(segments)

        yield PipelineProgress(
            percent=_map_progress("transcribe", 1.0),
            stage="transcribe",
            message=f"转录完成: {len(segments)} 个片段, {len(paragraphs)} 个段落",
            transcript_md=result.transcript_markdown,
        )

        # --- Stage 4: Summarize ---
        yield PipelineProgress(
            percent=_map_progress("summarize", 0),
            stage="summarize",
            message="正在生成内容总结...",
            transcript_md=result.transcript_markdown,
        )

        llm_input = segments_to_llm_input(paragraphs, always_hours)
        summary_parts = []

        try:
            for chunk in summarize_stream(llm_input):
                summary_parts.append(chunk)
                result.summary = "".join(summary_parts)
                yield PipelineProgress(
                    percent=_map_progress("summarize", 0.5),
                    stage="summarize",
                    message="正在生成总结...",
                    transcript_md=result.transcript_markdown,
                    partial_summary=result.summary,
                )
        except SummarizeError as e:
            logger.error("总结失败: %s", e)
            result.summary = f"总结生成失败: {e}"
            yield PipelineProgress(
                percent=_map_progress("summarize", 1.0),
                stage="summarize",
                message=f"总结失败: {e}",
                transcript_md=result.transcript_markdown,
                partial_summary=result.summary,
            )

        yield PipelineProgress(
            percent=1.0,
            stage="summarize",
            message="处理完成!",
        )

        # --- Final result ---
        yield result

    finally:
        if audio_path:
            cleanup_audio(audio_path)
