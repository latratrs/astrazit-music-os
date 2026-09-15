"""
apps/radio/overlay/renderer.py
Deterministic RGBA PNG renderer for Layout A (Minimal Lower Third).
Output dimensions: 385x88.
Artwork: OFF.
"""
from __future__ import annotations
import os
import io
import hashlib
from typing import Dict, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

from .sanitizer import normalize_metadata

WIDTH = 385
HEIGHT = 88
USABLE_TITLE_WIDTH = 345

# Standard cross-platform font resolution
FONT_PATHS = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
FONT_BOLD_PATHS = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

def _resolve_font(paths: list[str]) -> str:
    for p in paths:
        if os.path.isfile(p):
            return p
    return paths[0]

FONT_REGULAR_PATH = _resolve_font(FONT_PATHS)
FONT_BOLD_PATH = _resolve_font(FONT_BOLD_PATHS)

def get_font(size_px: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_REGULAR_PATH
    try:
        return ImageFont.truetype(path, size_px)
    except Exception:
        # Fallback to default
        return ImageFont.load_default()

def truncate_text_to_width(text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    """
    Truncate text using binary/bounded search so that rendered length + ellipsis fits within max_width.
    """
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0]
    if w <= max_width:
        return text

    ellipsis = "..."
    ell_bbox = font.getbbox(ellipsis)
    ell_w = ell_bbox[2] - ell_bbox[0]
    available_w = max_width - ell_w
    if available_w <= 0:
        return ellipsis

    # Binary search optimal length
    low = 1
    high = len(text)
    best_fit = ""
    while low <= high:
        mid = (low + high) // 2
        sub = text[:mid]
        sub_bbox = font.getbbox(sub)
        sub_w = sub_bbox[2] - sub_bbox[0]
        if sub_w <= available_w:
            best_fit = sub
            low = mid + 1
        else:
            high = mid - 1

    return best_fit.rstrip() + ellipsis

def render_overlay_image(metadata: Dict[str, str], opacity: float = 1.0) -> Image.Image:
    """
    Render 385x88 RGBA image for Layout A.
    opacity: 0.0 (completely transparent) to 1.0 (full design opacity).
    """
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if opacity <= 0.0:
        return img

    draw = ImageDraw.Draw(img)

    # Base background alpha
    bg_alpha = int(175 * opacity)
    outline_alpha = int(35 * opacity)
    accent_alpha = int(230 * opacity)

    # 1. Dark translucent glass container with rounded corners
    draw.rounded_rectangle(
        [0, 0, WIDTH - 1, HEIGHT - 1],
        radius=8,
        fill=(10, 12, 18, bg_alpha),
        outline=(255, 255, 255, outline_alpha),
        width=1,
    )

    # 2. Left glowing vertical neon stripe
    draw.line(
        [(10, 12), (10, HEIGHT - 13)],
        fill=(185, 140, 255, accent_alpha),
        width=3,
    )

    # 3. Typography
    font_header = get_font(11, bold=True)
    font_title = get_font(18, bold=True)
    font_artist = get_font(13, bold=False)

    text_x = 22

    # Program / Category Header
    program_label = metadata.get("program", "ASTRAZIT RADIO").upper()
    header_str = f"NOW PLAYING  •  {program_label}"
    header_str = truncate_text_to_width(header_str, font_header, USABLE_TITLE_WIDTH)
    draw.text(
        (text_x, 12),
        header_str,
        font=font_header,
        fill=(195, 180, 235, int(240 * opacity)),
    )

    # Track Title
    raw_title = metadata.get("title", "ASTRAZIT RADIO")
    title_str = truncate_text_to_width(raw_title, font_title, USABLE_TITLE_WIDTH)
    draw.text(
        (text_x, 31),
        title_str,
        font=font_title,
        fill=(255, 255, 255, int(255 * opacity)),
    )

    # Artist
    artist_str = metadata.get("artist", "")
    if artist_str:
        artist_str = truncate_text_to_width(artist_str, font_artist, USABLE_TITLE_WIDTH)
        draw.text(
            (text_x, 57),
            artist_str,
            font=font_artist,
            fill=(205, 210, 220, int(220 * opacity)),
        )

    return img

def render_overlay_bytes(metadata_dict: dict, opacity: float = 1.0) -> bytes:
    """
    Render overlay and return deterministic PNG bytes.
    """
    normalized = normalize_metadata(metadata_dict)
    img = render_overlay_image(normalized, opacity=opacity)
    buf = io.BytesIO()
    # Save PNG deterministically without variable timestamps or headers
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
