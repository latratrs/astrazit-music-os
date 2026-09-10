"""Comprehensive automated test suite for Local Demo Catalog / Catalog Sandbox.

Governed by OS-007.
Tests all requirements:
- Sandbox initialization and fixture persistence
- Expected entity counts (3 Works, 5 Recordings, 3 Releases)
- Schema and business rule validation
- Deterministic list outputs and formatting
- Detailed entity view with relationship translation
- Work->Recording and Release->Recording referential integrity
- Duplicate init safety and force overwrite
- Safe reset requiring valid demo marker
- Reset path containment and boundary enforcement
- Zero production SequenceStore or Firestore calls
- Offline / cloud safety
- Corrupted mapping and record handling
- Non-zero exit codes on errors
- CWD independence and relocated execution
- Adversarial probes
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.admin.catalog_demo.cli import main as cli_main
from apps.admin.catalog_demo.fixtures import (
    DEMO_TO_INTERNAL_ID,
    INTERNAL_TO_DEMO_ID,
    get_all_demo_fixtures,
)
from apps.admin.catalog_demo.sandbox import (
    DemoCatalogSandbox,
    DemoMappingError,
    DemoSandboxError,
    MARKER_FILE_NAME,
    SandboxSafetyError,
    SandboxUninitializedError,
)
from packages.catalog.identifiers import EntityType
from packages.catalog.repository import CatalogConflictError, CatalogStateError


class TestLocalCatalogDemo(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox_dir = Path(self.temp_dir.name) / "demo_sandbox"
        self.sandbox = DemoCatalogSandbox(sandbox_dir=self.sandbox_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. INITIALIZATION AND FIXTURE PERSISTENCE
    def test_init_succeeds_and_creates_structure(self):
        self.assertFalse(self.sandbox.is_initialized())
        counts = self.sandbox.init()
        self.assertEqual(counts["works"], 3)
        self.assertEqual(counts["recordings"], 5)
        self.assertEqual(counts["releases"], 3)
        self.assertTrue(self.sandbox.is_initialized())

        marker_file = self.sandbox_dir / MARKER_FILE_NAME
        self.assertTrue(marker_file.exists())
        marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
        self.assertEqual(marker_data["mode"], "DEMO")
        self.assertFalse(marker_data["production"])
        self.assertEqual(marker_data["schema_version"], 1)
        self.assertIn("id_mapping", marker_data)

    # 2. DUPLICATE INIT FAILS SAFELY WITHOUT FORCE
    def test_duplicate_init_fails_safely(self):
        self.sandbox.init()
        with self.assertRaises(CatalogConflictError):
            self.sandbox.init(force=False)

        # Force init succeeds and refreshes
        counts = self.sandbox.init(force=True)
        self.assertEqual(counts["works"], 3)

    # 3. FIXTURE INTEGRITY AND REFERENTIAL VALIDATION
    def test_sandbox_validation_passes(self):
        self.sandbox.init()
        res = self.sandbox.validate()
        self.assertTrue(res["valid"])
        self.assertEqual(res["issues"], [])

    # 4. DETERMINISTIC LISTING
    def test_deterministic_list_works(self):
        self.sandbox.init()
        works = self.sandbox.list_entities(EntityType.WORK)
        self.assertEqual(len(works), 3)
        self.assertEqual(works[0]["demo_id"], "DEMO-WRK-000001")
        self.assertEqual(works[0]["title"], "Electric Dream")
        self.assertEqual(works[0]["rights"], "APPROVED")

        self.assertEqual(works[1]["demo_id"], "DEMO-WRK-000002")
        self.assertEqual(works[1]["title"], "Beat in Your Veins")
        self.assertEqual(works[1]["rights"], "PENDING_HUMAN_APPROVAL")

        self.assertEqual(works[2]["demo_id"], "DEMO-WRK-000003")
        self.assertEqual(works[2]["title"], "Creatures of the Night")
        self.assertEqual(works[2]["origin"], "HISTORICAL_IMPORT")

    def test_deterministic_list_recordings(self):
        self.sandbox.init()
        recs = self.sandbox.list_entities(EntityType.RECORDING)
        self.assertEqual(len(recs), 5)
        self.assertEqual(recs[0]["demo_id"], "DEMO-REC-000001")
        self.assertEqual(recs[0]["title"], "Electric Dream -- Original Mix")
        self.assertEqual(recs[0]["work_id"], "DEMO-WRK-000001")
        self.assertEqual(recs[0]["radio"], "ELIGIBLE")
        self.assertEqual(recs[0]["rotation"], "HEAVY")

        self.assertEqual(recs[1]["demo_id"], "DEMO-REC-000002")
        self.assertEqual(recs[1]["title"], "Electric Dream -- Radio Edit")
        self.assertEqual(recs[1]["work_id"], "DEMO-WRK-000001")
        self.assertEqual(recs[1]["radio"], "ELIGIBLE")
        self.assertEqual(recs[1]["rotation"], "MEDIUM")

        self.assertEqual(recs[2]["demo_id"], "DEMO-REC-000003")
        self.assertEqual(recs[2]["radio"], "INELIGIBLE")

        self.assertEqual(recs[3]["demo_id"], "DEMO-REC-000004")
        self.assertEqual(recs[3]["origin"], "HISTORICAL_IMPORT")

        self.assertEqual(recs[4]["demo_id"], "DEMO-REC-000005")
        self.assertEqual(recs[4]["origin"], "HISTORICAL_IMPORT")

    def test_deterministic_list_releases(self):
        self.sandbox.init()
        rels = self.sandbox.list_entities(EntityType.RELEASE)
        self.assertEqual(len(rels), 3)
        self.assertEqual(rels[0]["demo_id"], "DEMO-REL-000001")
        self.assertEqual(rels[0]["title"], "Electric Dream - Single")
        self.assertEqual(rels[0]["tracks"], ["DEMO-REC-000001"])

        self.assertEqual(rels[1]["demo_id"], "DEMO-REL-000002")
        self.assertEqual(rels[1]["title"], "Beat in Your Veins - Single")
        self.assertEqual(rels[1]["tracks"], ["DEMO-REC-000003"])

        self.assertEqual(rels[2]["demo_id"], "DEMO-REL-000003")
        self.assertEqual(rels[2]["title"], "Creatures of the Night")
        self.assertEqual(rels[2]["tracks"], ["DEMO-REC-000004", "DEMO-REC-000005"])

    # 5. ENTITY DETAIL SHOW
    def test_show_entity_by_demo_id(self):
        self.sandbox.init()
        etype, doc = self.sandbox.get_entity("DEMO-WRK-000001")
        self.assertEqual(etype, EntityType.WORK)
        self.assertEqual(doc["canonical_title"], "Electric Dream")

        etype_rec, doc_rec = self.sandbox.get_entity("DEMO-REC-000001")
        self.assertEqual(etype_rec, EntityType.RECORDING)
        self.assertEqual(doc_rec["recording_title"], "Electric Dream")

        etype_rel, doc_rel = self.sandbox.get_entity("DEMO-REL-000001")
        self.assertEqual(etype_rel, EntityType.RELEASE)
        self.assertEqual(doc_rel["title"], "Electric Dream - Single")

    def test_show_entity_by_internal_id(self):
        self.sandbox.init()
        etype, doc = self.sandbox.get_entity("AST-WRK-000001")
        self.assertEqual(etype, EntityType.WORK)
        self.assertEqual(doc["canonical_title"], "Electric Dream")

    def test_unknown_demo_id_raises(self):
        self.sandbox.init()
        with self.assertRaises(DemoMappingError):
            self.sandbox.get_entity("DEMO-WRK-999999")

    # 6. SUMMARY STATS
    def test_summary_aggregates(self):
        self.sandbox.init()
        summary = self.sandbox.summary()
        self.assertEqual(summary["counts"]["works"], 3)
        self.assertEqual(summary["counts"]["recordings"], 5)
        self.assertEqual(summary["counts"]["releases"], 3)
        self.assertEqual(summary["radio"]["eligible"], 2)
        self.assertEqual(summary["radio"]["ineligible"], 3)
        self.assertEqual(summary["composition_rights"]["APPROVED"], 1)
        self.assertEqual(summary["composition_rights"]["PENDING_HUMAN_APPROVAL"], 2)

    # 7. RESET SAFETY BOUNDARIES
    def test_reset_unconfirmed_fails(self):
        self.sandbox.init()
        with self.assertRaises(SandboxSafetyError):
            self.sandbox.reset(confirmed=False)
        self.assertTrue(self.sandbox.is_initialized())

    def test_reset_without_marker_fails_closed(self):
        # Create non-demo directory
        non_demo = Path(self.temp_dir.name) / "regular_folder"
        non_demo.mkdir(parents=True, exist_ok=True)
        (non_demo / "important_file.txt").write_text("do not delete", encoding="utf-8")

        bad_sandbox = DemoCatalogSandbox(sandbox_dir=non_demo)
        with self.assertRaises(SandboxSafetyError):
            bad_sandbox.reset(confirmed=True)

        self.assertTrue((non_demo / "important_file.txt").exists())

    def test_reset_confirmed_cleans_sandbox(self):
        self.sandbox.init()
        self.assertTrue(self.sandbox.is_initialized())
        self.sandbox.reset(confirmed=True)
        self.assertFalse(self.sandbox.sandbox_dir.exists())

    # 8. NO PRODUCTION CALLS OR STATE MUTATION
    def test_zero_production_allocator_calls(self):
        """Verify that running sandbox operations never touches sequence stores."""
        with patch("packages.catalog.identifiers.IdentifierAllocator.allocate") as mock_alloc, \
             patch("packages.catalog.firestore_sequence_store.FirestoreSequenceStore") as mock_fs:
            self.sandbox.init()
            self.sandbox.summary()
            self.sandbox.list_entities(EntityType.WORK)
            self.sandbox.validate()
            self.sandbox.reset(confirmed=True)
            mock_alloc.assert_not_called()
            mock_fs.assert_not_called()

    # 9. CLI COMMANDS EXECUTION
    def test_cli_full_flow(self):
        s_dir = str(self.sandbox_dir)

        # 1. Init
        ret = cli_main(["--sandbox-dir", s_dir, "init"])
        self.assertEqual(ret, 0)

        # 2. Duplicate init without force fails
        ret_dup = cli_main(["--sandbox-dir", s_dir, "init"])
        self.assertEqual(ret_dup, 1)

        # 3. Summary
        ret_sum = cli_main(["--sandbox-dir", s_dir, "summary"])
        self.assertEqual(ret_sum, 0)

        # 4. List commands
        self.assertEqual(cli_main(["--sandbox-dir", s_dir, "list", "works"]), 0)
        self.assertEqual(cli_main(["--sandbox-dir", s_dir, "list", "recordings"]), 0)
        self.assertEqual(cli_main(["--sandbox-dir", s_dir, "list", "releases"]), 0)

        # 5. Show commands
        self.assertEqual(cli_main(["--sandbox-dir", s_dir, "show", "DEMO-WRK-000001"]), 0)
        self.assertEqual(cli_main(["--sandbox-dir", s_dir, "show", "DEMO-REC-000001"]), 0)
        self.assertEqual(cli_main(["--sandbox-dir", s_dir, "show", "DEMO-REL-000001"]), 0)

        # 6. Validate
        self.assertEqual(cli_main(["--sandbox-dir", s_dir, "validate"]), 0)

        # 7. Reset
        self.assertEqual(cli_main(["--sandbox-dir", s_dir, "reset", "--yes"]), 0)
        self.assertFalse(self.sandbox_dir.exists())

    # 10. ADVERSARIAL: CORRUPTED RECORDS FAIL VALIDATE NON-ZERO
    def test_corrupted_record_fails_validation(self):
        self.sandbox.init()
        # Corrupt one recording file
        rec_file = self.sandbox_dir / "catalog" / "recordings" / "AST-REC-000001.json"
        rec_data = json.loads(rec_file.read_text(encoding="utf-8"))
        rec_data.pop("astrazit_work_id")  # Schema violation
        rec_file.write_text(json.dumps(rec_data), encoding="utf-8")

        res = self.sandbox.validate()
        self.assertFalse(res["valid"])
        self.assertTrue(any("astrazit_work_id" in issue for issue in res["issues"]))

    # 11. ADVERSARIAL: BROKEN REFERENCE FAILS VALIDATE
    def test_broken_reference_fails_validation(self):
        self.sandbox.init()
        # Delete work file referenced by recording
        work_file = self.sandbox_dir / "catalog" / "works" / "AST-WRK-000001.json"
        work_file.unlink()

        res = self.sandbox.validate()
        self.assertFalse(res["valid"])
        self.assertTrue(any("references missing Work" in issue for issue in res["issues"]))

    # 12. CWD INDEPENDENCE
    def test_cwd_independence(self):
        orig_cwd = os.getcwd()
        try:
            temp_cwd = tempfile.mkdtemp()
            os.chdir(temp_cwd)
            sandbox = DemoCatalogSandbox(sandbox_dir=self.sandbox_dir)
            sandbox.init()
            self.assertTrue(sandbox.is_initialized())
            self.assertEqual(sandbox.summary()["counts"]["works"], 3)
        finally:
            os.chdir(orig_cwd)
            try:
                shutil.rmtree(temp_cwd)
            except OSError:
                pass

    # 13. OS-007A: INCOMPLETE SANDBOX RECOVERY
    def _make_incomplete(self):
        self.sandbox.init()
        marker_path = self.sandbox_dir / MARKER_FILE_NAME
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["initialized"] = False
        marker_path.write_text(json.dumps(marker), encoding="utf-8")

    def test_incomplete_marker_is_unreadable_but_reset_recreates(self):
        self._make_incomplete()
        self.assertFalse(self.sandbox.is_initialized())
        for operation in (self.sandbox.summary, lambda: self.sandbox.list_entities(EntityType.WORK), self.sandbox.validate):
            with self.assertRaises(SandboxSafetyError):
                operation()
        self.sandbox.reset(confirmed=True, recreate=True)
        self.assertTrue(self.sandbox.is_initialized())

    def test_init_force_recovers_incomplete_sandbox(self):
        self._make_incomplete()
        counts = self.sandbox.init(force=True)
        self.assertEqual(counts, {"works": 3, "recordings": 5, "releases": 3})
        self.assertTrue(self.sandbox.is_initialized())

    def test_incomplete_recovery_rejects_bad_marker_or_artifacts(self):
        for mutate in (
            lambda m: m.update(mode="NOT_DEMO"),
            lambda m: m.update(production=True),
            lambda m: m.update(schema_version=2),
            lambda m: m.pop("id_mapping"),
        ):
            with self.subTest(mutate=mutate):
                self._make_incomplete()
                path = self.sandbox_dir / MARKER_FILE_NAME
                marker = json.loads(path.read_text(encoding="utf-8"))
                mutate(marker)
                path.write_text(json.dumps(marker), encoding="utf-8")
                with self.assertRaises(SandboxSafetyError):
                    self.sandbox.reset(confirmed=True)
                shutil.rmtree(self.sandbox_dir)

    def test_incomplete_recovery_rejects_unexpected_file(self):
        self._make_incomplete()
        (self.sandbox_dir / "unexpected.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(SandboxSafetyError):
            self.sandbox.reset(confirmed=True)
        self.assertTrue((self.sandbox_dir / "unexpected.txt").exists())


if __name__ == "__main__":
    unittest.main()
