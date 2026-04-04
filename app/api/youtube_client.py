"""YouTube Data API v3 client."""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
    TRANSCRIPT_AVAILABLE = True
except ImportError:
    TRANSCRIPT_AVAILABLE = False


def _published_after(date_filter: str) -> Optional[str]:
    """Return ISO 8601 string for publishedAfter parameter."""
    now = datetime.now(timezone.utc)
    if date_filter == "week":
        dt = now - timedelta(days=7)
    elif date_filter == "month":
        dt = now - timedelta(days=30)
    elif date_filter == "year":
        dt = now - timedelta(days=365)
    else:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def search_videos(
    api_key: str,
    query: str,
    date_filter: str = "all",
    order: str = "relevance",
    max_results: int = 20,
) -> list[dict]:
    """Search YouTube videos. Returns list of video info dicts (without stats)."""
    if not GOOGLE_API_AVAILABLE:
        raise RuntimeError("google-api-python-client is not installed.")

    yt = build("youtube", "v3", developerKey=api_key)
    params = {
        "q": query,
        "type": "video",
        "part": "snippet",
        "maxResults": min(max_results, 50),
        "order": order,
        "videoDuration": "any",
    }
    published_after = _published_after(date_filter)
    if published_after:
        params["publishedAfter"] = published_after

    try:
        resp = yt.search().list(**params).execute()
    except HttpError as e:
        raise RuntimeError(f"YouTube API error: {e}") from e

    items = resp.get("items", [])
    video_ids = [item["id"]["videoId"] for item in items]
    if not video_ids:
        return []

    # Fetch statistics for all videos in one call
    stats_resp = (
        yt.videos()
        .list(part="snippet,statistics,contentDetails", id=",".join(video_ids))
        .execute()
    )
    stats_map = {}
    for v in stats_resp.get("items", []):
        stats_map[v["id"]] = v

    results = []
    for item in items:
        vid_id = item["id"]["videoId"]
        snippet = item["snippet"]
        v_data = stats_map.get(vid_id, {})
        stats = v_data.get("statistics", {})
        details = v_data.get("contentDetails", {})

        view_count = int(stats.get("viewCount", 0))
        results.append({
            "id": vid_id,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt", ""),
            "description": snippet.get("description", ""),
            "thumbnail": (
                snippet.get("thumbnails", {})
                .get("medium", {})
                .get("url", "")
            ),
            "view_count": view_count,
            "like_count": int(stats.get("likeCount", 0)),
            "duration": details.get("duration", ""),
            "tags": v_data.get("snippet", {}).get("tags", []),
        })
    return results


def get_video_details(api_key: str, video_id_or_url: str) -> dict:
    """Fetch full details for a single video by ID or URL."""
    if not GOOGLE_API_AVAILABLE:
        raise RuntimeError("google-api-python-client is not installed.")

    vid_id = extract_video_id(video_id_or_url)
    yt = build("youtube", "v3", developerKey=api_key)
    resp = (
        yt.videos()
        .list(part="snippet,statistics,contentDetails", id=vid_id)
        .execute()
    )
    items = resp.get("items", [])
    if not items:
        raise RuntimeError(f"Video not found: {video_id_or_url}")
    v = items[0]
    snippet = v.get("snippet", {})
    stats = v.get("statistics", {})
    details = v.get("contentDetails", {})
    return {
        "id": vid_id,
        "url": f"https://www.youtube.com/watch?v={vid_id}",
        "title": snippet.get("title", ""),
        "channel": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt", ""),
        "description": snippet.get("description", ""),
        "thumbnail": (
            snippet.get("thumbnails", {}).get("high", {}).get("url", "")
        ),
        "view_count": int(stats.get("viewCount", 0)),
        "like_count": int(stats.get("likeCount", 0)),
        "duration": details.get("duration", ""),
        "tags": snippet.get("tags", []),
    }


def get_transcript(video_id: str, languages: list[str] | None = None) -> str:
    """Fetch transcript for a video. Returns plain text or empty string."""
    if not TRANSCRIPT_AVAILABLE:
        return ""
    if languages is None:
        languages = ["ru", "en", "uk"]
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        return " ".join(entry["text"] for entry in transcript)
    except (TranscriptsDisabled, NoTranscriptFound):
        return ""
    except Exception:
        return ""


def extract_video_id(url_or_id: str) -> str:
    """Extract YouTube video ID from URL or return as-is."""
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    # Assume it's already an ID if 11 chars
    if re.match(r"^[A-Za-z0-9_-]{11}$", url_or_id.strip()):
        return url_or_id.strip()
    raise ValueError(f"Cannot extract video ID from: {url_or_id}")


def download_thumbnail(url: str) -> bytes:
    """Download thumbnail image bytes."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.content
