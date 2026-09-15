"""
apps/radio/overlay/sanitizer.py
Deterministic sanitization and normalization for Now Playing metadata.
Treats all metadata as untrusted display data.
"""
from __future__ import annotations
import unicodedata
from typing import Any, Dict, Optional

# Bounds to prevent excessive memory or render issues
MAX_STRING_LEN = 200
MAX_TITLE_LEN = 300

def sanitize_string(val: Any, max_len: int = MAX_STRING_LEN, fallback: str = "") -> str:
    """
    Sanitize an untrusted input into safe, single-line normalized display text.
    - Strips or replaces control chars and embedded newlines with safe spaces.
    - Normalizes Unicode (NFC).
    - Collapses whitespace.
    - Limits maximum length.
    """
    if val is None or isinstance(val, bool):
        return fallback
    if not isinstance(val, str):
        # Numeric conversions (float/int)
        if isinstance(val, (int, float)):
            val = str(val)
        else:
            return fallback

    # Normalize unicode to NFC
    val = unicodedata.normalize("NFC", val)

    # Filter control characters, replacing C0/C1 control codes with space
    cleaned_chars = []
    for ch in val:
        cat = unicodedata.category(ch)
        if cat.startswith("C"):
            cleaned_chars.append(" ")
        else:
            cleaned_chars.append(ch)
    
    cleaned = "".join(cleaned_chars)

    # Collapse multiple consecutive whitespace
    parts = cleaned.split()
    result = " ".join(parts)

    if not result:
        return fallback

    lower_res = result.lower()
    if lower_res in ("none", "null", "unknown"):
        return fallback
    if "traceback (most recent call last)" in lower_res or "exception:" in lower_res:
        return fallback
    if any(lower_res.endswith(ext) for ext in (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".mp4", ".opus")):
        return fallback

    if len(result) > max_len:
        result = result[:max_len].rstrip()

    return result

def normalize_metadata(data: Any) -> Dict[str, str]:
    """
    Normalize metadata payload. Enforces frozen Layout A rules and fallbacks:
    - If title is missing/empty/invalid -> fallback to "ASTRAZIT RADIO"
    - If program is missing/empty -> fallback to "ASTRAZIT RADIO"
    - song_id is consumed as opaque string
    - artwork_path is ignored for V1 rendering
    """
    if not isinstance(data, dict):
        return {
            "song_id": "",
            "title": "ASTRAZIT RADIO",
            "artist": "",
            "program": "ASTRAZIT RADIO",
            "visual_profile": "default",
        }

    # Opaque song_id
    raw_song_id = data.get("song_id")
    song_id = sanitize_string(raw_song_id, max_len=64, fallback="")

    # Title
    raw_title = data.get("title")
    title = sanitize_string(raw_title, max_len=MAX_TITLE_LEN, fallback="ASTRAZIT RADIO")

    # Artist
    raw_artist = data.get("artist")
    artist = sanitize_string(raw_artist, max_len=MAX_STRING_LEN, fallback="")

    # Program
    raw_program = data.get("program")
    program = sanitize_string(raw_program, max_len=MAX_STRING_LEN, fallback="ASTRAZIT RADIO")

    # Visual profile
    raw_profile = data.get("visual_profile")
    visual_profile = sanitize_string(raw_profile, max_len=64, fallback="default")

    return {
        "song_id": song_id,
        "title": title,
        "artist": artist,
        "program": program,
        "visual_profile": visual_profile,
    }
