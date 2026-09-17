from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from packages.catalog.import_staging import (
    CSV_FIELDS,
    ImportStagingError,
    build_staging_manifest,
    write_manifest_atomic,
)


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_catalog_import.py"
SPEC = importlib.util.spec_from_file_location("prepare_catalog_import", SCRIPT)
assert SPEC and SPEC.loader
PREPARE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE_MODULE)


class CatalogImportStagingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.csv_path = self.root / "catalog.csv"

    def tearDown(self):
        self.tempdir.cleanup()

    def _write(self, rows, headers=CSV_FIELDS):
        with self.csv_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _row(song, daypart, streams, release_date="1/2/2024"):
        return {
            "song": song,
            "listeners": "0",
            "streams": str(streams),
            "saves": "0",
            "release_date": release_date,
            "exact_music_genre": "Test Genre",
            "radio_daypart": daypart,
            "genre_description": "Provisional description",
        }

    def _six_rows(self):
        labels = [
            "AstraZit Sunrise (06:00–09:00)",
            "AstraZit Day (09:00–12:00)",
            "AstraZit Future (12:00–17:00)",
            "AstraZit Sunset (17:00–21:00)",
            "AstraZit Night (21:00–02:00)",
            "AstraZit Deep Space (02:00–06:00)",
        ]
        return [self._row(f"Song {index}", label, index) for index, label in enumerate(labels, 1)]

    def test_stages_without_ids_approvals_or_readiness(self):
        self._write(self._six_rows())
        manifest = build_staging_manifest(self.csv_path)
        self.assertEqual(manifest["mode"], "STAGING_ONLY")
        self.assertFalse(manifest["canonical_write_permitted"])
        self.assertFalse(manifest["ast_id_allocation_permitted"])
        self.assertEqual(manifest["summary"]["staged_rows"], 6)
        self.assertEqual(len(manifest["representative_candidates"]), 6)
        for record in manifest["records"]:
            self.assertTrue(all(value is None for key, value in record["identity"].items()
                                if key.startswith("astrazit_")))
            self.assertEqual(record["provisional_enrichment"]["canonical_status"], "PROVISIONAL")
            self.assertEqual(record["rights_review"]["composition_rights"], "NOT_SUPPLIED")
            self.assertFalse(record["readiness"]["ready_for_radio"])

    def test_duplicate_title_is_flagged_without_merging(self):
        rows = self._six_rows()
        rows.append(self._row("  SONG 1 ", "AstraZit Night (21:00–02:00)", 99, "2/3/2025"))
        self._write(rows)
        manifest = build_staging_manifest(self.csv_path)
        self.assertEqual(manifest["summary"]["duplicate_title_groups"], 1)
        duplicate = manifest["duplicate_title_groups"][0]
        self.assertEqual(duplicate["source_rows"], [2, 8])
        self.assertEqual(duplicate["resolution"], "HUMAN_REQUIRED")
        self.assertEqual(manifest["summary"]["staged_rows"], 7)

    def test_representative_is_highest_stream_count_within_daypart(self):
        rows = self._six_rows()
        rows.append(self._row("Sunrise Leader", "AstraZit Sunrise (06:00–09:00)", 500))
        self._write(rows)
        manifest = build_staging_manifest(self.csv_path)
        sunrise = manifest["representative_candidates"][0]
        self.assertEqual(sunrise["song"], "Sunrise Leader")
        self.assertEqual(sunrise["status"], "PROVISIONAL_METADATA_ONLY")
        self.assertFalse(sunrise["radio_cleared"])

    def test_audio_qc_attachment_does_not_imply_clearance(self):
        self._write(self._six_rows())
        qc = {2: {"master_valid": True, "audio_qc_pass": True,
                  "radio_derivative_required": False}}
        record = build_staging_manifest(self.csv_path, audio_qc_by_source_row=qc)["records"][0]
        self.assertTrue(record["readiness"]["master_present"])
        self.assertTrue(record["readiness"]["audio_qc_pass"])
        self.assertFalse(record["readiness"]["radio_cleared"])
        self.assertFalse(record["readiness"]["ready_for_radio"])

    def test_rejects_unknown_audio_source_row(self):
        self._write(self._six_rows())
        with self.assertRaisesRegex(ImportStagingError, "unknown source rows"):
            build_staging_manifest(self.csv_path, audio_qc_by_source_row={99: {}})

    def test_rejects_missing_frozen_daypart(self):
        self._write(self._six_rows()[:-1])
        with self.assertRaisesRegex(ImportStagingError, "all six frozen dayparts"):
            build_staging_manifest(self.csv_path)

    def test_rejects_column_drift_invalid_date_count_and_daypart(self):
        rows = self._six_rows()
        self._write(rows, headers=CSV_FIELDS[:-1])
        with self.assertRaisesRegex(ImportStagingError, "columns must exactly equal"):
            build_staging_manifest(self.csv_path)

        rows[0]["release_date"] = "2024-01-02"
        self._write(rows)
        with self.assertRaisesRegex(ImportStagingError, "M/D/YYYY"):
            build_staging_manifest(self.csv_path)

        rows[0]["release_date"] = "1/2/2024"
        rows[0]["streams"] = "1.5"
        self._write(rows)
        with self.assertRaisesRegex(ImportStagingError, "non-negative integer"):
            build_staging_manifest(self.csv_path)

        rows[0]["streams"] = "1"
        rows[0]["radio_daypart"] = "Unknown"
        self._write(rows)
        with self.assertRaisesRegex(ImportStagingError, "unknown frozen daypart"):
            build_staging_manifest(self.csv_path)

    def test_atomic_manifest_is_deterministic(self):
        self._write(self._six_rows())
        manifest = build_staging_manifest(self.csv_path)
        destination = self.root / "nested" / "manifest.json"
        write_manifest_atomic(manifest, destination)
        first = destination.read_bytes()
        write_manifest_atomic(manifest, destination)
        self.assertEqual(first, destination.read_bytes())
        self.assertEqual(json.loads(first)["summary"]["ready_for_radio"], 0)

    def test_manifest_output_cannot_alias_input(self):
        with self.assertRaisesRegex(ImportStagingError, "cannot overwrite"):
            PREPARE_MODULE.validate_output_path(self.csv_path, self.csv_path)

    def test_manifest_output_must_be_json(self):
        with self.assertRaisesRegex(ImportStagingError, "must be a JSON file"):
            PREPARE_MODULE.validate_output_path(
                self.csv_path, self.root / "manifest.txt"
            )


if __name__ == "__main__":
    unittest.main()
