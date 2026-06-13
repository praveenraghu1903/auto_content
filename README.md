# auto_content — Automated YouTube Shorts Pipeline

Monitors YouTube channels for new videos, picks the best 30–59 second moments using AI, edits them into vertical 9:16 Shorts with burned-in captions, and uploads automatically.

## How it works

```
RSS Feed → yt-dlp download → Groq Whisper transcribe → Llama pick moments → FFmpeg edit → YouTube upload
```

**Two modes:**
- **New video mode** — triggered when any monitored channel uploads something new
- **Daily Reel mode** — when no new videos exist, picks old unseen videos from 4 random channels

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```
FFmpeg must also be installed on the system:
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# Mac
brew install ffmpeg
```

### 2. Set environment variables
```bash
export GROQ_API_KEY=your_groq_api_key
export YOUTUBE_CLIENT_ID=your_client_id
export YOUTUBE_CLIENT_SECRET=your_client_secret
export YOUTUBE_REFRESH_TOKEN=your_refresh_token
```

Get your Groq API key at: https://console.groq.com/keys

For YouTube OAuth credentials:
1. Go to Google Cloud Console → Create project
2. Enable YouTube Data API v3
3. Create OAuth 2.0 credentials
4. Get refresh token via OAuth flow

### 3. Run manually
```bash
python main.py
```

### 4. Schedule with cron (every 3 hours)
```bash
crontab -e
# Add:
0 */3 * * * cd /path/to/auto_content && python main.py >> logs/pipeline.log 2>&1
```

## Configuration

Edit `detector.py` to change:
- `CHANNELS` — list of YouTube channel URLs to monitor
- `DAILY_CHANNEL_QUOTA` — how many channels to process per day in daily mode (default: 4)

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point, orchestrates the pipeline |
| `detector.py` | Monitors channels via RSS, daily video picker |
| `downloader.py` | Downloads videos with yt-dlp |
| `transcriber.py` | Transcribes audio with Groq Whisper |
| `picker.py` | Picks best moments with Llama 3.3 (via Groq) |
| `editor.py` | Edits vertical Shorts with FFmpeg |
| `uploader.py` | Uploads to YouTube via Data API v3 |
| `seen_videos.json` | Tracks processed videos (auto-created) |
| `daily_seen.json` | Tracks old videos used for daily Reels (auto-created) |
| `channel_id_cache.json` | Caches resolved channel IDs (auto-created) |
