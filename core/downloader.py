import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yt_dlp

import config

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    audio_path: str
    title: str
    duration: float
    platform: str


class DownloadError(Exception):
    pass


def _build_ydl_opts(
    output_dir: Path,
    platform: str,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict:
    """Build yt-dlp options dict."""
    output_template = str(output_dir / "%(id)s.%(ext)s")

    opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }
        ],
        "postprocessor_args": [
            "-ar", "16000",
            "-ac", "1",
        ],
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }

    if platform == "douyin":
        opts["http_headers"] = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/16.6 Mobile/15E148 Safari/604.1"
            ),
        }

    if progress_callback:
        def _hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                if total > 0:
                    pct = downloaded / total
                    progress_callback(pct, "正在下载音频...")
            elif d["status"] == "finished":
                progress_callback(1.0, "下载完成，正在转换格式...")

        opts["progress_hooks"] = [_hook]

    return opts


def download_audio(
    url: str,
    platform: str,
    progress_callback: Callable[[float, str], None] | None = None,
) -> DownloadResult:
    """Download video audio as 16kHz mono WAV.

    Args:
        url: Video URL.
        platform: Platform name ('youtube', 'bilibili', 'douyin').
        progress_callback: Optional callback(percent: 0-1, message: str).

    Returns:
        DownloadResult with audio file path and metadata.

    Raises:
        DownloadError on failure.
    """
    output_dir = config.AUDIO_OUTPUT_DIR
    opts = _build_ydl_opts(output_dir, platform, progress_callback)

    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if info is None:
                    raise DownloadError("无法获取视频信息")

                title = info.get("title", "unknown")
                duration = info.get("duration", 0) or 0
                video_id = info.get("id", "unknown")

                if duration > config.MAX_VIDEO_DURATION:
                    raise DownloadError(
                        f"视频时长超过限制 ({duration // 3600}小时 > "
                        f"{config.MAX_VIDEO_DURATION // 3600}小时)"
                    )

                audio_path = output_dir / f"{video_id}.wav"
                if not audio_path.exists():
                    candidates = list(output_dir.glob(f"{video_id}.*"))
                    if candidates:
                        audio_path = candidates[0]
                    else:
                        raise DownloadError("音频文件提取失败，请确认 ffmpeg 已安装")

                return DownloadResult(
                    audio_path=str(audio_path),
                    title=title,
                    duration=duration,
                    platform=platform,
                )

        except yt_dlp.utils.DownloadError as e:
            last_error = e
            error_msg = str(e).lower()
            if any(kw in error_msg for kw in ["private", "unavailable", "not found", "removed"]):
                raise DownloadError("视频不存在或无法访问（可能是私密视频）") from e
            if "geo" in error_msg or "country" in error_msg:
                raise DownloadError("该视频受地域限制，无法下载") from e
            if attempt < max_retries - 1:
                logger.warning("下载失败 (尝试 %d/%d): %s", attempt + 1, max_retries, e)
                time.sleep(2 ** attempt)
                continue
        except DownloadError:
            raise
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning("下载失败 (尝试 %d/%d): %s", attempt + 1, max_retries, e)
                time.sleep(2 ** attempt)
                continue

    raise DownloadError(f"下载失败，已重试{max_retries}次: {last_error}")


def cleanup_audio(audio_path: str) -> None:
    """Delete a temporary audio file."""
    try:
        Path(audio_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("清理音频文件失败: %s", audio_path)
