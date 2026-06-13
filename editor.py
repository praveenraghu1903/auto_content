"""
editor.py — creates vertical 9:16 Shorts from the source video using FFmpeg.

For each moment:
1. Trims to the clip window
2. Crops/scales to 1080x1920 (9:16)
3. Burns in subtitle captions from the transcript
4. Adds a subtle top/bottom gradient overlay for text readability
"""

import os
import subprocess
import uuid
from pathlib import Path


OUTPUT_DIR = "/tmp/shorts_workspace/shorts"
WORKSPACE = "/tmp/shorts_workspace"


def build_subtitle_file(segments: list[dict], start: float, end: float, clip_uid: str) -> str:
    """
    Build an SRT subtitle file for the clip window.
    Timestamps are relative to clip start.
    Uses a unique clip_uid to avoid filename collisions between
    clips that start at the same second.
    """
    srt_path = f"{WORKSPACE}/captions_{clip_uid}.srt"
    clip_segments = [s for s in segments if s["end"] > start and s["start"] < end]

    lines = []
    for i, seg in enumerate(clip_segments, 1):
        rel_start = max(0, seg["start"] - start)
        rel_end = min(end - start, seg["end"] - start)

        def fmt(t):
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ms = int((t % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        lines.append(str(i))
        lines.append(f"{fmt(rel_start)} --> {fmt(rel_end)}")
        lines.append(seg["text"])
        lines.append("")

    with open(srt_path, "w") as f:
        f.write("\n".join(lines))

    return srt_path


def create_short(
    video_path: str,
    moment: dict,
    output_path: str,
    segments: list[dict],
    clip_uid: str,
) -> bool:
    """
    Create a single 9:16 Short from a video moment.
    Uses smart crop: centers the crop window horizontally.
    clip_uid is passed through to subtitle file naming.
    """
    start = moment["start"]
    duration = moment["end"] - moment["start"]
    srt_path = build_subtitle_file(segments, moment["start"], moment["end"], clip_uid)

    # FFmpeg filter chain:
    # 1. scale to height 1920 keeping aspect
    # 2. crop width to 1080 from center
    # 3. burn subtitles
    subtitle_style = (
        "FontName=Arial,"
        "FontSize=18,"
        "PrimaryColour=&HFFFFFF,"
        "OutlineColour=&H000000,"
        "Outline=2,"
        "Bold=1,"
        "Alignment=2,"           # bottom center
        "MarginV=80"
    )

    vf = (
        f"scale=-2:1920,"
        f"crop=1080:1920:(iw-1080)/2:0,"
        f"subtitles={srt_path}:force_style='{subtitle_style}'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FFmpeg error: {result.stderr[-500:]}")
        return False

    size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    print(f"Created short: {output_path} ({size_mb:.1f} MB)")
    return True


def create_shorts(
    video_path: str,
    moments: list[dict],
    video_title: str,
    segments: list[dict] = None,
) -> list[dict] | None:
    """
    Create all Shorts for the given moments.
    Returns list of dicts with path + metadata.
    """
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    shorts = []

    for i, moment in enumerate(moments, 1):
        # Unique ID per clip — prevents subtitle file collisions even if
        # two moments happen to start at the same second.
        clip_uid = uuid.uuid4().hex[:8]

        safe_title = "".join(c for c in moment["title"] if c.isalnum() or c in " _-")[:40]
        output_path = f"{OUTPUT_DIR}/short_{clip_uid}_{safe_title.replace(' ', '_')}.mp4"

        print(f"Editing Short {i}/{len(moments)}: {moment['title']}")
        success = create_short(video_path, moment, output_path, segments or [], clip_uid)

        if success:
            shorts.append({
                "path": output_path,
                "title": moment["title"],
                "description": moment.get("description", ""),
                "hashtags": moment.get("hashtags", ["#shorts"]),
            })
        else:
            print(f"Failed to create short {i}, skipping.")

    return shorts if shorts else None
