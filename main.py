"""
main.py — pipeline entry point.

Two modes:
1. NEW VIDEO mode  — runs whenever a new video is detected on any channel.
2. DAILY REEL mode — runs when NO new videos exist across all channels.
                     Picks one old unseen video from DAILY_CHANNEL_QUOTA
                     random channels and makes a Reel from each.

Run once manually:     python main.py
Recommended cron:      every 3 hours
    0 */3 * * * cd /path/to/auto_content && python main.py >> logs/pipeline.log 2>&1
"""

import os
import sys
from datetime import date
from pathlib import Path

from detector import (
    get_new_videos,
    get_old_videos_for_daily,
    load_seen_videos,
    save_seen_videos,
    save_daily_seen,
)
from downloader import download_video
from transcriber import transcribe_video
from picker import pick_best_moments
from editor import create_shorts
from uploader import upload_all

SEEN_FILE = "seen_videos.json"
LOG_DIR   = Path("logs")


def check_env():
    """Warn about missing environment variables before doing any work."""
    required = ["GROQ_API_KEY", "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"⚠ WARNING: Missing environment variables: {missing}")
        print("  Transcription and/or upload will fail without these.")
    else:
        print("✓ All required environment variables are set.")


def process_video(video: dict, seen: dict, label: str = "New") -> None:
    """
    Run the full pipeline for a single video.
    Each step prints clearly so you can see exactly where it stops.
    """
    print(f"\n{'='*55}")
    print(f"[{label}] [{video['channel']}] {video['title']}")
    print(f"  URL: {video['url']}")
    print(f"{'='*55}")

    video_path = None

    try:
        # ── Step 1: Download ──────────────────────────────────────────────
        print("\n[Step 1/5] Downloading video...")
        video_path = download_video(video["url"])
        if not video_path:
            print("✗ Step 1 FAILED: Download returned None. Marking for retry.")
            seen[video["id"]] = {"title": video["title"], "channel": video["channel"],
                                  "error": "download_failed", "retry": True}
            return
        print(f"✓ Step 1 OK: {video_path}")

        # ── Step 2: Transcribe ────────────────────────────────────────────
        print("\n[Step 2/5] Transcribing audio...")
        transcript = transcribe_video(video_path)
        if not transcript:
            print("✗ Step 2 FAILED: Transcription returned None. Marking for retry.")
            seen[video["id"]] = {"title": video["title"], "channel": video["channel"],
                                  "error": "transcription_failed", "retry": True}
            return
        print(f"✓ Step 2 OK: {len(transcript)} segments transcribed.")

        # ── Step 3: Pick moments ──────────────────────────────────────────
        print("\n[Step 3/5] Picking best moments with Llama...")
        moments = pick_best_moments(transcript, video["title"])
        if not moments:
            print("✗ Step 3: No good moments found. Marking as processed (no retry).")
            seen[video["id"]] = {"title": video["title"], "channel": video["channel"],
                                  "shorts": [], "note": "no_good_moments"}
            return
        print(f"✓ Step 3 OK: {len(moments)} moment(s) selected.")
        for i, m in enumerate(moments, 1):
            print(f"   Moment {i}: '{m['title']}' — {m['start']:.0f}s to {m['end']:.0f}s ({m['end']-m['start']:.0f}s)")

        # ── Step 4: Edit ──────────────────────────────────────────────────
        print("\n[Step 4/5] Editing Shorts with FFmpeg...")
        shorts = create_shorts(video_path, moments, video["title"], segments=transcript)
        if not shorts:
            print("✗ Step 4 FAILED: Editing returned None. Marking for retry.")
            seen[video["id"]] = {"title": video["title"], "channel": video["channel"],
                                  "error": "edit_failed", "retry": True}
            return
        print(f"✓ Step 4 OK: {len(shorts)} short(s) edited.")

        # ── Step 5: Upload ────────────────────────────────────────────────
        print("\n[Step 5/5] Uploading to YouTube...")
        results   = upload_all(shorts)
        failed    = [r for r in results if r["youtube"] is None]
        succeeded = [r for r in results if r["youtube"] is not None]

        for r in succeeded:
            print(f"✓ Uploaded: '{r['title']}' → {r['url']}")
        for r in failed:
            print(f"✗ Upload FAILED: '{r['title']}'")

        seen[video["id"]] = {
            "title":           video["title"],
            "channel":         video["channel"],
            "mode":            label.lower(),
            "shorts":          results,
            "upload_failures": len(failed),
        }

        print(f"\n✓ Done: {len(succeeded)}/{len(results)} uploaded from '{video['title']}'")

    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR processing '{video['title']}': {e}")
        import traceback
        traceback.print_exc()

    finally:
        if video_path and Path(video_path).exists():
            Path(video_path).unlink(missing_ok=True)
            print(f"Cleaned up source: {video_path}")


def run():
    LOG_DIR.mkdir(exist_ok=True)
    today = date.today().isoformat()
    print(f"\n{'#'*55}")
    print(f"  Shorts Pipeline starting [{today}]")
    print(f"{'#'*55}\n")

    # ── Environment check ─────────────────────────────────────────────────
    check_env()

    # ── Load seen videos ──────────────────────────────────────────────────
    seen = load_seen_videos(SEEN_FILE)
    print(f"\n✓ Loaded seen_videos.json: {len(seen)} previously processed videos.")

    # Re-queue retryable failures
    retry_ids = [vid_id for vid_id, data in seen.items() if data.get("retry")]
    if retry_ids:
        print(f"  Re-queuing {len(retry_ids)} previously failed video(s) for retry.")
        for vid_id in retry_ids:
            del seen[vid_id]

    # ── Mode 1: New videos ────────────────────────────────────────────────
    print("\n── Checking all channels for new videos... ──")
    new_videos = get_new_videos(seen)

    if new_videos:
        print(f"\n✓ Found {len(new_videos)} new video(s). Running NEW VIDEO mode.")
        for video in new_videos:
            process_video(video, seen, label="New")
            save_seen_videos(SEEN_FILE, seen)
        print(f"\n{'#'*55}")
        print("  Pipeline complete [new video mode]")
        print(f"{'#'*55}")
        return

    # ── Mode 2: Daily Reel from old videos ────────────────────────────────
    print("\nNo new videos found on any channel.")
    print("── Switching to DAILY REEL mode... ──")

    old_videos, daily_seen = get_old_videos_for_daily(main_seen=seen)

    if not old_videos:
        print("No unseen old videos available either. Nothing to process today.")
        print(f"\n{'#'*55}")
        print("  Pipeline complete [nothing to process]")
        print(f"{'#'*55}")
        return

    print(f"✓ Found {len(old_videos)} old video(s) for daily Reels.")

    for video in old_videos:
        process_video(video, seen, label="Daily")

        daily_seen[video["id"]] = {
            "title":   video["title"],
            "channel": video["channel"],
            "date":    today,
        }
        save_daily_seen(daily_seen)
        save_seen_videos(SEEN_FILE, seen)

    print(f"\n{'#'*55}")
    print("  Pipeline complete [daily reel mode]")
    print(f"{'#'*55}")


if __name__ == "__main__":
    run()
