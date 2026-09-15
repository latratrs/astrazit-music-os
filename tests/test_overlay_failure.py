"""
tests/test_overlay_failure.py
Failure isolation, atomic_writer regression, and error resilience unit tests
for AstraZit Radio Now Playing overlay pipeline.
Governed by VISUAL-003R4.
"""
import os
import io
import time
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

from apps.radio.overlay.sanitizer import (
    sanitize_string,
    normalize_metadata,
)
from apps.radio.overlay.renderer import (
    render_overlay_bytes,
    render_overlay_image,
    WIDTH,
    HEIGHT,
)
from apps.radio.overlay.atomic_writer import (
    atomic_write_png,
    validate_png_bytes,
)
from apps.radio.overlay.controller import (
    OverlayController,
    TransitionState,
)


class TestAtomicWriterRegression(unittest.TestCase):
    """
    Dedicated regression test suite for apps/radio/overlay/atomic_writer.py.
    Audits sync_to_disk parameter and atomic guarantees.
    """
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.target_path = os.path.join(self.temp_dir, "test_overlay.png")
        self.valid_meta = {
            "song_id": "AST-000001",
            "title": "Solar Flare",
            "artist": "AstraZit",
            "program": "TEST",
        }
        self.valid_png = render_overlay_bytes(self.valid_meta)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_atomic_contract_preserved(self):
        """1. Default behavior (sync_to_disk=True) preserves R1 atomic contract."""
        success = atomic_write_png(self.target_path, self.valid_png)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(self.target_path))
        with open(self.target_path, "rb") as f:
            content = f.read()
        self.assertEqual(content, self.valid_png)

    def test_temporary_file_created_in_same_directory(self):
        """2. Temporary file is created on the same directory/filesystem to allow atomic os.replace."""
        created_temp_paths = []
        real_mkstemp = tempfile.mkstemp

        def mock_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            created_temp_paths.append(path)
            return fd, path

        with patch("tempfile.mkstemp", side_effect=mock_mkstemp):
            success = atomic_write_png(self.target_path, self.valid_png)
            self.assertTrue(success)

        self.assertEqual(len(created_temp_paths), 1)
        temp_dir_used = os.path.dirname(os.path.abspath(created_temp_paths[0]))
        target_dir = os.path.dirname(os.path.abspath(self.target_path))
        self.assertEqual(temp_dir_used, target_dir)

    def test_candidate_validated_before_replacement(self):
        """3. Candidate data is validated before file creation and after write."""
        with patch("tempfile.mkstemp") as mock_mkstemp:
            success = atomic_write_png(self.target_path, b"NOT_PNG_BYTES")
            self.assertFalse(success)
            mock_mkstemp.assert_not_called()

    def test_os_replace_is_commit_point(self):
        """4. os.replace remains the sole commit point."""
        replace_called = []
        real_replace = os.replace

        def mock_replace(src, dst):
            replace_called.append((src, dst))
            real_replace(src, dst)

        with patch("os.replace", side_effect=mock_replace):
            success = atomic_write_png(self.target_path, self.valid_png)
            self.assertTrue(success)

        self.assertEqual(len(replace_called), 1)
        self.assertEqual(replace_called[0][1], self.target_path)

    def test_failed_candidate_cannot_replace_last_known_good(self):
        """5. Failed candidate cannot replace last-known-good overlay."""
        self.assertTrue(atomic_write_png(self.target_path, self.valid_png))
        with open(self.target_path, "rb") as f:
            lkg_content = f.read()

        corrupted = b"\x89PNG\r\n\x1a\ncorrupted_data_that_fails_parsing"
        self.assertFalse(atomic_write_png(self.target_path, corrupted))

        with open(self.target_path, "rb") as f:
            after_fail = f.read()
        self.assertEqual(after_fail, lkg_content)

    def test_temporary_files_cleaned_on_failure(self):
        """6. Temporary files are cleaned up when writing or validation fails."""
        temp_files_seen = []
        real_mkstemp = tempfile.mkstemp

        def mock_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            temp_files_seen.append(path)
            return fd, path

        with patch("apps.radio.overlay.atomic_writer.validate_png_bytes") as mock_val:
            mock_val.side_effect = [True, False]
            with patch("tempfile.mkstemp", side_effect=mock_mkstemp):
                res = atomic_write_png(self.target_path, self.valid_png)
                self.assertFalse(res)

        for p in temp_files_seen:
            self.assertFalse(os.path.exists(p), f"Temporary file {p} was not cleaned up")

    def test_sync_to_disk_durability_semantics(self):
        """7. sync_to_disk=True issues os.fsync; sync_to_disk=False skips os.fsync."""
        fsync_calls = []
        real_fsync = os.fsync

        def mock_fsync(fd):
            fsync_calls.append(fd)
            real_fsync(fd)

        with patch("os.fsync", side_effect=mock_fsync):
            atomic_write_png(self.target_path, self.valid_png, sync_to_disk=True)
            self.assertEqual(len(fsync_calls), 1)

            atomic_write_png(self.target_path, self.valid_png, sync_to_disk=False)
            self.assertEqual(len(fsync_calls), 1)


class TestFailureModelAndResilience(unittest.TestCase):
    """
    Failure model tests covering the 10 required failure modes from VISUAL-003R4:
    1. malformed JSON
    2. missing metadata source/file
    3. wrong metadata types
    4. invalid/empty metadata
    5. renderer exception
    6. corrupted candidate PNG
    7. invalid candidate dimensions/mode
    8. atomic candidate write/validation failure
    9. update arriving while previous transition is active
    10. invalid update arriving while a valid pending state exists
    """
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.target_png = os.path.join(self.temp_dir, "controller_overlay.png")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _wait_for_visible(self, ctrl, timeout=3.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if ctrl.state == TransitionState.VISIBLE and ctrl.pending_metadata is None:
                return True
            time.sleep(0.01)
        return False

    def test_01_malformed_json_resilience(self):
        """1. Malformed JSON strings or unparseable payloads do not crash the controller."""
        ctrl = OverlayController(target_png_path=self.target_png, fade_duration=0.05, steps_per_sec=20)
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Initial Song", "artist": "AstraZit"})
            self.assertTrue(self._wait_for_visible(ctrl))

            bad_inputs = [
                "{malformed json without closing brace",
                '{"title": "Unclosed string, "artist": "Test"}',
                "null",
                "None",
                b"\x80\x81\xfe\xff binary garbage",
            ]
            for bad in bad_inputs:
                accepted = ctrl.submit_metadata(bad)
                self.assertTrue(ctrl._running)

            self.assertTrue(ctrl._running)
            self.assertIsNotNone(ctrl.last_known_good_metadata)
        finally:
            ctrl.stop()

    def test_02_missing_metadata_file_or_source(self):
        """2. Missing metadata file / None / empty structure defaults to safe station identifier."""
        res_none = normalize_metadata(None)
        self.assertEqual(res_none["title"], "ASTRAZIT RADIO")
        self.assertEqual(res_none["program"], "ASTRAZIT RADIO")
        self.assertEqual(res_none["artist"], "")

        missing_file_path = os.path.join(self.temp_dir, "nonexistent_metadata.json")
        loaded_data = None
        if os.path.exists(missing_file_path):
            with open(missing_file_path) as f:
                loaded_data = json.load(f)
        res_missing = normalize_metadata(loaded_data)
        self.assertEqual(res_missing["title"], "ASTRAZIT RADIO")

    def test_03_wrong_metadata_types(self):
        """3. Wrong metadata types (arrays, integers, booleans, objects) sanitized to safe values."""
        weird_payload = {
            "title": [1, 2, 3, {"nested": "dict"}],
            "artist": object(),
            "program": 9999.5,
            "song_id": False,
        }
        res = normalize_metadata(weird_payload)
        self.assertEqual(res["title"], "ASTRAZIT RADIO")
        self.assertEqual(res["artist"], "")
        self.assertEqual(res["program"], "9999.5")
        self.assertEqual(res["song_id"], "")

    def test_04_invalid_and_empty_metadata(self):
        """4. Invalid/empty metadata never displays sentinels (null, None, unknown, stack traces)."""
        sentinels = [
            {"title": "null", "artist": "None", "program": "unknown"},
            {"title": "NULL", "artist": "NONE", "program": "UNKNOWN"},
            {"title": "Traceback (most recent call last):\n  File 'x.py', line 1", "artist": "exception: error"},
            {"title": "track_12.mp3", "artist": "beat.wav", "program": "song.flac"},
            {"title": "", "artist": "   \t \n  ", "program": ""},
        ]
        for s in sentinels:
            res = normalize_metadata(s)
            self.assertEqual(res["title"], "ASTRAZIT RADIO")
            self.assertEqual(res["artist"], "")
            self.assertEqual(res["program"], "ASTRAZIT RADIO")

    def test_05_renderer_exception_contained(self):
        """5. Injected renderer failure does not crash controller thread or take down worker."""
        ctrl = OverlayController(target_png_path=self.target_png, fade_duration=0.05, steps_per_sec=20)
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Initial Song", "artist": "AstraZit"})
            self.assertTrue(self._wait_for_visible(ctrl))

            with patch("apps.radio.overlay.controller.render_overlay_bytes", side_effect=RuntimeError("Injected GPU/Pillow fault")):
                ctrl.submit_metadata({"title": "Crash Attempt", "artist": "Fault"})
                time.sleep(0.2)

            self.assertTrue(ctrl._running)
            self.assertTrue(ctrl._worker_thread.is_alive())

            ctrl.submit_metadata({"title": "Recovered Song", "artist": "AstraZit"})
            self.assertTrue(self._wait_for_visible(ctrl, timeout=3.0))
            self.assertEqual(ctrl.current_metadata["title"], "Recovered Song")
        finally:
            ctrl.stop()

    def test_06_corrupted_candidate_png_rejected(self):
        """6. Corrupted candidate bytes rejected; destination file untouched."""
        valid_png = render_overlay_bytes({"title": "Valid LKG"})
        self.assertTrue(atomic_write_png(self.target_png, valid_png))
        with open(self.target_png, "rb") as f:
            orig_bytes = f.read()

        corrupt_candidates = [
            b"",
            b"GIF89a",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
            b"Random unstructured non-image text",
        ]
        for c in corrupt_candidates:
            self.assertFalse(validate_png_bytes(c))
            self.assertFalse(atomic_write_png(self.target_png, c))

        with open(self.target_png, "rb") as f:
            after_bytes = f.read()
        self.assertEqual(after_bytes, orig_bytes)

    def test_07_invalid_candidate_dimensions_and_mode(self):
        """7. Invalid dimensions (e.g., not 385x88) and invalid mode (RGB instead of RGBA) rejected."""
        img_wrong_dim = Image.new("RGBA", (300, 88), (255, 255, 255, 255))
        buf = io.BytesIO()
        img_wrong_dim.save(buf, format="PNG")
        bytes_wrong_dim = buf.getvalue()
        self.assertFalse(validate_png_bytes(bytes_wrong_dim, (WIDTH, HEIGHT)))
        self.assertFalse(atomic_write_png(self.target_png, bytes_wrong_dim))

        img_wrong_mode = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
        buf = io.BytesIO()
        img_wrong_mode.save(buf, format="PNG")
        bytes_wrong_mode = buf.getvalue()
        self.assertFalse(validate_png_bytes(bytes_wrong_mode, (WIDTH, HEIGHT)))
        self.assertFalse(atomic_write_png(self.target_png, bytes_wrong_mode))

    def test_08_atomic_write_failure_preserves_lkg(self):
        """8. Atomic candidate write/replace failure preserves LKG."""
        valid_png = render_overlay_bytes({"title": "Preserved LKG"})
        self.assertTrue(atomic_write_png(self.target_png, valid_png))

        with patch("os.replace", side_effect=OSError("Disk locked / permission error")):
            new_png = render_overlay_bytes({"title": "New Attempt"})
            success = atomic_write_png(self.target_png, new_png)
            self.assertFalse(success)

        with open(self.target_png, "rb") as f:
            content = f.read()
        self.assertEqual(content, valid_png)

    def test_09_update_arriving_while_transition_active(self):
        """9. Update arriving while previous transition is active is queued in pending slot and executed."""
        ctrl = OverlayController(target_png_path=self.target_png, fade_duration=0.2, steps_per_sec=20)
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Song 1"})
            self.assertTrue(self._wait_for_visible(ctrl))

            ctrl.submit_metadata({"title": "Song 2"})
            time.sleep(0.05)

            ctrl.submit_metadata({"title": "Song 3"})

            self.assertTrue(self._wait_for_visible(ctrl, timeout=4.0))
            self.assertEqual(ctrl.current_metadata["title"], "Song 3")
        finally:
            ctrl.stop()

    def test_10_valid_pending_vs_invalid_new_update(self):
        """
        10. Explicitly prove:
        Valid metadata A is pending.
        Then invalid/malformed metadata B arrives.
        B must NOT destroy or supersede valid pending A.
        Latest VALID metadata wins.
        """
        ctrl = OverlayController(target_png_path=self.target_png, fade_duration=0.2, steps_per_sec=20)
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Song 0", "artist": "AstraZit"})
            self.assertTrue(self._wait_for_visible(ctrl))

            ctrl.submit_metadata({"title": "Song 1"})
            time.sleep(0.05)

            ctrl.submit_metadata({"title": "Valid Pending A", "artist": "Artist A"})
            self.assertEqual(ctrl.pending_metadata["title"], "Valid Pending A")

            with patch("apps.radio.overlay.controller.normalize_metadata", side_effect=ValueError("Corrupt schema payload")):
                accepted = ctrl.submit_metadata("GARBAGE_PAYLOAD")
                self.assertFalse(accepted)

            self.assertIsNotNone(ctrl.pending_metadata)
            self.assertEqual(ctrl.pending_metadata["title"], "Valid Pending A")

            self.assertTrue(self._wait_for_visible(ctrl, timeout=4.0))
            self.assertEqual(ctrl.current_metadata["title"], "Valid Pending A")
        finally:
            ctrl.stop()


if __name__ == "__main__":
    unittest.main()
