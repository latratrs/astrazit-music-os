"""
Unit tests for AstraZit Radio Now Playing overlay.
Governed by VISUAL-003 and V1 overlay specification.
Uses standard library unittest.
"""
import os
import io
import time
import hashlib
import unittest
import tempfile
import shutil
from PIL import Image

from apps.radio.overlay.sanitizer import sanitize_string, normalize_metadata, MAX_STRING_LEN, MAX_TITLE_LEN
from apps.radio.overlay.renderer import (
    render_overlay_image,
    render_overlay_bytes,
    truncate_text_to_width,
    get_font,
    WIDTH,
    HEIGHT,
    USABLE_TITLE_WIDTH,
)
from apps.radio.overlay.atomic_writer import atomic_write_png, validate_png_bytes
from apps.radio.overlay.controller import OverlayController

class TestOverlayRenderer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sanitizer_normal_string(self):
        self.assertEqual(sanitize_string("Hello World"), "Hello World")

    def test_sanitizer_control_chars_and_newlines(self):
        # Specific conceptual test from VISUAL-003R1 specification:
        # "Track\tTitle\nwith\x00control\rchars" -> "Track Title with control chars"
        dirty = "Track\tTitle\nwith\x00control\rchars"
        cleaned = sanitize_string(dirty)
        self.assertEqual(cleaned, "Track Title with control chars")

    def test_sanitizer_pathological_whitespace(self):
        dirty = "  Track   \t \n\r   Title   with    extra    spaces   "
        cleaned = sanitize_string(dirty)
        self.assertEqual(cleaned, "Track Title with extra spaces")

    def test_sanitizer_non_whitespace_control_characters(self):
        # Non-whitespace control chars (\x00, \x1b, \x07, \x7f) must not concatenate adjacent words
        dirty = "Track\x00Name\x07With\x1bEscape\x7fDel"
        cleaned = sanitize_string(dirty)
        self.assertEqual(cleaned, "Track Name With Escape Del")

    def test_sanitizer_adversarial_injection(self):
        # Hostile shell and FFmpeg characters must be treated purely as display text
        hostile = "Title; rm -rf /; $(whoami); `cat /etc/passwd` | & < > \" ' $PATH %APPDATA% [drawtext=1]"
        cleaned = sanitize_string(hostile)
        self.assertIn("; rm -rf /;", cleaned)
        self.assertIn("$(whoami)", cleaned)
        self.assertIn("[drawtext=1]", cleaned)

    def test_sanitizer_sentinels_and_forbidden_strings(self):
        # Must never display null, None, unknown, exception text, stack trace, or raw audio filenames
        self.assertEqual(sanitize_string("null", fallback="FALLBACK"), "FALLBACK")
        self.assertEqual(sanitize_string("NULL", fallback="FALLBACK"), "FALLBACK")
        self.assertEqual(sanitize_string("None", fallback="FALLBACK"), "FALLBACK")
        self.assertEqual(sanitize_string("none", fallback="FALLBACK"), "FALLBACK")
        self.assertEqual(sanitize_string("unknown", fallback="FALLBACK"), "FALLBACK")
        self.assertEqual(sanitize_string("UNKNOWN", fallback="FALLBACK"), "FALLBACK")
        self.assertEqual(sanitize_string("Traceback (most recent call last):\n  File 'x.py'", fallback="FB"), "FB")
        self.assertEqual(sanitize_string("Exception: failed to play", fallback="FB"), "FB")
        self.assertEqual(sanitize_string("track_01.mp3", fallback="FB"), "FB")
        self.assertEqual(sanitize_string("audio.wav", fallback="FB"), "FB")
        self.assertEqual(sanitize_string("song.flac", fallback="FB"), "FB")

    def test_sanitizer_unicode(self):
        unicode_text = "Волна • 電子音楽 • Café del Mar • 🎶"
        cleaned = sanitize_string(unicode_text)
        self.assertIn("Волна", cleaned)
        self.assertIn("電子音楽", cleaned)
        self.assertIn("Café del Mar", cleaned)
        self.assertIn("🎶", cleaned)

    def test_normalize_metadata_missing_title(self):
        res = normalize_metadata({"artist": "AstraZit"})
        self.assertEqual(res["title"], "ASTRAZIT RADIO")
        self.assertEqual(res["artist"], "AstraZit")
        self.assertEqual(res["program"], "ASTRAZIT RADIO")

    def test_normalize_metadata_missing_artist(self):
        res = normalize_metadata({"title": "Solar Wind"})
        self.assertEqual(res["title"], "Solar Wind")
        self.assertEqual(res["artist"], "")
        self.assertEqual(res["program"], "ASTRAZIT RADIO")

    def test_normalize_metadata_missing_program(self):
        res = normalize_metadata({"title": "Solar Wind", "artist": "AstraZit"})
        self.assertEqual(res["program"], "ASTRAZIT RADIO")

    def test_normalize_metadata_empty_and_whitespace(self):
        res = normalize_metadata({"title": "", "artist": "   \t \n  ", "program": ""})
        self.assertEqual(res["title"], "ASTRAZIT RADIO")
        self.assertEqual(res["artist"], "")
        self.assertEqual(res["program"], "ASTRAZIT RADIO")

    def test_normalize_metadata_wrong_types(self):
        # Test null, boolean, integer/float, object, array
        res = normalize_metadata({
            "song_id": 12345,
            "title": ["invalid", "list"],
            "artist": {"dict": "invalid"},
            "program": False,
        })
        self.assertEqual(res["song_id"], "12345")
        self.assertEqual(res["title"], "ASTRAZIT RADIO")
        self.assertEqual(res["artist"], "")
        self.assertEqual(res["program"], "ASTRAZIT RADIO")

        res_none = normalize_metadata({
            "song_id": None,
            "title": None,
            "artist": None,
            "program": None,
        })
        self.assertEqual(res_none["song_id"], "")
        self.assertEqual(res_none["title"], "ASTRAZIT RADIO")
        self.assertEqual(res_none["artist"], "")
        self.assertEqual(res_none["program"], "ASTRAZIT RADIO")

    def test_render_dimensions(self):
        meta = {"song_id": "AST-001", "title": "Test Title", "artist": "AstraZit"}
        img = render_overlay_image(normalize_metadata(meta))
        self.assertEqual(img.size, (WIDTH, HEIGHT))
        self.assertEqual(img.mode, "RGBA")

    def test_title_truncation_measurement_based(self):
        font = get_font(18, bold=True)

        # 1. Short title
        short_title = "Short Title"
        res_short = truncate_text_to_width(short_title, font, USABLE_TITLE_WIDTH)
        self.assertEqual(res_short, short_title)
        bbox = font.getbbox(res_short)
        self.assertLessEqual(bbox[2] - bbox[0], USABLE_TITLE_WIDTH)

        # 2. 64-character title
        title_64 = "A" * 64
        res_64 = truncate_text_to_width(title_64, font, USABLE_TITLE_WIDTH)
        self.assertTrue(res_64.endswith("..."))
        bbox_64 = font.getbbox(res_64)
        self.assertLessEqual(bbox_64[2] - bbox_64[0], USABLE_TITLE_WIDTH)

        # 3. 200-character title
        title_200 = "Extended Title With Multiple Words And Numbers " * 4
        self.assertGreaterEqual(len(title_200), 180)
        res_200 = truncate_text_to_width(title_200, font, USABLE_TITLE_WIDTH)
        self.assertTrue(res_200.endswith("..."))
        bbox_200 = font.getbbox(res_200)
        self.assertLessEqual(bbox_200[2] - bbox_200[0], USABLE_TITLE_WIDTH)

        # 4. 1000+ character title
        title_1000 = "Massive Extremely Long Song Title " * 35
        self.assertGreaterEqual(len(title_1000), 1000)
        res_1000 = truncate_text_to_width(title_1000, font, USABLE_TITLE_WIDTH)
        self.assertTrue(res_1000.endswith("..."))
        bbox_1000 = font.getbbox(res_1000)
        self.assertLessEqual(bbox_1000[2] - bbox_1000[0], USABLE_TITLE_WIDTH)

        # 5. Unicode title
        title_unicode = "Электронная музыка и космические волны с очень длинным названием для проверки усечения"
        res_uni = truncate_text_to_width(title_unicode, font, USABLE_TITLE_WIDTH)
        self.assertTrue(res_uni.endswith("..."))
        bbox_uni = font.getbbox(res_uni)
        self.assertLessEqual(bbox_uni[2] - bbox_uni[0], USABLE_TITLE_WIDTH)

    def test_unicode_rendering_representative_strings(self):
        # Test accented Latin, Cyrillic, emoji, and CJK
        meta_accented = {"title": "Café del Mar • Björk • Sigur Rós", "artist": "José González"}
        meta_cyrillic = {"title": "Волна • Электроника • Спутник", "artist": "Кино"}
        meta_emoji = {"title": "Late Night Waves 🎶 🌌", "artist": "AstraZit 📻"}
        meta_cjk = {"title": "電子音楽 • 夜の散歩", "artist": "久石 譲"}

        for meta in [meta_accented, meta_cyrillic, meta_emoji, meta_cjk]:
            b = render_overlay_bytes(meta)
            self.assertTrue(validate_png_bytes(b, (WIDTH, HEIGHT)))

    def test_atomic_writer_and_last_known_good(self):
        target_png = os.path.join(self.temp_dir, "overlay.png")
        meta = {"song_id": "AST-001", "title": "Title 1", "artist": "Artist 1"}
        b1 = render_overlay_bytes(meta)

        # 1. Successful initial write
        self.assertTrue(atomic_write_png(target_png, b1))
        self.assertTrue(os.path.exists(target_png))
        with open(target_png, "rb") as f:
            read_b1 = f.read()
        self.assertEqual(read_b1, b1)

        # 2. Corrupted candidate write should fail and preserve last known good
        corrupted_bytes = b"NOT_A_PNG_HEADER"
        self.assertFalse(atomic_write_png(target_png, corrupted_bytes))
        with open(target_png, "rb") as f:
            still_b1 = f.read()
        self.assertEqual(still_b1, b1)

        # 3. Wrong dimensions should fail and preserve last known good
        img_wrong_size = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        buf = io.BytesIO()
        img_wrong_size.save(buf, format="PNG")
        wrong_size_bytes = buf.getvalue()
        self.assertFalse(atomic_write_png(target_png, wrong_size_bytes))
        with open(target_png, "rb") as f:
            still_b1_after_wrong_size = f.read()
        self.assertEqual(still_b1_after_wrong_size, b1)

    def test_rendering_determinism(self):
        meta = {
            "song_id": "AST-000001",
            "title": "Walk in The Rain After Party",
            "artist": "AstraZit",
            "program": "LATE NIGHT ELECTRONIC MUSIC",
        }
        b1 = render_overlay_bytes(meta)
        b2 = render_overlay_bytes(meta)

        # Byte determinism
        self.assertEqual(b1, b2)
        h1 = hashlib.sha256(b1).hexdigest()
        h2 = hashlib.sha256(b2).hexdigest()
        self.assertEqual(h1, h2)

        # Pixel determinism
        img1 = Image.open(io.BytesIO(b1))
        img2 = Image.open(io.BytesIO(b2))
        self.assertEqual(img1.tobytes(), img2.tobytes())

    def test_rapid_updates_coalescing(self):
        target_png = os.path.join(self.temp_dir, "overlay.png")
        controller = OverlayController(target_png, fade_duration=0.05, steps_per_sec=20)
        controller.start()

        # Submit rapid burst of 10 updates
        for i in range(10):
            controller.submit_metadata({
                "song_id": f"AST-{i}",
                "title": f"Rapid Title {i}",
                "artist": "AstraZit",
            })

        # Wait for coalescing worker to process
        time.sleep(0.5)
        controller.stop()

        self.assertTrue(os.path.exists(target_png))
        self.assertEqual(controller.current_metadata["title"], "Rapid Title 9")

if __name__ == "__main__":
    unittest.main()
