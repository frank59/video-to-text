import re
from urllib.parse import urlparse

import requests

PLATFORM_PATTERNS = {
    "youtube": [
        r"(?:www\.)?youtube\.com/watch",
        r"(?:www\.)?youtube\.com/shorts/",
        r"youtu\.be/",
        r"(?:www\.)?youtube\.com/live/",
    ],
    "bilibili": [
        r"(?:www\.)?bilibili\.com/video/",
        r"b23\.tv/",
    ],
    "douyin": [
        r"(?:www\.)?douyin\.com/video/",
        r"v\.douyin\.com/",
        r"(?:www\.)?iesdouyin\.com/",
    ],
}


def detect_platform(url: str) -> str | None:
    """Detect video platform from URL. Returns 'youtube', 'bilibili', 'douyin', or None."""
    url = url.strip()
    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, url):
                return platform
    return None


def normalize_url(url: str) -> str:
    """Expand short links (b23.tv, v.douyin.com, etc.) to canonical URLs."""
    url = url.strip()
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)

    short_domains = {"b23.tv", "v.douyin.com"}
    if parsed.hostname in short_domains:
        try:
            resp = requests.head(url, allow_redirects=True, timeout=10)
            return resp.url
        except requests.RequestException:
            pass

    return url


def validate_url(url: str) -> tuple[str, str]:
    """Validate and normalize a video URL.

    Returns:
        (normalized_url, platform) tuple.

    Raises:
        ValueError if URL is invalid or unsupported.
    """
    url = url.strip()
    if not url:
        raise ValueError("请输入视频链接")

    url = normalize_url(url)
    platform = detect_platform(url)

    if platform is None:
        raise ValueError("不支持的视频链接，目前支持抖音、B站和YouTube")

    return url, platform
