#!/usr/bin/env python3
# /// script
# dependencies = [
#   "google-api-python-client>=2.150.0",
#   "google-auth-oauthlib>=1.0.0",
#   "youtube-transcript-api>=0.6.0",
#   "pyyaml>=6.0",
#   "python-dotenv>=1.0.0",
#   "requests>=2.31.0",
# ]
# ///
"""
YouTube Tool - Research, search, upload, and analytics.

Usage:
    uv run youtube.py get_channel_videos @mkbhd --days 30
    uv run youtube.py search_videos "AI agents" --max 20
    uv run youtube.py get_transcript VIDEO_ID
    uv run youtube.py upload video.mp4 --title "My Video" --description "..."

Analytics (requires OAuth):
    uv run youtube.py channel_stats --days 30
    uv run youtube.py top_videos --days 30
    uv run youtube.py video_daily VIDEO_ID --days 30
    uv run youtube.py traffic_sources --days 30
    uv run youtube.py search_terms --days 30
    uv run youtube.py demographics --days 30
    uv run youtube.py retention VIDEO_ID
    uv run youtube.py geography --days 30
    uv run youtube.py revenue --days 30

Environment (auto-loaded from .env):
    YOUTUBE_API_KEY - Required for research commands.
    YOUTUBE_CLIENT_SECRETS - Path to OAuth client_secrets.json (for upload/analytics).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import requests
import yaml

# Load .env from project root
load_dotenv()

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)


# =============================================================================
# Helpers
# =============================================================================


def parse_markdown_metadata(content: str) -> dict:
    """Parse markdown file with YAML frontmatter.

    Format:
        ---
        title: My Video
        tags: [a, b, c]
        privacy: unlisted
        thumbnail: thumb.jpg
        ---

        Description body here...

    Returns:
        Dict with frontmatter fields + 'description' from body
    """
    # Match YAML frontmatter between --- markers
    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.match(pattern, content, re.DOTALL)

    if not match:
        # No frontmatter, treat entire content as description
        return {"description": content.strip()}

    frontmatter_str, body = match.groups()

    try:
        metadata = yaml.safe_load(frontmatter_str) or {}
    except yaml.YAMLError:
        metadata = {}

    metadata["description"] = body.strip()
    return metadata


def date_range_from_days(days: int) -> tuple[str, str]:
    """Convert a 'days back' count to (start_date, end_date) strings for Analytics API."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Video:
    """A YouTube video with computed metrics."""

    video_id: str
    title: str
    url: str
    channel_name: str
    published_at: str
    view_count: int
    like_count: int
    comment_count: int
    engagement_rate: float
    views_per_day: float
    outlier_score: float | None = None
    is_outlier: bool | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class ChannelInfo:
    """Information about a YouTube channel."""

    channel_id: str
    name: str
    subscriber_count: int
    total_video_count: int
    handle: str | None = None


@dataclass
class ChannelVideosResponse:
    """Response from get_channel_videos."""

    channel_name: str
    period_days: int
    total_videos: int
    avg_views: float
    std_dev_views: float
    videos: list[Video]


@dataclass
class SearchResponse:
    """Response from search_videos."""

    query: str
    total_results: int
    avg_views: float
    top_channels: list[dict]
    videos: list[Video]


# =============================================================================
# YouTube Service
# =============================================================================

@dataclass
class YouTubeResponse:
    """Base class for YouTube API responses."""
    title: str
    url: str

class YouTubeService:
    """YouTube Data API v3 wrapper providing research tools."""

    def __init__(self, api_key: str):
        self.youtube = build("youtube", "v3", developerKey=api_key)

    def resolve_channel(self, channel_input: str) -> ChannelInfo | dict:
        """Resolve a channel from @handle, URL, or channel ID."""
        try:
            channel_id = self._parse_channel_input(channel_input)
            if channel_id is None:
                return {"error": f"Could not parse channel input: {channel_input}"}

            if channel_id.startswith("@"):
                search_response = (
                    self.youtube.search()
                    .list(part="snippet", q=channel_id, type="channel", maxResults=1)
                    .execute()
                )
                if not search_response.get("items"):
                    return {"error": f"Channel not found: {channel_id}"}
                channel_id = search_response["items"][0]["snippet"]["channelId"]

            response = (
                self.youtube.channels()
                .list(part="snippet,statistics", id=channel_id)
                .execute()
            )
            
            if not response.get("items"):
                return {"error": f"Channel not found: {channel_input}"}

            item = response["items"][0]
            snippet = item["snippet"]
            stats = item["statistics"]

            return ChannelInfo(
                channel_id=item["id"],
                handle=snippet.get("customUrl"),
                name=snippet["title"],
                subscriber_count=int(stats.get("subscriberCount", 0)),
                total_video_count=int(stats.get("videoCount", 0)),
            )

        except HttpError as e:
            return {"error": f"YouTube API error: {e.reason}"}
        except Exception as e:
            return {"error": f"Error resolving channel: {str(e)}"}
        
    def upload_video(self, video_id: str):
        """ This is used to upload videos to YouTube. """
        if (not video_id):
            return {"error": "Video ID is required for upload."}

    def get_channel_videos(
        self, channel_id: str, days_back: int = 30, max_results: int = 50
    ) -> ChannelVideosResponse | dict:
        """Get videos from a channel with performance metrics and outlier analysis."""
        try:
            channel_response = (
                self.youtube.channels().list(part="snippet", id=channel_id).execute()
            )
            if not channel_response.get("items"):
                return {"error": f"Channel not found: {channel_id}"}

            channel_name = channel_response["items"][0]["snippet"]["title"]
            published_after = datetime.now(timezone.utc) - timedelta(days=days_back)

            search_response = (
                self.youtube.search()
                .list(
                    part="id",
                    channelId=channel_id,
                    type="video",
                    order="date",
                    publishedAfter=published_after.isoformat(),
                    maxResults=max_results,
                )
                .execute()
            )

            video_ids = [
                item["id"]["videoId"] for item in search_response.get("items", [])
            ]

            if not video_ids:
                return ChannelVideosResponse(
                    channel_name=channel_name,
                    period_days=days_back,
                    total_videos=0,
                    avg_views=0.0,
                    std_dev_views=0.0,
                    videos=[],
                )

            videos = self._fetch_video_details(video_ids)

            if not videos:
                return ChannelVideosResponse(
                    channel_name=channel_name,
                    period_days=days_back,
                    total_videos=0,
                    avg_views=0.0,
                    std_dev_views=0.0,
                    videos=[],
                )

            view_counts = [v.view_count for v in videos]
            avg_views = statistics.mean(view_counts)
            std_dev_views = (
                statistics.stdev(view_counts) if len(view_counts) > 1 else 0.0
            )

            for video in videos:
                if std_dev_views > 0:
                    video.outlier_score = round(
                        (video.view_count - avg_views) / std_dev_views, 2
                    )
                    video.is_outlier = video.outlier_score > 2.0
                else:
                    video.outlier_score = 0.0
                    video.is_outlier = False

            videos.sort(key=lambda v: v.outlier_score or 0, reverse=True)

            return ChannelVideosResponse(
                channel_name=channel_name,
                period_days=days_back,
                total_videos=len(videos),
                avg_views=round(avg_views, 2),
                std_dev_views=round(std_dev_views, 2),
                videos=videos,
            )

        except HttpError as e:
            return {"error": f"YouTube API error: {e.reason}"}
        except Exception as e:
            return {"error": f"Error fetching channel videos: {str(e)}"}

    def search_videos(
        self,
        query: str,
        max_results: int = 25,
        days_back: int | None = None,
        order_by: str = "relevance",
    ) -> SearchResponse | dict:
        """Search YouTube videos by keyword."""
        try:
            order_map = {
                "relevance": "relevance",
                "view_count": "viewCount",
                "date": "date",
            }
            order = order_map.get(order_by, "relevance")

            search_params: dict[str, Any] = {
                "part": "id",
                "q": query,
                "type": "video",
                "order": order,
                "maxResults": max_results,
            }

            if days_back is not None:
                published_after = datetime.now(timezone.utc) - timedelta(days=days_back)
                search_params["publishedAfter"] = published_after.isoformat()

            search_response = self.youtube.search().list(**search_params).execute()

            total_results = search_response.get("pageInfo", {}).get("totalResults", 0)
            video_ids = [
                item["id"]["videoId"] for item in search_response.get("items", [])
            ]

            if not video_ids:
                return SearchResponse(
                    query=query,
                    total_results=0,
                    avg_views=0.0,
                    top_channels=[],
                    videos=[],
                )

            videos = self._fetch_video_details(video_ids)
            avg_views = (
                statistics.mean([v.view_count for v in videos]) if videos else 0.0
            )

            channel_counts: dict[str, int] = {}
            for video in videos:
                channel_counts[video.channel_name] = (
                    channel_counts.get(video.channel_name, 0) + 1
                )

            top_channels = [
                {"name": name, "video_count": count}
                for name, count in sorted(
                    channel_counts.items(), key=lambda x: x[1], reverse=True
                )[:5]
            ]

            return SearchResponse(
                query=query,
                total_results=total_results,
                avg_views=round(avg_views, 2),
                top_channels=top_channels,
                videos=videos,
            )

        except HttpError as e:
            return {"error": f"YouTube API error: {e.reason}"}
        except Exception as e:
            return {"error": f"Error searching videos: {str(e)}"}

    def get_transcript(self, video_id: str, max_chars: int = 50000) -> dict:
        """Get video transcript/captions.

        Tries Supadata API first (if SUPADATA_API_KEY is set), then falls back
        to youtube-transcript-api if that fails.
        """
        # Try Supadata API first (avoids rate limiting)
        supadata_key = os.environ.get("SUPADATA_API_KEY")
        if supadata_key:
            result = self._get_transcript_supadata(video_id, supadata_key, max_chars)
            if "error" not in result:
                return result
            # Fall through to youtube-transcript-api if Supadata fails

        # Fallback to youtube-transcript-api
        return self._get_transcript_youtube_api(video_id, max_chars)

    def _get_transcript_supadata(
        self, video_id: str, api_key: str, max_chars: int = 50000
    ) -> dict:
        """Get transcript via Supadata API."""
        try:
            # Handle both video IDs and full URLs
            if video_id.startswith("http"):
                url = video_id
            else:
                url = f"https://youtu.be/{video_id}"

            response = requests.get(
                "https://api.supadata.ai/v1/transcript",
                params={"url": url},
                headers={"x-api-key": api_key},
                timeout=30,
            )

            if response.status_code == 401:
                return {"error": "Supadata API: Invalid API key"}
            if response.status_code == 404:
                return {"error": f"Supadata API: Transcript not found for {video_id}"}
            if response.status_code != 200:
                return {"error": f"Supadata API error: {response.status_code}"}

            data = response.json()

            # Extract transcript text from response
            # Supadata returns { "content": [...], "lang": "en", ... }
            content = data.get("content", [])
            if isinstance(content, list):
                full_text = " ".join(
                    item.get("text", "") for item in content if isinstance(item, dict)
                )
            else:
                full_text = str(content)

            if len(full_text) > max_chars:
                full_text = full_text[:max_chars] + "... [truncated]"

            return {
                "video_id": video_id,
                "language": data.get("lang", "unknown"),
                "is_generated": False,  # Supadata doesn't provide this info
                "transcript": full_text,
                "source": "supadata",
            }

        except requests.Timeout:
            return {"error": "Supadata API: Request timed out"}
        except requests.RequestException as e:
            return {"error": f"Supadata API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Supadata API error: {str(e)}"}

    def _get_transcript_youtube_api(self, video_id: str, max_chars: int = 50000) -> dict:
        """Get transcript via youtube-transcript-api (fallback)."""
        try:
            api = YouTubeTranscriptApi()
            # Try English first, then fall back to any available language
            try:
                transcript = api.fetch(video_id, languages=["en"])
                language = "en"
            except NoTranscriptFound:
                # Fall back to first available transcript
                transcript_list = api.list(video_id)
                transcript = transcript_list.find_transcript(
                    [t.language_code for t in transcript_list]
                ).fetch()
                language = transcript_list[0].language_code if transcript_list else "unknown"

            full_text = " ".join([snippet.text for snippet in transcript])

            if len(full_text) > max_chars:
                full_text = full_text[:max_chars] + "... [truncated]"

            return {
                "video_id": video_id,
                "language": language,
                "is_generated": getattr(transcript, 'is_generated', False),
                "transcript": full_text,
                "source": "youtube-transcript-api",
            }

        except TranscriptsDisabled:
            return {"error": f"Transcripts are disabled for video: {video_id}"}
        except NoTranscriptFound:
            return {"error": f"No transcript found for video: {video_id}"}
        except VideoUnavailable:
            return {"error": f"Video unavailable: {video_id}"}
        except Exception as e:
            return {"error": f"Error fetching transcript: {str(e)}"}

    def _parse_channel_input(self, channel_input: str) -> str | None:
        """Parse channel input and return channel ID or @handle."""
        channel_input = channel_input.strip()

        if channel_input.startswith("@"):
            return channel_input

        url_patterns = [
            r"(?:https?://)?(?:www\.)?youtube\.com/@([\w-]+)",
            r"(?:https?://)?(?:www\.)?youtube\.com/channel/(UC[\w-]+)",
            r"(?:https?://)?(?:www\.)?youtube\.com/c/([\w-]+)",
        ]

        for pattern in url_patterns:
            match = re.match(pattern, channel_input)
            if match:
                result = match.group(1)
                if not result.startswith("UC"):
                    return f"@{result}"
                return result

        if channel_input.startswith("UC"):
            return channel_input

        if re.match(r"^[\w-]+$", channel_input):
            return f"@{channel_input}"

        return None

    def _fetch_video_details(self, video_ids: list[str]) -> list[Video]:
        """Fetch detailed video information for a list of video IDs."""
        videos = []

        for i in range(0, len(video_ids), 50):
            batch_ids = video_ids[i : i + 50]

            response = (
                self.youtube.videos()
                .list(part="snippet,statistics", id=",".join(batch_ids))
                .execute()
            )

            for item in response.get("items", []):
                video = self._parse_video_item(item)
                if video:
                    videos.append(video)

        return videos

    def _parse_video_item(self, item: dict) -> Video | None:
        """Parse a YouTube API video item into a Video."""
        try:
            snippet = item["snippet"]
            stats = item.get("statistics", {})

            video_id = item["id"]
            published_at = datetime.fromisoformat(
                snippet["publishedAt"].replace("Z", "+00:00")
            )

            view_count = int(stats.get("viewCount", 0))
            like_count = int(stats.get("likeCount", 0))
            comment_count = int(stats.get("commentCount", 0))

            engagement_rate = 0.0
            if view_count > 0:
                engagement_rate = (like_count + comment_count) / view_count

            days_since_published = (datetime.now(timezone.utc) - published_at).days
            views_per_day = view_count / max(days_since_published, 1)

            return Video(
                video_id=video_id,
                title=snippet["title"],
                url=f"https://www.youtube.com/watch?v={video_id}",
                channel_name=snippet["channelTitle"],
                published_at=published_at.isoformat(),
                view_count=view_count,
                like_count=like_count,
                comment_count=comment_count,
                engagement_rate=round(engagement_rate, 4),
                views_per_day=round(views_per_day, 2),
                tags=snippet.get("tags", []),
            )
        except (KeyError, ValueError):
            return None


# =============================================================================
# YouTube Uploader (OAuth)
# =============================================================================

# OAuth scopes for uploading
UPLOAD_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

DEFAULT_TOKEN_PATH = Path.home() / ".youtube-agent" / "token.json"


class YouTubeUploader:
    """YouTube uploader using OAuth credentials."""

    def __init__(
        self,
        client_secrets_path: Path,
        token_path: Path = DEFAULT_TOKEN_PATH,
    ):
        self.client_secrets_path = Path(client_secrets_path)
        self.token_path = Path(token_path)

        if not self.client_secrets_path.exists():
            raise FileNotFoundError(
                f"Client secrets not found: {self.client_secrets_path}\n"
                "Download OAuth credentials from Google Cloud Console."
            )

        self.credentials = self._get_credentials()
        self.youtube = build("youtube", "v3", credentials=self.credentials)

    def _get_credentials(self) -> Credentials:
        """Get or refresh OAuth credentials."""
        credentials = None

        if self.token_path.exists():
            credentials = Credentials.from_authorized_user_file(
                str(self.token_path), UPLOAD_SCOPES
            )

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.client_secrets_path), UPLOAD_SCOPES
                )
                credentials = flow.run_local_server(port=0)

            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_path, "w") as f:
                f.write(credentials.to_json())

        return credentials

    def upload(
        self,
        video_path: Path,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
        category_id: str = "22",  # People & Blogs
        privacy: str = "private",
        thumbnail_path: Path | None = None,
    ) -> dict:
        """Upload a video to YouTube.

        Args:
            video_path: Path to video file
            title: Video title
            description: Video description
            tags: List of tags
            category_id: YouTube category ID (22 = People & Blogs, 10 = Music)
            privacy: private, unlisted, or public
            thumbnail_path: Optional thumbnail image

        Returns:
            Dict with video_id and url
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return {"error": f"Video file not found: {video_path}"}

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags or [],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=1024 * 1024,
        )

        try:
            request = self.youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"Upload progress: {int(status.progress() * 100)}%")

            video_id = response["id"]

            if thumbnail_path:
                self.set_thumbnail(video_id, thumbnail_path)

            return {
                "video_id": video_id,
                "url": f"https://youtube.com/watch?v={video_id}",
                "title": title,
                "privacy": privacy,
            }

        except HttpError as e:
            return {"error": f"Upload failed: {e.reason}"}
        except Exception as e:
            return {"error": f"Upload failed: {str(e)}"}

    def update_video(
        self,
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        category_id: str | None = None,
    ) -> dict:
        """Update video metadata.

        Args:
            video_id: YouTube video ID
            title: New title (optional)
            description: New description (optional)
            tags: New tags (optional)
            category_id: New category ID (optional)

        Returns:
            Dict with updated video info
        """
        try:
            # First get current video data
            response = self.youtube.videos().list(
                part="snippet",
                id=video_id,
            ).execute()

            if not response.get("items"):
                return {"error": f"Video not found: {video_id}"}

            current = response["items"][0]["snippet"]

            # Update only provided fields
            body = {
                "id": video_id,
                "snippet": {
                    "title": title if title is not None else current["title"],
                    "description": description if description is not None else current["description"],
                    "tags": tags if tags is not None else current.get("tags", []),
                    "categoryId": category_id if category_id is not None else current["categoryId"],
                },
            }

            result = self.youtube.videos().update(
                part="snippet",
                body=body,
            ).execute()

            return {
                "video_id": result["id"],
                "title": result["snippet"]["title"],
                "url": f"https://youtube.com/watch?v={result['id']}",
            }

        except HttpError as e:
            return {"error": f"Update failed: {e.reason}"}
        except Exception as e:
            return {"error": f"Update failed: {str(e)}"}

    def set_thumbnail(self, video_id: str, thumbnail_path: Path) -> dict:
        """Set custom thumbnail for a video."""
        thumbnail_path = Path(thumbnail_path)
        if not thumbnail_path.exists():
            return {"error": f"Thumbnail not found: {thumbnail_path}"}

        # Detect mimetype from file extension
        ext = thumbnail_path.suffix.lower()
        mimetype_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
        mimetype = mimetype_map.get(ext, "image/png")

        try:
            media = MediaFileUpload(str(thumbnail_path), mimetype=mimetype)
            self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=media,
            ).execute()
            return {"success": True, "video_id": video_id}

        except HttpError as e:
            return {"error": f"Thumbnail failed: {e.reason}"}
        except Exception as e:
            return {"error": f"Thumbnail failed: {str(e)}"}


# =============================================================================
# YouTube Analytics (OAuth)
# =============================================================================

ANALYTICS_SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]

ANALYTICS_TOKEN_PATH = Path.home() / ".youtube-agent" / "analytics_token.json"


class YouTubeAnalytics:
    """YouTube Analytics API v2 wrapper for channel performance data.

    Provides access to watch time, retention, traffic sources, demographics,
    impressions/CTR, and revenue data that the Data API v3 cannot provide.

    Requires OAuth credentials with yt-analytics.readonly scope.
    Revenue methods additionally require yt-analytics-monetary.readonly.
    """

    def __init__(
        self,
        client_secrets_path: Path,
        token_path: Path = ANALYTICS_TOKEN_PATH,
    ):
        self.client_secrets_path = Path(client_secrets_path)
        self.token_path = Path(token_path)

        if not self.client_secrets_path.exists():
            raise FileNotFoundError(
                f"Client secrets not found: {self.client_secrets_path}\n"
                "Download OAuth credentials from Google Cloud Console."
            )

        self.credentials = self._get_credentials()
        self.analytics = build("youtubeAnalytics", "v2", credentials=self.credentials)

    def _get_credentials(self) -> Credentials:
        """Get or refresh OAuth credentials for Analytics API."""
        credentials = None

        if self.token_path.exists():
            credentials = Credentials.from_authorized_user_file(
                str(self.token_path), ANALYTICS_SCOPES
            )

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.client_secrets_path), ANALYTICS_SCOPES
                )
                credentials = flow.run_local_server(port=0)

            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_path, "w") as f:
                f.write(credentials.to_json())

        return credentials

    def _query(self, **kwargs) -> dict:
        """Execute an analytics report query."""
        try:
            return self.analytics.reports().query(**kwargs).execute()
        except HttpError as e:
            return {"error": f"YouTube Analytics API error: {e.reason}"}

    def _parse_rows(self, response: dict) -> list[dict] | dict:
        """Parse Analytics API response into a list of row dicts."""
        if "error" in response:
            return response
        headers = [h["name"] for h in response.get("columnHeaders", [])]
        return [dict(zip(headers, row)) for row in response.get("rows", [])]

    def channel_stats(self, start_date: str, end_date: str) -> list[dict] | dict:
        """Daily channel metrics: views, watch time, avg duration, subs gained/lost."""
        response = self._query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
            dimensions="day",
            sort="-day",
        )
        return self._parse_rows(response)

    def top_videos(
        self, start_date: str, end_date: str, max_results: int = 20
    ) -> list[dict] | dict:
        """Top videos by views with engagement metrics."""
        response = self._query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,shares,subscribersGained,subscribersLost",
            dimensions="video",
            sort="-views",
            maxResults=max_results,
        )
        return self._parse_rows(response)

    def video_daily(
        self, video_id: str, start_date: str, end_date: str
    ) -> list[dict] | dict:
        """Daily metrics for a specific video."""
        response = self._query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,shares,subscribersGained,subscribersLost",
            dimensions="day",
            filters=f"video=={video_id}",
            sort="-day",
        )
        return self._parse_rows(response)

    def traffic_sources(self, start_date: str, end_date: str) -> list[dict] | dict:
        """Traffic source breakdown: where viewers find your videos."""
        response = self._query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType",
            sort="-views",
        )
        return self._parse_rows(response)

    def search_terms(
        self, start_date: str, end_date: str, max_results: int = 25
    ) -> list[dict] | dict:
        """YouTube search terms driving traffic to your channel."""
        response = self._query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceDetail",
            filters="insightTrafficSourceType==YT_SEARCH",
            sort="-views",
            maxResults=max_results,
        )
        return self._parse_rows(response)

    def demographics(self, start_date: str, end_date: str) -> list[dict] | dict:
        """Viewer demographics: age group and gender breakdown."""
        response = self._query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="viewerPercentage",
            dimensions="ageGroup,gender",
        )
        return self._parse_rows(response)

    def audience_retention(self, video_id: str) -> list[dict] | dict:
        """Audience retention curve for a specific video."""
        response = self._query(
            ids="channel==MINE",
            startDate="2020-01-01",
            endDate="2030-12-31",
            metrics="audienceWatchRatio,relativeRetentionPerformance",
            dimensions="elapsedVideoTimeRatio",
            filters=f"video=={video_id}",
        )
        return self._parse_rows(response)

    def geography(
        self, start_date: str, end_date: str, max_results: int = 25
    ) -> list[dict] | dict:
        """Views by country."""
        response = self._query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="country",
            sort="-views",
            maxResults=max_results,
        )
        return self._parse_rows(response)

    def revenue(self, start_date: str, end_date: str) -> list[dict] | dict:
        """Daily revenue metrics. Requires monetized channel."""
        response = self._query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="estimatedRevenue,estimatedAdRevenue,grossRevenue,cpm",
            dimensions="day",
            sort="-day",
        )
        return self._parse_rows(response)


# =============================================================================
# Output Formatters
# =============================================================================


def format_number(n: int | float) -> str:
    """Format large numbers for display (e.g., 1.2M, 45K)."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def print_channel_videos(result: ChannelVideosResponse) -> None:
    """Pretty print channel videos result."""
    print(f"\n{'=' * 60}")
    print(f"Channel: {result.channel_name}")
    print(f"Period: Last {result.period_days} days")
    print(f"Videos: {result.total_videos}")
    print(f"Avg Views: {format_number(result.avg_views)}")
    print(f"{'=' * 60}\n")

    if not result.videos:
        print("No videos found in this period.")
        return

    print("Top Videos by Outlier Score:\n")
    for i, video in enumerate(result.videos[:10], 1):
        outlier = f"[OUTLIER {video.outlier_score:.1f}x]" if video.is_outlier else ""
        print(f"{i}. {video.title}")
        print(f"   Views: {format_number(video.view_count)} | "
              f"Engagement: {video.engagement_rate:.2%} | "
              f"Score: {video.outlier_score:.2f} {outlier}")
        print(f"   {video.url}\n")


def print_search_results(result: SearchResponse) -> None:
    """Pretty print search results."""
    print(f"\n{'=' * 60}")
    print(f"Search: {result.query}")
    print(f"Results: {result.total_results:,}")
    print(f"Avg Views: {format_number(result.avg_views)}")
    print(f"{'=' * 60}\n")

    if result.top_channels:
        print("Top Channels:")
        for ch in result.top_channels:
            print(f"  - {ch['name']} ({ch['video_count']} videos)")
        print()

    if not result.videos:
        print("No videos found.")
        return

    print("Videos:\n")
    for i, video in enumerate(result.videos[:10], 1):
        print(f"{i}. {video.title}")
        print(f"   Channel: {video.channel_name} | Views: {format_number(video.view_count)}")
        print(f"   {video.url}\n")


def print_transcript(result: dict) -> None:
    """Pretty print transcript."""
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"\n{'=' * 60}")
    print(f"Video ID: {result['video_id']}")
    print(f"Language: {result['language']}")
    print(f"Generated: {result['is_generated']}")
    print(f"{'=' * 60}\n")
    print(result["transcript"])


def _fmt_duration(seconds: float) -> str:
    """Format seconds as M:SS."""
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}:{secs:02d}"


def _fmt_minutes(minutes: float) -> str:
    """Format minutes as hours or minutes."""
    if minutes >= 60:
        return f"{minutes / 60:.1f}h"
    return f"{minutes:.0f}m"


def print_channel_stats(rows: list[dict]) -> None:
    """Print daily channel statistics."""
    if not rows:
        print("\nNo channel data available.\n")
        return

    total_views = sum(r.get("views", 0) for r in rows)
    total_minutes = sum(r.get("estimatedMinutesWatched", 0) for r in rows)
    total_subs = sum(
        r.get("subscribersGained", 0) - r.get("subscribersLost", 0) for r in rows
    )

    print(f"\n{'=' * 60}")
    print("Channel Daily Stats")
    print(f"{'=' * 60}")
    print(f"  Total Views: {format_number(total_views)}")
    print(f"  Watch Time:  {_fmt_minutes(total_minutes)}")
    print(f"  Net Subs:    {'+' if total_subs >= 0 else ''}{total_subs}")
    print(f"{'=' * 60}\n")

    print(f"{'Date':<12} {'Views':>8} {'Watch':>8} {'Avg Dur':>8} {'Subs':>6}")
    print(f"{'-' * 12} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 6}")

    for row in rows:
        date = row.get("day", "")
        views = row.get("views", 0)
        minutes = row.get("estimatedMinutesWatched", 0)
        avg_dur = row.get("averageViewDuration", 0)
        subs_net = row.get("subscribersGained", 0) - row.get("subscribersLost", 0)
        subs_str = f"{'+' if subs_net >= 0 else ''}{subs_net}"

        print(
            f"{date:<12} {format_number(views):>8} "
            f"{_fmt_minutes(minutes):>8} {_fmt_duration(avg_dur):>8} {subs_str:>6}"
        )
    print()


def print_top_videos(rows: list[dict]) -> None:
    """Print top videos by views."""
    if not rows:
        print("\nNo video data available.\n")
        return

    print(f"\n{'=' * 60}")
    print("Top Videos by Views")
    print(f"{'=' * 60}\n")

    for i, row in enumerate(rows, 1):
        vid = row.get("video", "?")
        views = row.get("views", 0)
        minutes = row.get("estimatedMinutesWatched", 0)
        avg_dur = row.get("averageViewDuration", 0)
        avg_pct = row.get("averageViewPercentage", 0)
        likes = row.get("likes", 0)
        shares = row.get("shares", 0)
        subs = row.get("subscribersGained", 0) - row.get("subscribersLost", 0)

        print(f"{i:>2}. {vid}")
        print(
            f"    Views: {format_number(views)} | "
            f"Watch: {_fmt_minutes(minutes)} | "
            f"Avg: {_fmt_duration(avg_dur)} ({avg_pct:.0f}%)"
        )
        print(
            f"    Likes: {format_number(likes)} | "
            f"Shares: {format_number(shares)} | "
            f"Subs: {'+' if subs >= 0 else ''}{subs}"
        )
        print()


def print_video_daily(rows: list[dict], video_id: str) -> None:
    """Print daily metrics for a specific video."""
    if not rows:
        print(f"\nNo data for video {video_id}.\n")
        return

    total_views = sum(r.get("views", 0) for r in rows)
    total_minutes = sum(r.get("estimatedMinutesWatched", 0) for r in rows)

    print(f"\n{'=' * 60}")
    print(f"Video: {video_id}")
    print(f"{'=' * 60}")
    print(f"  Total Views: {format_number(total_views)}")
    print(f"  Watch Time:  {_fmt_minutes(total_minutes)}")
    print(f"{'=' * 60}\n")

    print(
        f"{'Date':<12} {'Views':>8} {'Watch':>8} {'Avg Dur':>8} "
        f"{'Avg %':>6} {'Likes':>6} {'Shares':>6}"
    )
    print(
        f"{'-' * 12} {'-' * 8} {'-' * 8} {'-' * 8} "
        f"{'-' * 6} {'-' * 6} {'-' * 6}"
    )

    for row in rows:
        date = row.get("day", "")
        views = row.get("views", 0)
        minutes = row.get("estimatedMinutesWatched", 0)
        avg_dur = row.get("averageViewDuration", 0)
        avg_pct = row.get("averageViewPercentage", 0)
        likes = row.get("likes", 0)
        shares = row.get("shares", 0)

        print(
            f"{date:<12} {format_number(views):>8} "
            f"{_fmt_minutes(minutes):>8} {_fmt_duration(avg_dur):>8} "
            f"{avg_pct:>5.0f}% {format_number(likes):>6} {format_number(shares):>6}"
        )
    print()


def print_traffic_sources(rows: list[dict]) -> None:
    """Print traffic source breakdown."""
    if not rows:
        print("\nNo traffic source data available.\n")
        return

    total_views = sum(r.get("views", 0) for r in rows)

    print(f"\n{'=' * 60}")
    print("Traffic Sources")
    print(f"{'=' * 60}\n")

    print(f"{'Source':<30} {'Views':>10} {'%':>6} {'Watch':>8}")
    print(f"{'-' * 30} {'-' * 10} {'-' * 6} {'-' * 8}")

    for row in rows:
        source = row.get("insightTrafficSourceType", "?")
        views = row.get("views", 0)
        minutes = row.get("estimatedMinutesWatched", 0)
        pct = (views / total_views * 100) if total_views > 0 else 0

        print(
            f"{source:<30} {format_number(views):>10} "
            f"{pct:>5.1f}% {_fmt_minutes(minutes):>8}"
        )
    print()


def print_search_terms_report(rows: list[dict]) -> None:
    """Print search terms driving traffic."""
    if not rows:
        print("\nNo search term data available.\n")
        return

    print(f"\n{'=' * 60}")
    print("YouTube Search Terms")
    print(f"{'=' * 60}\n")

    print(f"{'Term':<40} {'Views':>8} {'Watch':>8}")
    print(f"{'-' * 40} {'-' * 8} {'-' * 8}")

    for row in rows:
        term = row.get("insightTrafficSourceDetail", "?")
        views = row.get("views", 0)
        minutes = row.get("estimatedMinutesWatched", 0)

        # Truncate long search terms
        if len(term) > 38:
            term = term[:35] + "..."

        print(f"{term:<40} {format_number(views):>8} {_fmt_minutes(minutes):>8}")
    print()


def print_demographics(rows: list[dict]) -> None:
    """Print viewer demographics."""
    if not rows:
        print("\nNo demographic data available (channel may be too small).\n")
        return

    print(f"\n{'=' * 60}")
    print("Viewer Demographics")
    print(f"{'=' * 60}\n")

    print(f"{'Age Group':<12} {'Gender':<10} {'Viewers %':>10}")
    print(f"{'-' * 12} {'-' * 10} {'-' * 10}")

    for row in rows:
        age = row.get("ageGroup", "?")
        gender = row.get("gender", "?")
        pct = row.get("viewerPercentage", 0)
        print(f"{age:<12} {gender:<10} {pct:>9.1f}%")
    print()


def print_retention(rows: list[dict], video_id: str) -> None:
    """Print audience retention curve."""
    if not rows:
        print(f"\nNo retention data for video {video_id}.\n")
        return

    print(f"\n{'=' * 60}")
    print(f"Audience Retention: {video_id}")
    print(f"{'=' * 60}\n")

    print(f"{'Position':>10} {'Retention':>10} {'vs Similar':>10}")
    print(f"{'-' * 10} {'-' * 10} {'-' * 10}")

    for row in rows:
        elapsed = row.get("elapsedVideoTimeRatio", 0)
        watch_ratio = row.get("audienceWatchRatio", 0)
        relative = row.get("relativeRetentionPerformance", 0)

        pos_str = f"{elapsed * 100:.0f}%"
        ret_str = f"{watch_ratio * 100:.1f}%"
        # relative > 0 means above average, < 0 below average
        if relative > 0:
            rel_str = f"+{relative:.2f}"
        else:
            rel_str = f"{relative:.2f}"

        print(f"{pos_str:>10} {ret_str:>10} {rel_str:>10}")
    print()


def print_geography(rows: list[dict]) -> None:
    """Print geography breakdown."""
    if not rows:
        print("\nNo geographic data available.\n")
        return

    total_views = sum(r.get("views", 0) for r in rows)

    print(f"\n{'=' * 60}")
    print("Views by Country")
    print(f"{'=' * 60}\n")

    print(f"{'Country':<10} {'Views':>10} {'%':>6} {'Watch':>8}")
    print(f"{'-' * 10} {'-' * 10} {'-' * 6} {'-' * 8}")

    for row in rows:
        country = row.get("country", "?")
        views = row.get("views", 0)
        minutes = row.get("estimatedMinutesWatched", 0)
        pct = (views / total_views * 100) if total_views > 0 else 0

        print(
            f"{country:<10} {format_number(views):>10} "
            f"{pct:>5.1f}% {_fmt_minutes(minutes):>8}"
        )
    print()


def print_revenue(rows: list[dict]) -> None:
    """Print daily revenue."""
    if not rows:
        print("\nNo revenue data available (channel may not be monetized).\n")
        return

    total_revenue = sum(r.get("estimatedRevenue", 0) for r in rows)

    print(f"\n{'=' * 60}")
    print("Revenue")
    print(f"{'=' * 60}")
    print(f"  Total Estimated Revenue: ${total_revenue:.2f}")
    print(f"{'=' * 60}\n")

    print(f"{'Date':<12} {'Revenue':>10} {'Ad Rev':>10} {'Gross':>10} {'CPM':>8}")
    print(f"{'-' * 12} {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 8}")

    for row in rows:
        date = row.get("day", "")
        rev = row.get("estimatedRevenue", 0)
        ad_rev = row.get("estimatedAdRevenue", 0)
        gross = row.get("grossRevenue", 0)
        cpm = row.get("cpm", 0)

        print(
            f"{date:<12} ${rev:>9.2f} ${ad_rev:>9.2f} "
            f"${gross:>9.2f} ${cpm:>7.2f}"
        )
    print()


# =============================================================================
# CLI Commands
# =============================================================================


def cmd_get_channel_videos(args: argparse.Namespace, service: YouTubeService) -> None:
    """Handle get_channel_videos command."""
    channel_info = service.resolve_channel(args.handle)
    if isinstance(channel_info, dict) and "error" in channel_info:
        if args.json:
            print(json.dumps(channel_info, indent=2))
        else:
            print(f"Error: {channel_info['error']}")
        sys.exit(1)

    result = service.get_channel_videos(
        channel_id=channel_info.channel_id,
        days_back=args.days,
        max_results=args.max,
    )

    if isinstance(result, dict) and "error" in result:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Error: {result['error']}")
        sys.exit(1)

    if args.json:
        print(json.dumps(asdict(result), indent=2, default=str))
    else:
        print_channel_videos(result)


def cmd_search_videos(args: argparse.Namespace, service: YouTubeService) -> None:
    """Handle search_videos command."""
    result = service.search_videos(
        query=args.query,
        max_results=args.max,
        days_back=args.days,
        order_by=args.order,
    )

    if isinstance(result, dict) and "error" in result:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Error: {result['error']}")
        sys.exit(1)

    if args.json:
        print(json.dumps(asdict(result), indent=2, default=str))
    else:
        print_search_results(result)


def cmd_get_transcript(args: argparse.Namespace, service: YouTubeService) -> None:
    """Handle get_transcript command."""
    result = service.get_transcript(args.video_id, max_chars=args.max_chars)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_transcript(result)

    if "error" in result:
        sys.exit(1)


def cmd_upload(args: argparse.Namespace) -> None:
    """Handle upload command."""
    client_secrets = os.environ.get("YOUTUBE_CLIENT_SECRETS")
    if not client_secrets:
        print("Error: YOUTUBE_CLIENT_SECRETS environment variable not set", file=sys.stderr)
        print("Set it to the path of your OAuth client_secrets.json file", file=sys.stderr)
        sys.exit(1)

    try:
        uploader = YouTubeUploader(Path(client_secrets))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Load from metadata file if provided
    if args.metadata:
        metadata_path = Path(args.metadata)
        if not metadata_path.exists():
            print(f"Error: Metadata file not found: {metadata_path}", file=sys.stderr)
            sys.exit(1)

        with open(metadata_path) as f:
            content = f.read()

        # Parse based on file extension
        if metadata_path.suffix.lower() == ".md":
            metadata = parse_markdown_metadata(content)
        else:
            metadata = yaml.safe_load(content) or {}

        title = metadata.get("title", args.title)
        description = metadata.get("description", args.description or "")
        tags = metadata.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        category_id = str(metadata.get("category", args.category))
        privacy = metadata.get("privacy", args.privacy)
        # Thumbnail from metadata, but --thumbnail flag overrides
        thumbnail = args.thumbnail or metadata.get("thumbnail")
        thumbnail_path = Path(thumbnail) if thumbnail else None
    else:
        title = args.title
        description = args.description or ""
        tags = args.tags.split(",") if args.tags else []
        category_id = args.category
        privacy = args.privacy
        thumbnail_path = Path(args.thumbnail) if args.thumbnail else None

    if not title:
        print("Error: --title is required (or provide in metadata file)", file=sys.stderr)
        sys.exit(1)

    result = uploader.upload(
        video_path=Path(args.video),
        title=title,
        description=description,
        tags=tags,
        category_id=category_id,
        privacy=privacy,
        thumbnail_path=thumbnail_path,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    elif "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
    else:
        print(f"Uploaded: {result['url']}")
        print(f"Video ID: {result['video_id']}")
        print(f"Privacy: {result['privacy']}")


# -- Analytics CLI handlers --------------------------------------------------


def _get_analytics_service() -> YouTubeAnalytics:
    """Create a YouTubeAnalytics instance from env vars."""
    client_secrets = os.environ.get("YOUTUBE_CLIENT_SECRETS")
    if not client_secrets:
        print(
            "Error: YOUTUBE_CLIENT_SECRETS environment variable not set",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return YouTubeAnalytics(Path(client_secrets))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _analytics_result(result: list[dict] | dict, args: argparse.Namespace, printer) -> None:
    """Handle analytics result: check for errors, print JSON or formatted."""
    if isinstance(result, dict) and "error" in result:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Error: {result['error']}")
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        printer(result)


def cmd_channel_stats(args: argparse.Namespace) -> None:
    svc = _get_analytics_service()
    start, end = date_range_from_days(args.days)
    result = svc.channel_stats(start, end)
    _analytics_result(result, args, print_channel_stats)


def cmd_top_videos(args: argparse.Namespace) -> None:
    svc = _get_analytics_service()
    start, end = date_range_from_days(args.days)
    result = svc.top_videos(start, end, max_results=args.max)
    _analytics_result(result, args, print_top_videos)


def cmd_video_daily(args: argparse.Namespace) -> None:
    svc = _get_analytics_service()
    start, end = date_range_from_days(args.days)
    result = svc.video_daily(args.video_id, start, end)
    _analytics_result(
        result, args, lambda rows: print_video_daily(rows, args.video_id)
    )


def cmd_traffic_sources(args: argparse.Namespace) -> None:
    svc = _get_analytics_service()
    start, end = date_range_from_days(args.days)
    result = svc.traffic_sources(start, end)
    _analytics_result(result, args, print_traffic_sources)


def cmd_search_terms(args: argparse.Namespace) -> None:
    svc = _get_analytics_service()
    start, end = date_range_from_days(args.days)
    result = svc.search_terms(start, end, max_results=args.max)
    _analytics_result(result, args, print_search_terms_report)


def cmd_demographics(args: argparse.Namespace) -> None:
    svc = _get_analytics_service()
    start, end = date_range_from_days(args.days)
    result = svc.demographics(start, end)
    _analytics_result(result, args, print_demographics)


def cmd_retention(args: argparse.Namespace) -> None:
    svc = _get_analytics_service()
    result = svc.audience_retention(args.video_id)
    _analytics_result(
        result, args, lambda rows: print_retention(rows, args.video_id)
    )


def cmd_geography(args: argparse.Namespace) -> None:
    svc = _get_analytics_service()
    start, end = date_range_from_days(args.days)
    result = svc.geography(start, end, max_results=args.max)
    _analytics_result(result, args, print_geography)


def cmd_revenue(args: argparse.Namespace) -> None:
    svc = _get_analytics_service()
    start, end = date_range_from_days(args.days)
    result = svc.revenue(start, end)
    _analytics_result(result, args, print_revenue)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="YouTube Tool - Research, upload, and analytics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run youtube.py get_channel_videos @mkbhd --days 30
    uv run youtube.py search_videos "AI agents" --max 20 --order view_count
    uv run youtube.py get_transcript dQw4w9WgXcQ
    uv run youtube.py upload video.mp4 --title "My Video" --privacy unlisted

Analytics (requires OAuth via YOUTUBE_CLIENT_SECRETS):
    uv run youtube.py channel_stats --days 30
    uv run youtube.py top_videos --days 30
    uv run youtube.py video_daily VIDEO_ID --days 30
    uv run youtube.py traffic_sources --days 30
    uv run youtube.py search_terms --days 30
    uv run youtube.py demographics --days 90
    uv run youtube.py retention VIDEO_ID
    uv run youtube.py geography --days 30
    uv run youtube.py revenue --days 30
        """,
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # get_channel_videos
    p_channel = subparsers.add_parser(
        "get_channel_videos",
        help="Get videos from a channel with outlier analysis",
    )
    p_channel.add_argument("handle", help="Channel @handle, URL, or ID")
    p_channel.add_argument("--days", type=int, default=30, help="Days to look back")
    p_channel.add_argument("--max", type=int, default=50, help="Max videos to fetch")
    p_channel.add_argument("--json", action="store_true", help="Output as JSON")

    # search_videos
    p_search = subparsers.add_parser("search_videos", help="Search YouTube videos")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--max", type=int, default=25, help="Max results")
    p_search.add_argument("--days", type=int, default=None, help="Filter by days")
    p_search.add_argument(
        "--order",
        choices=["relevance", "view_count", "date"],
        default="relevance",
        help="Sort order",
    )
    p_search.add_argument("--json", action="store_true", help="Output as JSON")

    # get_transcript
    p_transcript = subparsers.add_parser(
        "get_transcript", help="Get video transcript/captions"
    )
    p_transcript.add_argument("video_id", help="YouTube video ID")
    p_transcript.add_argument(
        "--max-chars", type=int, default=5000, help="Max transcript chars"
    )
    p_transcript.add_argument("--json", action="store_true", help="Output as JSON")

    # upload
    p_upload = subparsers.add_parser("upload", help="Upload a video to YouTube")
    p_upload.add_argument("video", help="Path to video file")
    p_upload.add_argument("--metadata", help="Path to metadata file (.md or .yaml)")
    p_upload.add_argument("--title", help="Video title (required if no metadata file)")
    p_upload.add_argument("--description", help="Video description")
    p_upload.add_argument("--tags", help="Comma-separated tags")
    p_upload.add_argument("--category", default="22", help="Category ID (default: 22)")
    p_upload.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        default="private",
        help="Privacy status (default: private)",
    )
    p_upload.add_argument("--thumbnail", help="Path to thumbnail image")
    p_upload.add_argument("--json", action="store_true", help="Output as JSON")

    # set_thumbnail
    p_thumb = subparsers.add_parser("set_thumbnail", help="Set thumbnail for existing video")
    p_thumb.add_argument("video_id", help="YouTube video ID")
    p_thumb.add_argument("thumbnail", help="Path to thumbnail image")

    # update
    p_update = subparsers.add_parser("update", help="Update video metadata")
    p_update.add_argument("video_id", help="YouTube video ID")
    p_update.add_argument("--metadata", help="Path to metadata file (.md or .yaml)")
    p_update.add_argument("--title", help="New title")
    p_update.add_argument("--description", help="New description")
    p_update.add_argument("--tags", help="Comma-separated tags")

    # -- Analytics subcommands -----------------------------------------------

    # channel_stats
    p_cstats = subparsers.add_parser(
        "channel_stats", help="Daily channel metrics (views, watch time, subs)"
    )
    p_cstats.add_argument("--days", type=int, default=30, help="Days to look back")
    p_cstats.add_argument("--json", action="store_true", help="Output as JSON")

    # top_videos
    p_topvid = subparsers.add_parser(
        "top_videos", help="Top videos by views with engagement metrics"
    )
    p_topvid.add_argument("--days", type=int, default=30, help="Days to look back")
    p_topvid.add_argument("--max", type=int, default=20, help="Max videos")
    p_topvid.add_argument("--json", action="store_true", help="Output as JSON")

    # video_daily
    p_vdaily = subparsers.add_parser(
        "video_daily", help="Daily metrics for a specific video"
    )
    p_vdaily.add_argument("video_id", help="YouTube video ID")
    p_vdaily.add_argument("--days", type=int, default=30, help="Days to look back")
    p_vdaily.add_argument("--json", action="store_true", help="Output as JSON")

    # traffic_sources
    p_traffic = subparsers.add_parser(
        "traffic_sources", help="Traffic source breakdown"
    )
    p_traffic.add_argument("--days", type=int, default=30, help="Days to look back")
    p_traffic.add_argument("--json", action="store_true", help="Output as JSON")

    # search_terms
    p_sterms = subparsers.add_parser(
        "search_terms", help="YouTube search terms driving traffic"
    )
    p_sterms.add_argument("--days", type=int, default=30, help="Days to look back")
    p_sterms.add_argument("--max", type=int, default=25, help="Max terms")
    p_sterms.add_argument("--json", action="store_true", help="Output as JSON")

    # demographics
    p_demo = subparsers.add_parser(
        "demographics", help="Viewer age/gender demographics"
    )
    p_demo.add_argument("--days", type=int, default=90, help="Days to look back")
    p_demo.add_argument("--json", action="store_true", help="Output as JSON")

    # retention
    p_ret = subparsers.add_parser(
        "retention", help="Audience retention curve for a video"
    )
    p_ret.add_argument("video_id", help="YouTube video ID")
    p_ret.add_argument("--json", action="store_true", help="Output as JSON")

    # geography
    p_geo = subparsers.add_parser("geography", help="Views by country")
    p_geo.add_argument("--days", type=int, default=30, help="Days to look back")
    p_geo.add_argument("--max", type=int, default=25, help="Max countries")
    p_geo.add_argument("--json", action="store_true", help="Output as JSON")

    # revenue
    p_rev = subparsers.add_parser(
        "revenue", help="Daily revenue (requires monetized channel)"
    )
    p_rev.add_argument("--days", type=int, default=30, help="Days to look back")
    p_rev.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # -- Analytics commands (OAuth) ------------------------------------------
    analytics_commands = {
        "channel_stats": cmd_channel_stats,
        "top_videos": cmd_top_videos,
        "video_daily": cmd_video_daily,
        "traffic_sources": cmd_traffic_sources,
        "search_terms": cmd_search_terms,
        "demographics": cmd_demographics,
        "retention": cmd_retention,
        "geography": cmd_geography,
        "revenue": cmd_revenue,
    }

    if args.command in analytics_commands:
        analytics_commands[args.command](args)
        return

    # -- Upload/update commands (OAuth) --------------------------------------
    if args.command == "upload":
        cmd_upload(args)
        return

    # Set thumbnail command uses OAuth
    if args.command == "set_thumbnail":
        client_secrets = os.environ.get("YOUTUBE_CLIENT_SECRETS")
        if not client_secrets:
            print("Error: YOUTUBE_CLIENT_SECRETS environment variable not set", file=sys.stderr)
            sys.exit(1)
        uploader = YouTubeUploader(Path(client_secrets))
        result = uploader.set_thumbnail(args.video_id, Path(args.thumbnail))
        if "error" in result:
            print(f"Error: {result['error']}")
            sys.exit(1)
        print(f"Thumbnail set for video: {args.video_id}")
        return

    # Update video command uses OAuth
    if args.command == "update":
        client_secrets = os.environ.get("YOUTUBE_CLIENT_SECRETS")
        if not client_secrets:
            print("Error: YOUTUBE_CLIENT_SECRETS environment variable not set", file=sys.stderr)
            sys.exit(1)
        uploader = YouTubeUploader(Path(client_secrets))

        title = args.title
        description = args.description
        tags = args.tags.split(",") if args.tags else None

        # Load from metadata file if provided
        if args.metadata:
            metadata_path = Path(args.metadata)
            if not metadata_path.exists():
                print(f"Error: Metadata file not found: {metadata_path}", file=sys.stderr)
                sys.exit(1)
            with open(metadata_path) as f:
                content = f.read()
            if metadata_path.suffix.lower() == ".md":
                metadata = parse_markdown_metadata(content)
            else:
                metadata = yaml.safe_load(content) or {}
            title = title or metadata.get("title")
            description = description or metadata.get("description")
            if not tags and "tags" in metadata:
                tags = metadata["tags"]
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",")]

        result = uploader.update_video(
            video_id=args.video_id,
            title=title,
            description=description,
            tags=tags,
        )
        if "error" in result:
            print(f"Error: {result['error']}")
            sys.exit(1)
        print(f"Updated: {result['url']}")
        print(f"Title: {result['title']}")
        return

    # -- Research commands (API key) -----------------------------------------
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("Error: YOUTUBE_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    service = YouTubeService(api_key)

    commands = {
        "get_channel_videos": cmd_get_channel_videos,
        "search_videos": cmd_search_videos,
        "get_transcript": cmd_get_transcript,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args, service)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
