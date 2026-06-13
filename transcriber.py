"""
transcriber.py — transcribes video audio using Groq's hosted Whisper API.
Returns a list of segments: [{start, end, text}, ...]

For large audio files (>24MB), splits into chunks and merges results.
Groq's free tier: ~14,400 minutes/day.
"""

import os
import subprocess
from pathlib import Path

from groq import Groq

WORKSPACE    = "/tmp/shorts_workspace"
AUDIO_PATH   = f"{WORKSPACE}/audio.mp3"
MAX_FILE_MB  = 22   # Stay safely under Groq's 25MB limit
CHUNK_SECS   = 600  # 10-minute chunks for large files


def extract_audio(video_path: str, output_path: str = AUDIO_PATH) -> str | None:
    """Extract audio from video as compressed mono MP3."""
    Path(WORKSPACE).mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-ar", "16000",
        "-ac", "1",
        "-b:a", "64k",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Audio extraction failed: {result.stderr[-300:]}")
        return None
    size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    print(f"Audio extracted: {size_mb:.1f} MB")
    return output_path


def split_audio(audio_path: str) -> list[tuple[str, float]]:
    """
    Split large audio file into chunks.
    Returns list of (chunk_path, start_offset_seconds).
    """
    # Get total duration
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True
    )
    try:
        total_duration = float(result.stdout.strip())
    except Exception:
        total_duration = 0

    if total_duration == 0:
        return [(audio_path, 0.0)]

    chunks = []
    start = 0.0
    i = 0
    while start < total_duration:
        chunk_path = f"{WORKSPACE}/audio_chunk_{i}.mp3"
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-ss", str(start),
            "-t", str(CHUNK_SECS),
            "-c", "copy",
            chunk_path,
        ]
        subprocess.run(cmd, capture_output=True)
        if Path(chunk_path).exists():
            chunks.append((chunk_path, start))
        start += CHUNK_SECS
        i += 1

    print(f"Split into {len(chunks)} chunks.")
    return chunks


def transcribe_audio_file(client: Groq, audio_path: str, offset: float = 0.0) -> list[dict]:
    """Transcribe a single audio file and return segments with adjusted timestamps."""
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = []
    for seg in response.segments:
        if isinstance(seg, dict):
            start = seg.get('start', 0)
            end   = seg.get('end', 0)
            text  = seg.get('text', '').strip()
        else:
            start = seg.start
            end   = seg.end
            text  = seg.text.strip()

        segments.append({
            "start": round(start + offset, 2),
            "end":   round(end + offset, 2),
            "text":  text,
        })
    return segments


def transcribe_video(video_path: str) -> list[dict] | None:
    """
    Transcribe video and return timestamped segments.
    Automatically splits large audio files into chunks.
    Returns: [{"start": 12.4, "end": 18.1, "text": "..."}, ...]
    """
    audio_path = extract_audio(video_path)
    if not audio_path:
        return None

    size_mb = Path(audio_path).stat().st_size / (1024 * 1024)
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    all_segments = []

    print("Transcribing with Groq Whisper...")

    if size_mb <= MAX_FILE_MB:
        # Small file — transcribe directly
        try:
            all_segments = transcribe_audio_file(client, audio_path, offset=0.0)
        except Exception as e:
            print(f"Transcription failed: {e}")
            return None
    else:
        # Large file — split into chunks and transcribe each
        print(f"File is {size_mb:.1f} MB — splitting into {CHUNK_SECS}s chunks...")
        chunks = split_audio(audio_path)
        for chunk_path, offset in chunks:
            chunk_mb = Path(chunk_path).stat().st_size / (1024 * 1024)
            print(f"  Transcribing chunk at {offset:.0f}s ({chunk_mb:.1f} MB)...")
            try:
                segs = transcribe_audio_file(client, chunk_path, offset=offset)
                all_segments.extend(segs)
                print(f"  Got {len(segs)} segments.")
            except Exception as e:
                print(f"  Chunk at {offset:.0f}s failed: {e} — skipping.")
            finally:
                Path(chunk_path).unlink(missing_ok=True)

    if not all_segments:
        print("No segments returned from transcription.")
        return None

    total_duration = all_segments[-1]["end"] if all_segments else 0
    print(f"Transcribed {len(all_segments)} segments, {total_duration:.0f}s total.")
    return all_segments
