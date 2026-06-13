"""
uploader.py — uploads finished Shorts to YouTube only.
Uses YouTube Data API v3 with OAuth2 refresh token.
"""

import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials


def get_youtube_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(short: dict) -> str | None:
    """Upload a Short to YouTube. Returns video ID on success, None on failure."""
    print(f"Uploading to YouTube: {short['title']}")
    try:
        youtube = get_youtube_service()
        description = short["description"] + "\n\n" + " ".join(short["hashtags"])

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": short["title"][:100],
                    "description": description[:5000],
                    "tags": [h.lstrip("#") for h in short["hashtags"]],
                    "categoryId": "17",   # Sports
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False,
                },
            },
            media_body=MediaFileUpload(
                short["path"],
                mimetype="video/mp4",
                chunksize=10 * 1024 * 1024,
                resumable=True,
            ),
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"  Progress: {int(status.progress() * 100)}%")

        video_id = response["id"]
        print(f"  Uploaded: https://youtube.com/shorts/{video_id}")
        return video_id

    except Exception as e:
        print(f"YouTube upload failed: {e}")
        return None


def upload_all(shorts: list[dict]) -> list[dict]:
    """Upload all shorts to YouTube. Returns results list."""
    results = []
    for short in shorts:
        video_id = upload_to_youtube(short)
        if video_id:
            url = f"https://youtube.com/shorts/{video_id}"
            print(f"Done: '{short['title']}' — {url}")
            results.append({"title": short["title"], "youtube": video_id, "url": url})
        else:
            # Upload failed — mark as failed so main.py can handle retry
            print(f"Upload failed for: '{short['title']}'")
            results.append({"title": short["title"], "youtube": None, "url": None})
    return results
