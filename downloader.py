"""
downloader.py — downloads a YouTube video using yt-dlp.
Downloads best quality up to 1080p to keep file sizes manageable.
"""

import subprocess
import uuid
from pathlib import Path


OUTPUT_DIR = "/tmp/shorts_workspace"


def download_video(url: str) -> str | None:
    """
    Download video from URL.
    Uses a unique ID per download to avoid file collisions between runs.
    Returns local file path on success, None on failure.
    """
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # Unique filename per download — prevents collision if a previous run
    # left files behind or two videos are processed in sequence.
    unique_id = uuid.uuid4().hex[:8]
    output_template = f"{OUTPUT_DIR}/source_{unique_id}.%(ext)s"

    cmd = [
        "yt-dlp",
        "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--no-playlist",
        "--quiet",
        "--progress",
        url,
    ]

    print(f"Downloading: {url}")
    result = subprocess.run(cmd, capture_output=False, text=True)

    if result.returncode != 0:
        print(f"yt-dlp failed with code {result.returncode}")
        return None

    # Find the exact file this download produced
    matches = list(Path(OUTPUT_DIR).glob(f"source_{unique_id}.mp4"))
    if not matches:
        print("Downloaded file not found.")
        return None

    path = str(matches[0])
    size_mb = Path(path).stat().st_size / (1024 * 1024)
    print(f"Downloaded: {path} ({size_mb:.1f} MB)")
    return path
