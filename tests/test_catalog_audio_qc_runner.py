from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_catalog_audio_qc.py"
SPEC = importlib.util.spec_from_file_location("run_catalog_audio_qc", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CatalogAudioQcRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.mapping = self.root / "wav-map.csv"
        with self.mapping.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["source_row", "wav_path"])
            writer.writerow([2, str((self.root / "two.wav").resolve())])
            writer.writerow([3, str((self.root / "three.wav").resolve())])
        (self.root / "two.wav").write_bytes(b"two source bytes")
        (self.root / "three.wav").write_bytes(b"three source bytes")
        self.output = self.root / "qc.json"
        self.ffmpeg = self.root / "ffmpeg.exe"
        self.ffprobe = self.root / "ffprobe.exe"

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _result(path: Path):
        return {
            "source_path": str(path.resolve()),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            "size_bytes": 100,
            "master_valid": True,
            "analysis_level": "FULL",
            "audio_qc_pass": True,
            "radio_derivative_required": False,
            "basic_pcm": {"clipped_pcm_samples": 0},
            "ffprobe": {"codec_name": "pcm_s16le"},
            "loudness": {"integrated_lufs": -14.0, "true_peak_dbtp": -1.2, "loudness_range_lu": 4.0},
            "warnings": [],
            "source_preserved": True,
        }

    def test_batch_checkpoints_and_resumes_completed_rows(self):
        calls = []

        def inspect(path, **_kwargs):
            calls.append(path.name)
            return self._result(path)

        report = MODULE.run_batch(
            self.mapping, self.output,
            ffprobe_path=self.ffprobe, ffmpeg_path=self.ffmpeg,
            inspector=inspect, tool_versions={"ffmpeg": "test", "ffprobe": "test"},
            progress=None,
        )
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["summary"]["completed_tracks"], 2)
        self.assertEqual(calls, ["two.wav", "three.wav"])
        saved = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"]["within_provisional_radio_target"], 2)

        MODULE.run_batch(
            self.mapping, self.output,
            ffprobe_path=self.ffprobe, ffmpeg_path=self.ffmpeg,
            inspector=inspect, tool_versions={"ffmpeg": "test", "ffprobe": "test"},
            progress=None,
        )
        self.assertEqual(calls, ["two.wav", "three.wav"])

    def test_resume_rejects_changed_source_bytes(self):
        def inspect(path, **_kwargs):
            return self._result(path)

        MODULE.run_batch(
            self.mapping, self.output,
            ffprobe_path=self.ffprobe, ffmpeg_path=self.ffmpeg,
            inspector=inspect, tool_versions={"ffmpeg": "test", "ffprobe": "test"},
            progress=None,
        )
        (self.root / "two.wav").write_bytes(b"changed source bytes")
        with self.assertRaisesRegex(MODULE.BatchAudioQcError, "WAV bytes changed"):
            MODULE.run_batch(
                self.mapping, self.output,
                ffprobe_path=self.ffprobe, ffmpeg_path=self.ffmpeg,
                inspector=inspect, tool_versions={"ffmpeg": "test", "ffprobe": "test"},
                progress=None,
            )

    def test_output_cannot_alias_map_or_source(self):
        common = {
            "ffprobe_path": self.ffprobe,
            "ffmpeg_path": self.ffmpeg,
            "tool_versions": {"ffmpeg": "test", "ffprobe": "test"},
            "progress": None,
        }
        with self.assertRaisesRegex(MODULE.BatchAudioQcError, "cannot overwrite the WAV map"):
            MODULE.run_batch(self.mapping, self.mapping, **common)
        with self.assertRaisesRegex(MODULE.BatchAudioQcError, "must be a JSON file"):
            MODULE.run_batch(self.mapping, self.root / "two.wav", **common)

    def test_atomic_output_temp_cannot_alias_source(self):
        output = self.root / "qc.json"
        protected_source = self.root / ".qc.json.tmp"
        protected_source.write_bytes(b"source bytes")
        with self.mapping.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["source_row", "wav_path"])
            writer.writerow([2, str(protected_source.resolve())])
        with self.assertRaisesRegex(MODULE.BatchAudioQcError, "cannot overwrite"):
            MODULE.run_batch(
                self.mapping, output,
                ffprobe_path=self.ffprobe, ffmpeg_path=self.ffmpeg,
                tool_versions={"ffmpeg": "test", "ffprobe": "test"},
                progress=None,
            )

    def test_rejects_duplicate_source_rows(self):
        self.mapping.write_text(
            "source_row,wav_path\n2,C:\\\\one.wav\n2,C:\\\\two.wav\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.BatchAudioQcError, "repeats source_row 2"):
            MODULE.load_wav_map(self.mapping)

    def test_rejects_unsafe_worker_count(self):
        with self.assertRaisesRegex(MODULE.BatchAudioQcError, "workers must be between 1 and 8"):
            MODULE.run_batch(
                self.mapping, self.output,
                ffprobe_path=self.ffprobe, ffmpeg_path=self.ffmpeg,
                tool_versions={"ffmpeg": "test", "ffprobe": "test"},
                progress=None, workers=0,
            )


if __name__ == "__main__":
    unittest.main()
