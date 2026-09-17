from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from packages.catalog.audio_qc import AudioQcError, _chunk_peak_and_clipping, inspect_wav


class AudioQcTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def _wav(self, samples, name="source.wav"):
        path = self.root / name
        with wave.open(str(path), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(44100)
            frames = b"".join(struct.pack("<hh", sample, sample) for sample in samples)
            output.writeframes(frames)
        return path

    @staticmethod
    def _hash(path):
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()

    @patch("packages.catalog.audio_qc.shutil.which", return_value=None)
    def test_basic_inspection_preserves_master_and_reports_limit(self, _which):
        path = self._wav([0, 1000, -1000] * 100)
        before = self._hash(path)
        result = inspect_wav(path)
        self.assertEqual(before, self._hash(path))
        self.assertTrue(result["source_preserved"])
        self.assertTrue(result["master_valid"])
        self.assertEqual(result["analysis_level"], "BASIC_ONLY")
        self.assertEqual(result["basic_pcm"]["sample_rate_hz"], 44100)
        self.assertEqual(result["basic_pcm"]["bit_depth"], 16)
        self.assertEqual(result["basic_pcm"]["channels"], 2)
        self.assertFalse(result["audio_qc_pass"])
        self.assertIsNone(result["radio_derivative_required"])
        self.assertIn("SHORT_DURATION_REQUIRES_REVIEW", result["warnings"])

    @patch("packages.catalog.audio_qc._run_ffprobe", return_value={
        "codec_name": "pcm_s16le", "sample_rate": "44100", "channels": 2,
        "bits_per_raw_sample": "16",
    })
    @patch("packages.catalog.audio_qc._run_loudness_analysis")
    def test_full_analysis_marks_derivative_need_without_creating_one(self, loudness, _probe):
        loudness.return_value = {
            "integrated_lufs": -11.0,
            "true_peak_dbtp": 1.3,
            "loudness_range_lu": 4.7,
        }
        path = self._wav([0, 12000, -12000] * 100)
        fake_probe = self.root / "ffprobe.exe"
        fake_ffmpeg = self.root / "ffmpeg.exe"
        fake_probe.touch()
        fake_ffmpeg.touch()
        before_files = sorted(item.name for item in self.root.iterdir())
        result = inspect_wav(path, ffprobe_path=fake_probe, ffmpeg_path=fake_ffmpeg)
        self.assertEqual(result["analysis_level"], "FULL")
        self.assertTrue(result["audio_qc_pass"])
        self.assertTrue(result["radio_derivative_required"])
        self.assertIn("TRUE_PEAK_EXCEEDS_RADIO_TARGET", result["warnings"])
        self.assertEqual(before_files, sorted(item.name for item in self.root.iterdir()))

    @patch("packages.catalog.audio_qc._run_ffprobe", return_value={
        "codec_name": "aac", "sample_rate": "44100", "channels": 2,
    })
    def test_ffprobe_non_pcm_conflict_fails_closed(self, _probe):
        path = self._wav([0, 1000, -1000])
        fake_probe = self.root / "ffprobe.exe"
        fake_probe.touch()
        with self.assertRaisesRegex(AudioQcError, "not uncompressed PCM"):
            inspect_wav(path, ffprobe_path=fake_probe)

    @patch("packages.catalog.audio_qc.shutil.which", return_value=None)
    def test_detects_pcm_ceiling_samples(self, _which):
        result = inspect_wav(self._wav([32767, -32768, 0]))
        self.assertEqual(result["basic_pcm"]["clipped_pcm_samples"], 4)
        self.assertIn("PCM_CLIPPING_DETECTED", result["warnings"])

    def test_optimized_chunk_scan_matches_signed_pcm_limits(self):
        data16 = struct.pack("<hhhh", 0, 32767, -32768, -1234)
        self.assertEqual(_chunk_peak_and_clipping(data16, 2), (32768, 2))
        data32 = struct.pack("<iiii", 0, 2147483647, -2147483648, 42)
        self.assertEqual(_chunk_peak_and_clipping(data32, 4), (2147483648, 2))

    def test_rejects_missing_non_wav_and_invalid_wav(self):
        with self.assertRaisesRegex(AudioQcError, "does not exist"):
            inspect_wav(self.root / "missing.wav")
        text = self.root / "source.txt"
        text.write_text("not audio", encoding="utf-8")
        with self.assertRaisesRegex(AudioQcError, "only WAV"):
            inspect_wav(text)
        invalid = self.root / "invalid.wav"
        invalid.write_bytes(b"not a wav")
        with self.assertRaisesRegex(AudioQcError, "invalid or unsupported"):
            inspect_wav(invalid)


if __name__ == "__main__":
    unittest.main()
