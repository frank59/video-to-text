import logging
from typing import Callable

from faster_whisper import WhisperModel
from opencc import OpenCC

import config
from utils.formatter import TranscriptSegment, TranscriptParagraph, group_segments_into_paragraphs

logger = logging.getLogger(__name__)

_model: WhisperModel | None = None
_t2s = OpenCC('t2s')  # Traditional to Simplified Chinese converter


def get_model(
    model_size: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
) -> WhisperModel:
    """Get or load the Whisper model (singleton)."""
    global _model

    model_size = model_size or config.WHISPER_MODEL_SIZE
    device = device or config.WHISPER_DEVICE
    compute_type = compute_type or config.WHISPER_COMPUTE_TYPE

    if _model is None:
        logger.info("加载 Whisper 模型: %s (device=%s, compute=%s)", model_size, device, compute_type)
        _model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(config.WHISPER_CACHE_DIR),
        )
        logger.info("Whisper 模型加载完成")

    return _model


def reload_model(
    model_size: str,
    device: str | None = None,
    compute_type: str | None = None,
) -> WhisperModel:
    """Force reload model with new settings."""
    global _model
    _model = None
    return get_model(model_size, device, compute_type)


def transcribe(
    audio_path: str,
    language: str | None = None,
    model_size: str | None = None,
    total_duration: float = 0,
    progress_callback: Callable[[float, str], None] | None = None,
) -> tuple[list[TranscriptSegment], list[TranscriptParagraph], str]:
    """Transcribe audio file to text with timestamps.

    Args:
        audio_path: Path to audio file (WAV).
        language: Language code (e.g., 'zh', 'en') or None for auto-detect.
        model_size: Override model size. If different from loaded model, triggers reload.
        total_duration: Total audio duration in seconds (for progress calculation).
        progress_callback: Optional callback(percent: 0-1, message: str).

    Returns:
        (segments, paragraphs, detected_language) tuple.
    """
    model = get_model(model_size)

    transcribe_opts = {
        "vad_filter": True,
        "vad_parameters": {
            "min_silence_duration_ms": 500,
        },
    }
    if language and language != "auto":
        transcribe_opts["language"] = language

    logger.info("开始转录: %s", audio_path)
    result_segments, info = model.transcribe(audio_path, **transcribe_opts)

    detected_lang = info.language
    logger.info("检测到语言: %s (概率: %.2f)", detected_lang, info.language_probability)

    if total_duration <= 0:
        total_duration = info.duration or 1.0

    segments: list[TranscriptSegment] = []
    need_t2s = detected_lang == "zh"
    if need_t2s:
        logger.info("检测到中文，将自动繁体转简体")

    for seg in result_segments:
        text = _t2s.convert(seg.text) if need_t2s else seg.text
        segments.append(TranscriptSegment(
            start=seg.start,
            end=seg.end,
            text=text,
        ))

        if progress_callback and total_duration > 0:
            pct = min(seg.end / total_duration, 1.0)
            progress_callback(pct, f"正在转录... ({len(segments)} 段)")

    logger.info("转录完成: %d 个片段", len(segments))

    always_hours = total_duration >= 3600
    paragraphs = group_segments_into_paragraphs(segments)

    return segments, paragraphs, detected_lang
