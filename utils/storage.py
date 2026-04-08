import logging
from dataclasses import dataclass
from pathlib import Path

import config
from utils.formatter import safe_filename

logger = logging.getLogger(__name__)


@dataclass
class TaskOutputPaths:
    task_dir: Path
    transcript_md: Path | None = None
    transcript_txt: Path | None = None
    transcript_srt: Path | None = None
    learning_md: Path | None = None
    summary_md: Path | None = None


def save_task_output(result, output_dir: Path | None = None, job_id: str | None = None) -> TaskOutputPaths:
    """Save all task results to output/<task_id>/ directory.

    Args:
        result: PipelineResult object with task_id and all content fields.
        output_dir: Override output base directory. Defaults to config.OUTPUT_DIR.
        job_id: Optional custom job ID to use as directory name instead of result.task_id.

    Returns:
        TaskOutputPaths with paths to all written files.
    """
    base_dir = output_dir or config.OUTPUT_DIR
    task_dir = base_dir / str(job_id or result.task_id)
    task_dir.mkdir(parents=True, exist_ok=True)

    safe_name = safe_filename(result.title)
    paths = TaskOutputPaths(task_dir=task_dir)

    if result.transcript_markdown:
        p = task_dir / f"{safe_name}.md"
        p.write_text(result.transcript_markdown, encoding="utf-8")
        paths.transcript_md = p

    if result.transcript_pure:
        p = task_dir / f"{safe_name}.txt"
        p.write_text(result.transcript_pure, encoding="utf-8")
        paths.transcript_txt = p

    if result.transcript_srt:
        p = task_dir / f"{safe_name}.srt"
        p.write_text(result.transcript_srt, encoding="utf-8")
        paths.transcript_srt = p

    if result.learning_transcript:
        p = task_dir / f"{safe_name}_学习稿.md"
        p.write_text(result.learning_transcript, encoding="utf-8")
        paths.learning_md = p

    if result.summary:
        p = task_dir / f"{safe_name}_总结.md"
        p.write_text(result.summary, encoding="utf-8")
        paths.summary_md = p

    logger.info("任务结果已保存到: %s", task_dir)
    return paths
