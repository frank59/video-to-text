import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Ensure ffmpeg is available: use static_ffmpeg as fallback if system ffmpeg not found
if not shutil.which("ffmpeg"):
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    except ImportError:
        pass

BASE_DIR = Path(__file__).parent

# DashScope (Alibaba Bailian) - OpenAI compatible API
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://coding.dashscope.aliyuncs.com/v1")
DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen3.5-plus")

# Whisper
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "medium")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")

# Paths
AUDIO_OUTPUT_DIR = BASE_DIR / "data" / "audio"
WHISPER_CACHE_DIR = BASE_DIR / "data" / "cache"
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(BASE_DIR / "output")))

# Limits
MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION", "14400"))

# Cookies file for yt-dlp (Netscape format)
_cookies_file_env = os.getenv("COOKIES_FILE", "")
if _cookies_file_env:
    _cookies_path = Path(_cookies_file_env)
    if not _cookies_path.is_absolute():
        _cookies_path = BASE_DIR / _cookies_path
else:
    _cookies_path = BASE_DIR / "cookies.txt"
COOKIES_FILE: Path | None = _cookies_path if _cookies_path.is_file() else None
COOKIES_FILE_CONFIGURED = bool(_cookies_file_env)

# Ensure directories exist
AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
