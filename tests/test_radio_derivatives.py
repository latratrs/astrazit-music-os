from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_radio_derivatives.py"
SPEC = importlib.util.spec_from_file_location("create_radio_derivatives", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RadioDerivativeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.mapping = self.root / "representatives.csv"

    def tearDown(self):
        self.tempdir.cleanup()

    def write_map(self, rows=None, columns=None):
        rows = rows or [
            [daypart, index + 2, f"Track {index}", str((self.root / f"{index}.wav").resolve()), "A" * 64]
            for index, daypart in enumerate(MODULE.DAYPARTS)
        ]
        with self.mapping.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(columns or MODULE.MAP_COLUMNS)
            writer.writerows(rows)

    def test_loads_exactly_one_representative_per_frozen_daypart(self):
        self.write_map()
        rows = MODULE.load_map(self.mapping)
        self.assertEqual([row["daypart"] for row in rows], list(MODULE.DAYPARTS))

    def test_rejects_missing_daypart(self):
        rows = [
            [daypart, index + 2, f"Track {index}", str((self.root / f"{index}.wav").resolve()), "A" * 64]
            for index, daypart in enumerate(MODULE.DAYPARTS[:-1])
        ]
        self.write_map(rows)
        with self.assertRaisesRegex(MODULE.RadioDerivativeError, "exactly one row"):
            MODULE.load_map(self.mapping)

    def test_rejects_column_drift(self):
        self.write_map(columns=["daypart", "source_row", "title", "wav_path", "sha256"])
        with self.assertRaisesRegex(MODULE.RadioDerivativeError, "columns must exactly"):
            MODULE.load_map(self.mapping)

    def test_output_name_is_deterministic_and_safe(self):
        row = {"daypart": "DEEP SPACE", "source_row": 23, "title": "Walk In The Rain: After Party?"}
        self.assertEqual(
            MODULE.output_name(row),
            "deep-space__walk-in-the-rain-after-party__row-023__radio.wav",
        )

    def test_second_pass_filter_uses_measured_values_and_builtin_dither(self):
        measurement = {
            "input_i": "-10.0", "input_tp": "1.2", "input_lra": "5.0",
            "input_thresh": "-20.0", "target_offset": "0.1",
        }
        value = MODULE.second_pass_filter(measurement)
        self.assertIn("measured_I=-10.0", value)
        self.assertIn("TP=-1.5", value)
        self.assertIn("aresample=44100", value)
        self.assertIn("dither_method=triangular", value)
        self.assertNotIn("resampler=soxr", value)

    def test_verify_output_rejects_true_peak_over_ceiling(self):
        qc = {
            "basic_pcm": {
                "sample_rate_hz": 44100, "bit_depth": 16, "channels": 2,
                "clipped_pcm_samples": 0, "duration_seconds": 180.0,
            },
            "loudness": {"integrated_lufs": -14.0, "true_peak_dbtp": -0.9},
        }
        with self.assertRaisesRegex(MODULE.RadioDerivativeError, "true peak"):
            MODULE.verify_output(qc, 180.0)

    def test_verify_output_accepts_dynamic_loudnorm_tolerance(self):
        qc = {
            "basic_pcm": {
                "sample_rate_hz": 44100, "bit_depth": 16, "channels": 2,
                "clipped_pcm_samples": 0, "duration_seconds": 108.0,
            },
            "loudness": {"integrated_lufs": -14.31, "true_peak_dbtp": -1.35},
        }
        MODULE.verify_output(qc, 108.0)

    def test_verify_output_accepts_calibrated_low_dynamic_result(self):
        qc = {
            "basic_pcm": {
                "sample_rate_hz": 44100, "bit_depth": 16, "channels": 2,
                "clipped_pcm_samples": 0, "duration_seconds": 180.0,
            },
            "loudness": {"integrated_lufs": -14.72, "true_peak_dbtp": -1.32},
        }
        MODULE.verify_output(qc, 180.0)

    def test_report_cannot_alias_input_map(self):
        self.write_map()
        with self.assertRaisesRegex(MODULE.RadioDerivativeError, "cannot overwrite"):
            MODULE.create_derivatives(
                self.mapping,
                self.root / "output",
                self.mapping,
                ffmpeg=self.root / "ffmpeg.exe",
                ffprobe=self.root / "ffprobe.exe",
            )

    def test_partial_output_cannot_alias_any_source(self):
        output_dir = self.root / "output"
        first = {
            "daypart": MODULE.DAYPARTS[0], "source_row": 2, "title": "Track 0",
        }
        destination = output_dir / MODULE.output_name(first)
        protected_source = destination.with_name(f".{destination.stem}.partial.wav")
        rows = [
            [daypart, index + 2, f"Track {index}",
             str((protected_source if index == 1 else self.root / f"{index}.wav").resolve()),
             "A" * 64]
            for index, daypart in enumerate(MODULE.DAYPARTS)
        ]
        self.write_map(rows)
        with self.assertRaisesRegex(MODULE.RadioDerivativeError, "cannot overwrite"):
            MODULE.create_derivatives(
                self.mapping, output_dir, self.root / "report.json",
                ffmpeg=self.root / "ffmpeg.exe", ffprobe=self.root / "ffprobe.exe",
            )


if __name__ == "__main__":
    unittest.main()
