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
- A timestamped transcript as lines like [M:SS-M:SS] text

Your job is to select 2-3 clip windows that would make excellent Shorts.

STRICT RULES — violating these will break the pipeline:
1. Each clip MUST be between 30 and 59 seconds long (end - start >= 30 AND end - start <= 59)
2. start and end MUST be real timestamps that exist in the transcript
3. start MUST be less than end
4. Do NOT invent timestamps — only use times that appear in the transcript
5. If the video is too short or has no good moments, return an empty array []

Criteria for a great Short moment:
- STRONG HOOK — starts with something immediately interesting
- SELF-CONTAINED — makes complete sense without watching the full video
- HIGH VALUE — teaches something, entertains, or creates emotion

You must respond ONLY with a valid JSON array. No explanation. No markdown.
Example:
[
  {
    "start": 142.5,
    "end": 181.0,
    "title": "The surprising truth about X",
    "description": "Short engaging description for YouTube.",
    "hashtags": ["#topic1", "#shorts", "#viral"]
  }
]

If no moment meets the 30-59 second rule, return: []"""


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
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                if part.startswith("json"):
                    raw = part[4:].strip()
                    break
                elif "[" in part:
                    raw = part.strip()
                    break

        # Extract JSON array even if surrounded by text
        start_idx = raw.find("[")
        end_idx   = raw.rfind("]")
        if start_idx != -1 and end_idx != -1:
            raw = raw[start_idx:end_idx + 1]

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
