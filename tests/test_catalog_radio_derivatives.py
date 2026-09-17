from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_catalog_radio_derivatives.py"
SPEC = importlib.util.spec_from_file_location("run_catalog_radio_derivatives", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CatalogRadioDerivativeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.mapping = self.root / "catalog-map.csv"

    def tearDown(self):
        self.tempdir.cleanup()

    def write_map(self, rows=None, columns=None):
        rows = rows or [[
            2, "A Test Track", str((self.root / "source.wav").resolve()), "A" * 64, "123.5",
        ]]
        with self.mapping.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(columns or MODULE.MAP_COLUMNS)
            writer.writerows(rows)

    def test_load_map_requires_exact_columns(self):
        self.write_map(columns=["source_row", "title", "wav_path", "sha256", "duration"])
        with self.assertRaisesRegex(MODULE.CatalogDerivativeError, "columns must exactly"):
            MODULE.load_map(self.mapping)

    def test_load_map_rejects_duplicate_source_rows(self):
        row = [2, "A", str((self.root / "a.wav").resolve()), "A" * 64, "123"]
        self.write_map([row, [2, "B", str((self.root / "b.wav").resolve()), "B" * 64, "124"]])
        with self.assertRaisesRegex(MODULE.CatalogDerivativeError, "repeats source_row 2"):
            MODULE.load_map(self.mapping)

    def test_output_name_uses_source_row_and_safe_title(self):
        self.assertEqual(
            MODULE.output_name({"source_row": 20, "title": "Over the Ranbow?"}),
            "row-020__over-the-ranbow__radio.wav",
        )

    def test_resumable_item_requires_matching_output_hash(self):
        destination = self.root / "output.wav"
        destination.write_bytes(b"audio")
        source = self.root / "source.wav"
        source.write_bytes(b"source audio")
        source_hash = MODULE.sha256(source)
        row = {
            "source_row": 2,
            "source_path": source,
            "expected_source_sha256": source_hash,
        }
        prior = {
            "status": "PASS", "source_row": 2, "source_path": str(row["source_path"]),
            "source_sha256": source_hash, "destination": str(destination),
            "output_sha256": MODULE.sha256(destination),
        }
        self.assertTrue(MODULE._resumable_item(prior, row, destination))
        prior["output_sha256"] = "0" * 64
        self.assertFalse(MODULE._resumable_item(prior, row, destination))

    def test_resumable_item_rejects_changed_source_hash(self):
        source = self.root / "source.wav"
        destination = self.root / "output.wav"
        source.write_bytes(b"approved source")
        destination.write_bytes(b"derivative")
        approved_hash = MODULE.sha256(source)
        row = {
            "source_row": 2,
            "source_path": source,
            "expected_source_sha256": approved_hash,
        }
        prior = {
            "status": "PASS", "source_row": 2, "source_path": str(source),
            "source_sha256": approved_hash, "destination": str(destination),
            "output_sha256": MODULE.sha256(destination),
        }
        source.write_bytes(b"changed source")
        self.assertFalse(MODULE._resumable_item(prior, row, destination))

    def test_worker_count_is_bounded(self):
        self.write_map()
        with self.assertRaisesRegex(MODULE.CatalogDerivativeError, "workers must be between 1 and 6"):
            MODULE.run_batch(
                self.mapping, self.root / "out", self.root / "report.json",
                ffmpeg=self.root / "ffmpeg.exe", ffprobe=self.root / "ffprobe.exe", workers=7,
            )

    def test_partial_output_cannot_alias_source(self):
        output_dir = self.root / "out"
        row = {"source_row": 2, "title": "A Test Track"}
        destination = output_dir / MODULE.output_name(row)
        source = destination.with_name(f".{destination.stem}.partial.wav")
        self.write_map([[
            2, row["title"], str(source.resolve()), "A" * 64, "123.5",
        ]])
        self.ffmpeg = self.root / "ffmpeg.exe"
        self.ffprobe = self.root / "ffprobe.exe"
        self.ffmpeg.touch()
        self.ffprobe.touch()
        with self.assertRaisesRegex(MODULE.CatalogDerivativeError, "cannot overwrite"):
            MODULE.run_batch(
                self.mapping, output_dir, self.root / "report.json",
                ffmpeg=self.ffmpeg, ffprobe=self.ffprobe,
            )


if __name__ == "__main__":
    unittest.main()
