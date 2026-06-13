"""
transcriber.py — transcribes video audio using Groq's hosted Whisper API.
Returns a list of segments: [{start, end, text}, ...]
Groq's free tier is very generous (~14,400 minutes/day).
"""

import os
import subprocess
from pathlib import Path

from groq import Groq


AUDIO_PATH = "/tmp/shorts_workspace/audio.mp3"
MAX_FILE_MB = 24  # Groq limit is 25 MB


def extract_audio(video_path: str) -> str | None:
    """Extract audio from video as compressed MP3."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",                    # no video
        "-ar", "16000",           # 16kHz — enough for speech
        "-ac", "1",               # mono
        "-b:a", "64k",            # low bitrate keeps file small
        AUDIO_PATH,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Audio extraction failed: {result.stderr}")
        return None
    size_mb = Path(AUDIO_PATH).stat().st_size / (1024 * 1024)
    print(f"Audio extracted: {size_mb:.1f} MB")
    return AUDIO_PATH


def transcribe_video(video_path: str) -> list[dict] | None:
    """
    Transcribe video and return timestamped segments.
    Returns: [{"start": 12.4, "end": 18.1, "text": "..."}, ...]
    """
    audio_path = extract_audio(video_path)
    if not audio_path:
        return None

    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    print("Transcribing with Groq Whisper...")
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = [
        {
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        }
        for seg in response.segments
    ]

    total_duration = segments[-1]["end"] if segments else 0
    print(f"Transcribed {len(segments)} segments, {total_duration:.0f}s total.")
    return segments
