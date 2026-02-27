#!/usr/bin/env python3
# /// script
# dependencies = [
#   "youtube-transcript-api>=0.6.0",
#   "requests>=2.31.0",
# ]
# ///
"""
YouTube transcript tool.

Usage:
    uv run tools/youtube.py get_transcript VIDEO_ID
    uv run tools/youtube.py get_transcript VIDEO_ID --max-chars 10000
    uv run tools/youtube.py get_transcript VIDEO_ID --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)


def get_transcript(video_id: str, max_chars: int = 50000) -> dict:
    """Get video transcript/captions.

    Tries Supadata API first (if SUPADATA_API_KEY is set), then falls back
    to youtube-transcript-api.
    """
    supadata_key = os.environ.get("SUPADATA_API_KEY")
    if supadata_key:
        result = _get_transcript_supadata(video_id, supadata_key, max_chars)
        if "error" not in result:
            return result

    return _get_transcript_youtube_api(video_id, max_chars)


def _get_transcript_supadata(
    video_id: str, api_key: str, max_chars: int = 50000
) -> dict:
    """Get transcript via Supadata API."""
    try:
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
            "is_generated": False,
            "transcript": full_text,
            "source": "supadata",
        }

    except requests.Timeout:
        return {"error": "Supadata API: Request timed out"}
    except requests.RequestException as e:
        return {"error": f"Supadata API error: {str(e)}"}
    except Exception as e:
        return {"error": f"Supadata API error: {str(e)}"}


def _get_transcript_youtube_api(video_id: str, max_chars: int = 50000) -> dict:
    """Get transcript via youtube-transcript-api (fallback)."""
    try:
        api = YouTubeTranscriptApi()
        try:
            transcript = api.fetch(video_id, languages=["en"])
            language = "en"
        except NoTranscriptFound:
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
            "is_generated": getattr(transcript, "is_generated", False),
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


def main():
    parser = argparse.ArgumentParser(description="YouTube transcript tool")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("get_transcript", help="Get video transcript")
    p.add_argument("video_id", help="YouTube video ID or URL")
    p.add_argument("--max-chars", type=int, default=50000, help="Max transcript chars")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.command != "get_transcript":
        parser.print_help()
        sys.exit(1)

    # Extract video ID from URL if needed
    vid = args.video_id
    if "youtube.com" in vid:
        vid = vid.split("v=")[-1].split("&")[0]
    elif "youtu.be" in vid:
        vid = vid.split("/")[-1].split("?")[0]

    result = get_transcript(vid, max_chars=args.max_chars)

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Video: {result['video_id']} | Language: {result['language']}")
        print(f"Source: {result['source']}\n")
        print(result["transcript"])


if __name__ == "__main__":
    main()
