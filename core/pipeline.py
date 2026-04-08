import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Generator

import config
from core.downloader import download_audio, cleanup_audio, DownloadError
from core.transcriber import transcribe
from core.summarizer import summarize_stream, learning_transcript_stream, SummarizeError
from utils.url_parser import validate_url
from utils.formatter import (
    TranscriptSegment,
    TranscriptParagraph,
    segments_to_markdown,
    segments_to_srt,
    segments_to_plain_text,
    segments_to_llm_input,
    segments_to_pure_text,
)
from utils.snowflake import generate_id

logger = logging.getLogger(__name__)


# Task status constants
class TaskStatus:
    PENDING = "pending"
    VALIDATING = "validating"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    LEARNING = "learning"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"
    FAILED = "failed"


def _stage_to_status(stage: str) -> str:
    """Map pipeline stage to task status."""
    mapping = {
        "validate": TaskStatus.VALIDATING,
        "download": TaskStatus.DOWNLOADING,
        "transcribe": TaskStatus.TRANSCRIBING,
        "learning": TaskStatus.LEARNING,
        "summarize": TaskStatus.SUMMARIZING,
    }
    return mapping.get(stage, TaskStatus.PENDING)


def _save_progress_json(
    output_dir: Path,
    job_id: str,
    task_id: str,
    status: str,
    stage: str,
    percent: float,
    message: str,
    platform: str = "",
    title: str = "",
    duration: float = 0,
    detected_language: str = "",
    error: str = "",
    output_files: dict = None,
):
    """Save or update progress.json file."""
    if output_files is None:
        output_files = {}

    snapshot = {
        "task_id": task_id,
        "job_id": job_id,
        "status": status,
        "stage": stage,
        "percent": int(percent * 100),
        "message": message,
        "platform": platform,
        "title": title,
        "duration": duration,
        "detected_language": detected_language,
        "error": error or None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "output_files": output_files,
    }

    task_dir = output_dir / job_id
    task_dir.mkdir(parents=True, exist_ok=True)
    progress_file = task_dir / "progress.json"
    progress_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("Progress saved to %s", progress_file)


@dataclass
class PipelineResult:
    task_id: str = ""
    title: str = ""
    platform: str = ""
    duration: float = 0
    detected_language: str = ""
    segments: list[TranscriptSegment] = field(default_factory=list)
    paragraphs: list[TranscriptParagraph] = field(default_factory=list)
    transcript_markdown: str = ""
    transcript_plain: str = ""
    transcript_pure: str = ""
    transcript_srt: str = ""
    summary: str = ""
    learning_transcript: str = ""


@dataclass
class PipelineProgress:
    percent: float  # 0.0 - 1.0
    stage: str  # 'validate', 'download', 'transcribe', 'learning', 'summarize'
    message: str
    transcript_md: str = ""
    pure_text: str = ""
    partial_summary: str = ""
    partial_learning: str = ""


# Progress weight mapping: each stage's (start, end) as fractions of total
# Non-Chinese: validate 0-2%, download 2-18%, transcribe 18-60%, learning 60-80%, summarize 80-100%
# Chinese:     validate 0-2%, download 2-20%, transcribe 20-80%, summarize 80-100%
STAGE_WEIGHTS_WITH_LEARNING = {
    "validate": (0.0, 0.02),
    "download": (0.02, 0.18),
    "transcribe": (0.18, 0.60),
    "learning": (0.60, 0.80),
    "summarize": (0.80, 1.0),
}

STAGE_WEIGHTS_NO_LEARNING = {
    "validate": (0.0, 0.02),
    "download": (0.02, 0.20),
    "transcribe": (0.20, 0.80),
    "summarize": (0.80, 1.0),
}


def _map_progress(stage: str, local_pct: float, weights: dict) -> float:
    """Map a stage's local progress (0-1) to global progress (0-1)."""
    start, end = weights[stage]
    return start + local_pct * (end - start)


def process_video(
    url: str,
    model_size: str | None = None,
    language: str | None = None,
    job_id: str | None = None,
    output_dir: Path | None = None,
) -> Generator[PipelineProgress | PipelineResult, None, None]:
    """Process a video URL through the full pipeline.

    Yields PipelineProgress events during processing,
    and a final PipelineResult when complete.

    Args:
        url: Video URL.
        model_size: Whisper model size override.
        language: Language code override.
        job_id: Custom job ID for output directory name.
        output_dir: Output base directory for progress.json and results.
    """
    result = PipelineResult(task_id=str(generate_id()))
    audio_path = None
    weights = STAGE_WEIGHTS_NO_LEARNING
    task_dir_id = job_id or result.task_id
    out_dir = output_dir or config.OUTPUT_DIR

    def save_progress(status: str, stage: str, percent: float, message: str, error: str = ""):
        _save_progress_json(
            output_dir=out_dir,
            job_id=task_dir_id,
            task_id=result.task_id,
            status=status,
            stage=stage,
            percent=percent,
            message=message,
            platform=result.platform,
            title=result.title,
            duration=result.duration,
            detected_language=result.detected_language,
            error=error,
        )

    try:
        # --- Stage 1: Validate URL ---
        yield PipelineProgress(
            percent=_map_progress("validate", 0, weights),
            stage="validate",
            message="正在验证链接...",
        )
        save_progress(TaskStatus.VALIDATING, "validate", 0, "正在验证链接...")

        try:
            normalized_url, platform = validate_url(url)
        except ValueError as e:
            err_msg = f"错误: {e}"
            yield PipelineProgress(percent=0, stage="validate", message=err_msg)
            save_progress(TaskStatus.FAILED, "validate", 0, err_msg, error=str(e))
            return

        result.platform = platform
        yield PipelineProgress(
            percent=_map_progress("validate", 1.0, weights),
            stage="validate",
            message=f"识别为 {platform} 视频",
        )
        save_progress(TaskStatus.DOWNLOADING, "download", 0.02, f"识别为 {platform} 视频")

        # --- Stage 2: Download audio ---
        yield PipelineProgress(
            percent=_map_progress("download", 0, weights),
            stage="download",
            message="正在下载音频...",
        )
        save_progress(TaskStatus.DOWNLOADING, "download", 0.02, "正在下载音频...")

        try:
            dl_result = download_audio(normalized_url, platform)
        except DownloadError as e:
            err_msg = f"下载失败: {e}"
            yield PipelineProgress(
                percent=_map_progress("download", 0, weights),
                stage="download",
                message=err_msg,
            )
            save_progress(TaskStatus.FAILED, "download", 0.02, err_msg, error=str(e))
            return

        audio_path = dl_result.audio_path
        result.title = dl_result.title
        result.duration = dl_result.duration

        yield PipelineProgress(
            percent=_map_progress("download", 1.0, weights),
            stage="download",
            message=f"下载完成: {result.title}",
        )
        save_progress(TaskStatus.TRANSCRIBING, "transcribe", 0.20, f"下载完成: {result.title}")

        # --- Stage 3: Transcribe ---
        yield PipelineProgress(
            percent=_map_progress("transcribe", 0, weights),
            stage="transcribe",
            message="正在加载语音识别模型...",
        )
        save_progress(TaskStatus.TRANSCRIBING, "transcribe", 0.20, "正在加载语音识别模型...")

        progress_events = []

        def transcribe_progress(pct, msg):
            progress_events.append(PipelineProgress(
                percent=_map_progress("transcribe", pct, weights),
                stage="transcribe",
                message=msg,
            ))
            save_progress(TaskStatus.TRANSCRIBING, "transcribe",
                         _map_progress("transcribe", pct, weights), msg)

        segments, paragraphs, detected_lang = transcribe(
            audio_path=audio_path,
            language=language,
            model_size=model_size,
            total_duration=result.duration,
            progress_callback=transcribe_progress,
        )

        result.segments = segments
        result.paragraphs = paragraphs
        result.detected_language = detected_lang

        always_hours = result.duration >= 3600
        result.transcript_markdown = segments_to_markdown(paragraphs, always_hours)
        result.transcript_plain = segments_to_plain_text(paragraphs, always_hours)
        result.transcript_pure = segments_to_pure_text(paragraphs)
        result.transcript_srt = segments_to_srt(segments)

        yield PipelineProgress(
            percent=_map_progress("transcribe", 1.0, weights),
            stage="transcribe",
            message=f"转录完成: {len(segments)} 个片段, {len(paragraphs)} 个段落",
            transcript_md=result.transcript_markdown,
            pure_text=result.transcript_pure,
        )

        # --- Determine detected language and adjust weights ---
        is_non_chinese = result.detected_language != "zh"

        if is_non_chinese:
            weights = STAGE_WEIGHTS_WITH_LEARNING

        # --- Stage 3.5: Learning Transcript (non-Chinese only) ---
        if is_non_chinese:
            yield PipelineProgress(
                percent=_map_progress("learning", 0, weights),
                stage="learning",
                message="正在生成语言学习稿...",
                transcript_md=result.transcript_markdown,
                pure_text=result.transcript_pure,
            )
            save_progress(TaskStatus.LEARNING, "learning", 0.60, "正在生成语言学习稿...")

            learning_parts = []
            try:
                for chunk in learning_transcript_stream(result.transcript_pure, detected_lang):
                    learning_parts.append(chunk)
                    result.learning_transcript = "".join(learning_parts)
                    yield PipelineProgress(
                        percent=_map_progress("learning", 0.5, weights),
                        stage="learning",
                        message="正在生成学习稿...",
                        transcript_md=result.transcript_markdown,
                        pure_text=result.transcript_pure,
                        partial_learning=result.learning_transcript,
                    )
                    save_progress(TaskStatus.LEARNING, "learning",
                                 _map_progress("learning", 0.5, weights),
                                 "正在生成学习稿...")
            except SummarizeError as e:
                logger.error("学习稿生成失败: %s", e)
                result.learning_transcript = f"学习稿生成失败: {e}"

            yield PipelineProgress(
                percent=_map_progress("learning", 1.0, weights),
                stage="learning",
                message="学习稿生成完成",
                transcript_md=result.transcript_markdown,
                pure_text=result.transcript_pure,
                partial_learning=result.learning_transcript,
            )
            save_progress(TaskStatus.SUMMARIZING, "summarize", 0.80, "学习稿生成完成")

        # --- Stage 4: Summarize ---
        yield PipelineProgress(
            percent=_map_progress("summarize", 0, weights),
            stage="summarize",
            message="正在生成内容总结...",
            transcript_md=result.transcript_markdown,
            pure_text=result.transcript_pure,
            partial_learning=result.learning_transcript,
        )
        save_progress(TaskStatus.SUMMARIZING, "summarize",
                     _map_progress("summarize", 0, weights), "正在生成内容总结...")

        llm_input = segments_to_llm_input(paragraphs, always_hours)
        summary_parts = []

        try:
            for chunk in summarize_stream(llm_input):
                summary_parts.append(chunk)
                result.summary = "".join(summary_parts)
                yield PipelineProgress(
                    percent=_map_progress("summarize", 0.5, weights),
                    stage="summarize",
                    message="正在生成总结...",
                    transcript_md=result.transcript_markdown,
                    pure_text=result.transcript_pure,
                    partial_summary=result.summary,
                    partial_learning=result.learning_transcript,
                )
                save_progress(TaskStatus.SUMMARIZING, "summarize",
                             _map_progress("summarize", 0.5, weights), "正在生成总结...")
        except SummarizeError as e:
            logger.error("总结失败: %s", e)
            result.summary = f"总结生成失败: {e}"
            yield PipelineProgress(
                percent=_map_progress("summarize", 1.0, weights),
                stage="summarize",
                message=f"总结失败: {e}",
                transcript_md=result.transcript_markdown,
                pure_text=result.transcript_pure,
                partial_summary=result.summary,
                partial_learning=result.learning_transcript,
            )
            save_progress(TaskStatus.FAILED, "summarize",
                         _map_progress("summarize", 1.0, weights),
                         f"总结失败: {e}", error=str(e))

        yield PipelineProgress(
            percent=1.0,
            stage="summarize",
            message="处理完成!",
        )
        save_progress(TaskStatus.COMPLETED, "summarize", 1.0, "处理完成!")

        # --- Final result ---
        yield result

    finally:
        if audio_path:
            cleanup_audio(audio_path)
