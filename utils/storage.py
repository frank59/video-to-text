import json
import logging
from dataclasses import dataclass
from datetime import datetime
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


def _update_progress_with_output(task_dir: Path, paths: TaskOutputPaths):
    """Update progress.json with output file paths."""
    progress_file = task_dir / "progress.json"
    if progress_file.exists():
        try:
            data = json.loads(progress_file.read_text(encoding="utf-8"))
            data["output_files"] = {
                "transcript_md": str(paths.transcript_md) if paths.transcript_md else None,
                "transcript_txt": str(paths.transcript_txt) if paths.transcript_txt else None,
                "transcript_srt": str(paths.transcript_srt) if paths.transcript_srt else None,
                "learning_md": str(paths.learning_md) if paths.learning_md else None,
                "summary_md": str(paths.summary_md) if paths.summary_md else None,
            }
            data["updated_at"] = datetime.now().isoformat()
            progress_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("更新 progress.json 失败: %s", e)


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

    # Update progress.json with output file paths
    _update_progress_with_output(task_dir, paths)

    return paths
