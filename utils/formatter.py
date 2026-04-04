from dataclasses import dataclass


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptParagraph:
    start: float
    end: float
    text: str


def format_timestamp(seconds: float, always_hours: bool = False) -> str:
    """Format seconds to MM:SS or H:MM:SS string."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0 or always_hours:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _srt_timestamp(seconds: float) -> str:
    """Format seconds to SRT timestamp: HH:MM:SS,mmm"""
    total_ms = int(seconds * 1000)
    h = total_ms // 3600000
    m = (total_ms % 3600000) // 60000
    s = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def group_segments_into_paragraphs(
    segments: list[TranscriptSegment],
    pause_threshold: float = 2.0,
    max_segments_per_paragraph: int = 5,
) -> list[TranscriptParagraph]:
    """Group consecutive segments into paragraphs based on pauses or segment count."""
    if not segments:
        return []

    paragraphs = []
    current_texts = []
    current_start = segments[0].start
    seg_count = 0

    for i, seg in enumerate(segments):
        if seg_count > 0:
            gap = seg.start - segments[i - 1].end
            if gap >= pause_threshold or seg_count >= max_segments_per_paragraph:
                paragraphs.append(TranscriptParagraph(
                    start=current_start,
                    end=segments[i - 1].end,
                    text="".join(current_texts).strip(),
                ))
                current_texts = []
                current_start = seg.start
                seg_count = 0

        current_texts.append(seg.text)
        seg_count += 1

    if current_texts:
        paragraphs.append(TranscriptParagraph(
            start=current_start,
            end=segments[-1].end,
            text="".join(current_texts).strip(),
        ))

    return paragraphs


def segments_to_markdown(
    paragraphs: list[TranscriptParagraph],
    always_hours: bool = False,
) -> str:
    """Render paragraphs as Markdown with bold timestamps."""
    lines = []
    for p in paragraphs:
        ts = format_timestamp(p.start, always_hours)
        lines.append(f"**[{ts}]** {p.text}")
    return "\n\n".join(lines)


def segments_to_srt(segments: list[TranscriptSegment]) -> str:
    """Generate SRT subtitle format from segments."""
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(seg.start)} --> {_srt_timestamp(seg.end)}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines)


def segments_to_plain_text(
    paragraphs: list[TranscriptParagraph],
    always_hours: bool = False,
) -> str:
    """Plain text with timestamps for export."""
    lines = []
    for p in paragraphs:
        ts = format_timestamp(p.start, always_hours)
        lines.append(f"[{ts}] {p.text}")
    return "\n\n".join(lines)


def segments_to_llm_input(
    paragraphs: list[TranscriptParagraph],
    always_hours: bool = False,
) -> str:
    """Compact format for sending to LLM (saves tokens)."""
    lines = []
    for p in paragraphs:
        ts = format_timestamp(p.start, always_hours)
        lines.append(f"[{ts}] {p.text}")
    return "\n".join(lines)


def segments_to_pure_text(paragraphs: list[TranscriptParagraph]) -> str:
    """Pure text without any timestamps."""
    return "\n\n".join(p.text for p in paragraphs)
