"""
detector.py — monitors multiple YouTube channels for new uploads.
Uses public RSS feeds — no API quota consumed.
Channel handles are resolved to IDs via yt-dlp (one-time per handle).

Also provides get_old_videos_for_daily() which picks unseen old videos
from a random subset of channels for the daily Reel fallback.
"""

import json
import os
import random
import subprocess
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import requests


RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

# All channels to monitor — handles and direct IDs both supported
CHANNELS = [
    "https://www.youtube.com/@fifa",
    "https://www.youtube.com/@AdamBobrow",
    "https://www.youtube.com/@wttglobal",
    "https://www.youtube.com/@SportsTak",
    "https://www.youtube.com/@WorldAthletics",
    "https://www.youtube.com/@Olympics",
    "https://www.youtube.com/@SPORTSINDIA09",
    "https://www.youtube.com/channel/UCgq3yo_CiroLdMzd3DG3ihw",
    "https://www.youtube.com/@starsports",
    "https://www.youtube.com/@BeanymanSports",
    "https://www.youtube.com/@henriklehmannn",
]

# How many channels to pick for daily Reels when no new videos exist.
# Keep this low (3-5) to avoid heavy load — each needs a full download.
DAILY_CHANNEL_QUOTA = 4

# Cache file so we don't re-resolve handles on every run
CHANNEL_ID_CACHE = "channel_id_cache.json"

# Tracks which old videos have already been used for daily Reels
DAILY_SEEN_FILE = "daily_seen.json"


# ─────────────────────────────────────────────────────────────────────────────
# Channel ID resolution
# ─────────────────────────────────────────────────────────────────────────────

def resolve_channel_id(channel_url: str) -> str | None:
    """
    Resolve a YouTube channel URL (handle or /channel/) to its channel ID.
    Uses yt-dlp which handles all URL formats reliably.
    """
    if "/channel/UC" in channel_url:
        return channel_url.split("/channel/")[1].split("/")[0]

    try:
        result = subprocess.run(
            ["yt-dlp", "--playlist-items", "1", "--print", "channel_id", channel_url],
            capture_output=True, text=True, timeout=30
        )
        channel_id = result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
        return channel_id if channel_id else None
    except Exception as e:
        print(f"  Could not resolve channel ID for {channel_url}: {e}")
        return None


def load_channel_id_cache() -> dict:
    if Path(CHANNEL_ID_CACHE).exists():
        with open(CHANNEL_ID_CACHE) as f:
            return json.load(f)
    return {}


def save_channel_id_cache(cache: dict):
    with open(CHANNEL_ID_CACHE, "w") as f:
        json.dump(cache, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# RSS parsing
# ─────────────────────────────────────────────────────────────────────────────

def get_all_videos_for_channel(channel_id: str, channel_name: str) -> list[dict]:
    """
    Fetch all videos (up to 15) from a channel's RSS feed.
    Returns newest-first list of video dicts.
    """
    url = RSS_URL.format(channel_id=channel_id)
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  RSS fetch failed for {channel_name}: {e}")
        return []

    root = ET.fromstring(resp.text)
    videos = []
    for entry in root.findall("atom:entry", NS):
        video_id = entry.find("yt:videoId", NS).text
        title    = entry.find("atom:title", NS).text
        videos.append({
            "id":      video_id,
            "title":   title,
            "url":     f"https://www.youtube.com/watch?v={video_id}",
            "channel": channel_name,
        })
    return videos


def get_latest_video_for_channel(channel_id: str, channel_name: str) -> dict | None:
    """Fetch only the most recent video from a channel RSS feed."""
    videos = get_all_videos_for_channel(channel_id, channel_name)
    return videos[0] if videos else None


# ─────────────────────────────────────────────────────────────────────────────
# New video detection
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_all_channels() -> dict:
    """Return {channel_url: channel_id} for all channels, using cache."""
    cache = load_channel_id_cache()
    resolved = {}
    for channel_url in CHANNELS:
        channel_name = channel_url.split("@")[-1].split("/channel/")[-1]
        if channel_url in cache:
            resolved[channel_url] = cache[channel_url]
        else:
            print(f"  Resolving channel ID for {channel_name}...")
            channel_id = resolve_channel_id(channel_url)
            if channel_id:
                cache[channel_url] = channel_id
                save_channel_id_cache(cache)
                resolved[channel_url] = channel_id
            else:
                print(f"  Skipping {channel_name} — could not resolve ID.")
    return resolved


def get_new_videos(seen: dict) -> list[dict]:
    """
    Check all channels and return list of new (unseen) videos.
    """
    resolved = _resolve_all_channels()
    new_videos = []

    for channel_url, channel_id in resolved.items():
        channel_name = channel_url.split("@")[-1].split("/channel/")[-1]
        print(f"Checking {channel_name}...")

        video = get_latest_video_for_channel(channel_id, channel_name)
        if not video:
            continue

        if video["id"] not in seen:
            print(f"  ✓ New video: {video['title']}")
            new_videos.append(video)
        else:
            print(f"  Already seen: {video['title']}")

    return new_videos


# ─────────────────────────────────────────────────────────────────────────────
# Daily Reel fallback — old videos
# ─────────────────────────────────────────────────────────────────────────────

def load_daily_seen() -> dict:
    """Load the daily-seen tracker {video_id: {title, channel, date}}."""
    if Path(DAILY_SEEN_FILE).exists():
        with open(DAILY_SEEN_FILE) as f:
            return json.load(f)
    return {}


def save_daily_seen(daily_seen: dict):
    with open(DAILY_SEEN_FILE, "w") as f:
        json.dump(daily_seen, f, indent=2)
    print(f"Saved daily seen list ({len(daily_seen)} videos).")


def get_old_videos_for_daily(main_seen: dict) -> list[dict]:
    """
    When no new videos were found, pick one unseen old video from each of
    DAILY_CHANNEL_QUOTA randomly selected channels.

    Rules:
    - Only triggers when called (main.py decides when to call it)
    - Picks DAILY_CHANNEL_QUOTA channels at random (not all 11 every day)
    - Skips videos already in main_seen (already processed as new)
    - Skips videos already in daily_seen (already used for a daily Reel)
    - Picks the oldest unseen video from each selected channel's RSS feed
      (index -1) so we work backwards through the channel's history
    - If a channel has no unseen old videos left, it's skipped silently
    """
    daily_seen = load_daily_seen()
    resolved   = _resolve_all_channels()

    # Pick a random subset of channels for today
    all_channel_urls = list(resolved.keys())
    quota = min(DAILY_CHANNEL_QUOTA, len(all_channel_urls))
    selected = random.sample(all_channel_urls, quota)

    print(f"\n[Daily Reel] Picking old videos from {quota} random channels...")
    old_videos = []

    for channel_url in selected:
        channel_id   = resolved[channel_url]
        channel_name = channel_url.split("@")[-1].split("/channel/")[-1]
        print(f"  Scanning {channel_name}...")

        all_videos = get_all_videos_for_channel(channel_id, channel_name)
        if not all_videos:
            continue

        # Find the first video (oldest first) not in main_seen or daily_seen
        candidates = [
            v for v in reversed(all_videos)   # oldest first
            if v["id"] not in main_seen and v["id"] not in daily_seen
        ]

        if not candidates:
            print(f"    No unseen old videos left for {channel_name}, skipping.")
            continue

        chosen = candidates[0]
        chosen["daily_reel"] = True   # flag so main.py can label it
        print(f"    ✓ Picked old video: {chosen['title']}")
        old_videos.append(chosen)

    return old_videos, daily_seen


def load_seen_videos(path: str) -> dict:
    if Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_seen_videos(path: str, seen: dict):
    with open(path, "w") as f:
        json.dump(seen, f, indent=2)
    print(f"Saved seen list ({len(seen)} videos).")
