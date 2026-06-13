"""
picker.py — uses Llama (via Groq) to identify the 2-3 best moments for Shorts.

Llama receives the full timestamped transcript and video title, then
returns specific clip windows with titles, descriptions and hashtags.
This is the "brain" of the pipeline — quality depends on this step.
"""

import json
import os

from groq import Groq


CLIENT = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SYSTEM_PROMPT = """You are an expert short-form video editor who specialises in 
finding the most engaging, self-contained moments from long YouTube videos to 
turn into viral Shorts (under 60 seconds).

You will receive:
- The video title
- A timestamped transcript as JSON segments

Your job is to select 2-3 clip windows that would make excellent Shorts. 
Each clip must be 30–59 seconds long.

Criteria for a great Short moment:
1. STRONG HOOK — starts with something immediately interesting (a surprising fact, 
   a bold claim, a question, a demonstration, or an emotional moment)
2. SELF-CONTAINED — makes complete sense without watching the full video
3. HIGH VALUE — teaches something, entertains, or creates emotion
4. CLEAN ENDING — ends at a natural pause, not mid-sentence

You must respond ONLY with a valid JSON array. No explanation. No markdown. 
Example format:
[
  {
    "start": 142.5,
    "end": 198.0,
    "title": "The surprising truth about X",
    "description": "Did you know that... [engaging 2-sentence description for the Short]",
    "hashtags": ["#topic1", "#topic2", "#shorts", "#viral"],
    "hook": "Why this clip works as a hook (internal note)"
  }
]"""


def segments_to_text(segments: list[dict]) -> str:
    """Convert segments to a compact readable format for Llama."""
    lines = []
    for seg in segments:
        start = f"{int(seg['start'] // 60)}:{int(seg['start'] % 60):02d}"
        end = f"{int(seg['end'] // 60)}:{int(seg['end'] % 60):02d}"
        lines.append(f"[{start}-{end}] {seg['text']}")
    return "\n".join(lines)


def pick_best_moments(segments: list[dict], video_title: str) -> list[dict] | None:
    """
    Ask Llama to pick the best 2-3 clip windows from the transcript.
    Returns list of moment dicts with start/end/title/description/hashtags.
    """
    transcript_text = segments_to_text(segments)
    total_duration = segments[-1]["end"] if segments else 0

    user_message = f"""Video title: {video_title}
Total duration: {int(total_duration // 60)}:{int(total_duration % 60):02d}

Transcript:
{transcript_text}

Pick the 2-3 best moments for YouTube Shorts / Instagram Reels. 
Remember: each clip must be 30-59 seconds. Return only JSON."""

    print("Asking Llama to pick best moments...")
    try:
        response = CLIENT.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1500,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )

        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        moments = json.loads(raw)

        # Validate and filter
        valid = []
        for m in moments:
            duration = m["end"] - m["start"]
            if 28 <= duration <= 62:
                valid.append(m)
                print(f"  Moment: '{m['title']}' ({duration:.0f}s) @ {m['start']:.0f}s")
            else:
                print(f"  Skipping moment (invalid duration {duration:.0f}s): {m['title']}")

        return valid if valid else None

    except json.JSONDecodeError as e:
        print(f"Llama returned invalid JSON: {e}")
        return None
    except Exception as e:
        print(f"Llama API error: {e}")
        return None
