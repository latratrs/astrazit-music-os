"""Comprehensive automated test suite for Canonical CatalogRepository & Local Persistence.

Tests all requirements A through Y of ticket OS-005.
All test states are temporary and isolated; NO real production IDs or records are consumed.
"""
from __future__ import annotations

import concurrent.futures
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.catalog.identifiers import (
    EntityType,
    IdentifierAllocator,
)
from packages.catalog.local_repository import LocalJsonCatalogRepository
from packages.catalog.repository import (
    CatalogConflictError,
    CatalogError,
    CatalogIntegrityError,
    CatalogNotFoundError,
    CatalogPersistenceError,
    CatalogRepository,
    CatalogStateError,
    CatalogValidationError,
    create_with_allocated_id,
)
from packages.catalog.sequence_store import LocalJsonSequenceStore
from packages.catalog.validation import parse_strict_json

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "packages" / "schemas" / "examples"


def load_example(name: str) -> dict:
    content = (EXAMPLES_DIR / name).read_text(encoding="utf-8")
    return parse_strict_json(content)


class BaseRepositoryTestCase(unittest.TestCase):
    """Base test setup with temporary directory and repository instance."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name) / "catalog_root"
        self.repo = LocalJsonCatalogRepository(self.repo_root)

        # Load clean fictional examples
        self.work_fixture = load_example("work.single-recording.json")
        self.rec_fixture = load_example("recording.single.json")
        self.rel_fixture = load_example("release.single.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()


class TestCatalogRepository(BaseRepositoryTestCase):

    # A. CREATE WORK
    def test_create_work_persists_and_can_be_retrieved(self):
        created = self.repo.create(EntityType.WORK, self.work_fixture)
        self.assertEqual(created["astrazit_work_id"], "AST-WRK-000001")

        retrieved = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertEqual(retrieved["astrazit_work_id"], "AST-WRK-000001")
        self.assertEqual(retrieved["canonical_title"], self.work_fixture["canonical_title"])

    def test_os003_business_rules_are_enforced(self):
        invalid = copy.deepcopy(self.work_fixture)
        invalid["composition_rights"]["writers"][0]["percentage"] = 50.0
        with self.assertRaises(CatalogValidationError):
            self.repo.create(EntityType.WORK, invalid)

    def test_release_rights_gates_are_enforced_with_catalog_context(self):
        self.repo.create(EntityType.WORK, self.work_fixture)
        recording = copy.deepcopy(self.rec_fixture)
        recording["lifecycle_status"] = "RELEASED"
        recording["master_rights"]["approval_status"] = "PENDING_HUMAN_APPROVAL"
        with self.assertRaises(CatalogIntegrityError):
            self.repo.create(EntityType.RECORDING, recording)
        recording["lifecycle_status"] = "DRAFT"
        self.repo.create(EntityType.RECORDING, recording)
        release = copy.deepcopy(self.rel_fixture)
        release["lifecycle_status"] = "RELEASED"
        with self.assertRaises(CatalogIntegrityError):
            self.repo.create(EntityType.RELEASE, release)

    # B. CREATE RECORDING
    def test_create_recording_referencing_existing_work_persists(self):
        self.repo.create(EntityType.WORK, self.work_fixture)
        created_rec = self.repo.create(EntityType.RECORDING, self.rec_fixture)
        self.assertEqual(created_rec["astrazit_recording_id"], "AST-REC-000001")

        retrieved_rec = self.repo.get(EntityType.RECORDING, "AST-REC-000001")
        self.assertEqual(retrieved_rec["astrazit_work_id"], "AST-WRK-000001")

    # C. DANGLING WORK
    def test_dangling_work_reference_fails(self):
        # Work AST-WRK-000001 does not exist
        with self.assertRaises(CatalogIntegrityError):
            self.repo.create(EntityType.RECORDING, self.rec_fixture)

        self.assertFalse(self.repo.exists(EntityType.RECORDING, "AST-REC-000001"))

    # D. CREATE RELEASE
    def test_create_release_referencing_existing_recordings_persists(self):
        self.repo.create(EntityType.WORK, self.work_fixture)
        self.repo.create(EntityType.RECORDING, self.rec_fixture)

        created_rel = self.repo.create(EntityType.RELEASE, self.rel_fixture)
        self.assertEqual(created_rel["astrazit_release_id"], "AST-REL-000001")

        retrieved_rel = self.repo.get(EntityType.RELEASE, "AST-REL-000001")
        self.assertEqual(retrieved_rel["tracklist"][0]["astrazit_recording_id"], "AST-REC-000001")

    # E. DANGLING RECORDING
    def test_dangling_recording_reference_fails(self):
        with self.assertRaises(CatalogIntegrityError):
            self.repo.create(EntityType.RELEASE, self.rel_fixture)

        self.assertFalse(self.repo.exists(EntityType.RELEASE, "AST-REL-000001"))

    # F. DUPLICATE CREATE
    def test_duplicate_create_fails_and_original_remains_unchanged(self):
        self.repo.create(EntityType.WORK, self.work_fixture)

        mutated = copy.deepcopy(self.work_fixture)
        mutated["canonical_title"] = "Overwritten Horizon"

        with self.assertRaises(CatalogConflictError):
            self.repo.create(EntityType.WORK, mutated)

        retrieved = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertEqual(retrieved["canonical_title"], self.work_fixture["canonical_title"])

    # G. ID TYPE MISMATCH
    def test_id_type_mismatch_rejected(self):
        # Work with AST-REC ID
        bad_work = copy.deepcopy(self.work_fixture)
        bad_work["astrazit_work_id"] = "AST-REC-000001"
        with self.assertRaises(CatalogValidationError):
            self.repo.create(EntityType.WORK, bad_work)

        # Recording with AST-REL ID
        bad_rec = copy.deepcopy(self.rec_fixture)
        bad_rec["astrazit_recording_id"] = "AST-REL-000001"
        with self.assertRaises(CatalogValidationError):
            self.repo.create(EntityType.RECORDING, bad_rec)

        # Release with AST-WRK ID
        bad_rel = copy.deepcopy(self.rel_fixture)
        bad_rel["astrazit_release_id"] = "AST-WRK-000001"
        with self.assertRaises(CatalogValidationError):
            self.repo.create(EntityType.RELEASE, bad_rel)

        # Reference type safety: Recording references AST-REC instead of AST-WRK
        self.repo.create(EntityType.WORK, self.work_fixture)
        bad_rec_ref = copy.deepcopy(self.rec_fixture)
        bad_rec_ref["astrazit_work_id"] = "AST-REC-000001"
        with self.assertRaises(CatalogValidationError):  # fails schema regex pattern
            self.repo.create(EntityType.RECORDING, bad_rec_ref)

    # H. UPDATE
    def test_valid_update_succeeds(self):
        self.repo.create(EntityType.WORK, self.work_fixture)
        updated_doc = copy.deepcopy(self.work_fixture)
        updated_doc["canonical_title"] = "Updated Fictional Horizon"

        res = self.repo.update(EntityType.WORK, "AST-WRK-000001", updated_doc)
        self.assertEqual(res["canonical_title"], "Updated Fictional Horizon")

        retrieved = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertEqual(retrieved["canonical_title"], "Updated Fictional Horizon")

    # I. IDENTITY MUTATION
    def test_attempt_to_change_ast_id_through_update_fails(self):
        self.repo.create(EntityType.WORK, self.work_fixture)
        mutated = copy.deepcopy(self.work_fixture)
        mutated["astrazit_work_id"] = "AST-WRK-000002"

        with self.assertRaises(CatalogValidationError):
            self.repo.update(EntityType.WORK, "AST-WRK-000001", mutated)

        # Verify AST-WRK-000001 unchanged
        orig = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertEqual(orig["astrazit_work_id"], "AST-WRK-000001")
        self.assertFalse(self.repo.exists(EntityType.WORK, "AST-WRK-000002"))

    # J. UPDATE DANGLING REFERENCE
    def test_update_dangling_reference_fails(self):
        self.repo.create(EntityType.WORK, self.work_fixture)
        self.repo.create(EntityType.RECORDING, self.rec_fixture)

        # Update recording to nonexistent work
        bad_rec = copy.deepcopy(self.rec_fixture)
        bad_rec["astrazit_work_id"] = "AST-WRK-000999"
        with self.assertRaises(CatalogIntegrityError):
            self.repo.update(EntityType.RECORDING, "AST-REC-000001", bad_rec)

        # Create valid release
        self.repo.create(EntityType.RELEASE, self.rel_fixture)

        # Update release to nonexistent recording
        bad_rel = copy.deepcopy(self.rel_fixture)
        bad_rel["tracklist"][0]["astrazit_recording_id"] = "AST-REC-000999"
        with self.assertRaises(CatalogIntegrityError):
            self.repo.update(EntityType.RELEASE, "AST-REL-000001", bad_rel)

    # K. GET NOT FOUND
    def test_get_not_found(self):
        with self.assertRaises(CatalogNotFoundError):
            self.repo.get(EntityType.WORK, "AST-WRK-000999")

        self.assertFalse(self.repo.exists(EntityType.WORK, "AST-WRK-000999"))

    # L. UPDATE NOT FOUND
    def test_update_not_found(self):
        doc = copy.deepcopy(self.work_fixture)
        doc["astrazit_work_id"] = "AST-WRK-000999"
        with self.assertRaises(CatalogNotFoundError):
            self.repo.update(EntityType.WORK, "AST-WRK-000999", doc)

    # M. COPY SAFETY
    def test_copy_safety(self):
        self.repo.create(EntityType.WORK, self.work_fixture)

        retrieved = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        retrieved["canonical_title"] = "Mutated in memory"

        fresh = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertEqual(fresh["canonical_title"], self.work_fixture["canonical_title"])

    # N. RESTART PERSISTENCE
    def test_restart_persistence_and_process_isolation(self):
        self.repo.create(EntityType.WORK, self.work_fixture)

        # Separate repository instance on same root
        new_repo = LocalJsonCatalogRepository(self.repo_root)
        self.assertTrue(new_repo.exists(EntityType.WORK, "AST-WRK-000001"))
        retrieved = new_repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertEqual(retrieved["canonical_title"], self.work_fixture["canonical_title"])

        # Genuine subprocess restart check
        cmd = [
            sys.executable,
            "-c",
            (
                "from packages.catalog.local_repository import LocalJsonCatalogRepository\n"
                "from packages.catalog.identifiers import EntityType\n"
                f"repo = LocalJsonCatalogRepository(r'{self.repo_root}')\n"
                "doc = repo.get(EntityType.WORK, 'AST-WRK-000001')\n"
                "assert doc['canonical_title'] == 'Fictional Horizon'\n"
                "print('OK')\n"
            ),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertIn("OK", result.stdout)

    # O. STRICT CORRUPTION
    def test_strict_corruption_handling(self):
        self.repo.create(EntityType.WORK, self.work_fixture)
        work_file = self.repo_root / "works" / "AST-WRK-000001.json"

        # 1. Malformed JSON
        work_file.write_text("{ unquoted_key: 123 ", encoding="utf-8")
        with self.assertRaises(CatalogStateError):
            self.repo.get(EntityType.WORK, "AST-WRK-000001")
        with self.assertRaises(CatalogStateError):
            self.repo.exists(EntityType.WORK, "AST-WRK-000001")

        # 2. Duplicate keys
        work_file.write_text('{"schema_version": "1.0.0", "schema_version": "1.0.0"}', encoding="utf-8")
        with self.assertRaises(CatalogStateError):
            self.repo.get(EntityType.WORK, "AST-WRK-000001")

        # 3. NaN / Infinity
        work_file.write_text('{"schema_version": NaN}', encoding="utf-8")
        with self.assertRaises(CatalogStateError):
            self.repo.get(EntityType.WORK, "AST-WRK-000001")

        # 4. Invalid UTF-8
        work_file.write_bytes(b"\x80\x81\x82")
        with self.assertRaises(CatalogStateError):
            self.repo.get(EntityType.WORK, "AST-WRK-000001")

        # 5. Wrong root (JSON list instead of object)
        work_file.write_text("[]", encoding="utf-8")
        with self.assertRaises(CatalogStateError):
            self.repo.get(EntityType.WORK, "AST-WRK-000001")

        # 6. Schema-invalid persisted record
        from packages.catalog.local_repository import _dump_deterministic_json
        invalid_schema_record = copy.deepcopy(self.work_fixture)
        invalid_schema_record.pop("canonical_title")  # required field
        work_file.write_text(_dump_deterministic_json(invalid_schema_record), encoding="utf-8")
        with self.assertRaises(CatalogStateError):
            self.repo.get(EntityType.WORK, "AST-WRK-000001")

        # 7. Record-ID mismatch (file is AST-WRK-000001.json, content is AST-WRK-000002)
        mismatch_record = copy.deepcopy(self.work_fixture)
        mismatch_record["astrazit_work_id"] = "AST-WRK-000002"
        work_file.write_text(_dump_deterministic_json(mismatch_record), encoding="utf-8")
        with self.assertRaises(CatalogStateError):
            self.repo.get(EntityType.WORK, "AST-WRK-000001")

    # P. FAILED WRITE
    def test_failed_write_before_commit_retains_existing_record(self):
        self.repo.create(EntityType.WORK, self.work_fixture)

        # Inject failure during serialize / write before replacement
        def raise_write_failure(*args, **kwargs):
            raise OSError("Disk full simulation")

        with patch("packages.catalog.local_repository._dump_deterministic_json", side_effect=raise_write_failure):
            updated_doc = copy.deepcopy(self.work_fixture)
            updated_doc["canonical_title"] = "Failed Title"
            with self.assertRaises(CatalogPersistenceError):
                self.repo.update(EntityType.WORK, "AST-WRK-000001", updated_doc)

        # Verify canonical state is pristine
        current = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertEqual(current["canonical_title"], self.work_fixture["canonical_title"])


    # Q. AMBIGUOUS POST-COMMIT FAILURE
    def test_post_commit_failure_behavior(self):
        self.repo.create(EntityType.WORK, self.work_fixture)

        real_replace = os.replace

        def replace_then_raise(src, dst):
            real_replace(src, dst)
            raise OSError("Post-replace network/response drop")

        with patch("os.replace", side_effect=replace_then_raise):
            updated_doc = copy.deepcopy(self.work_fixture)
            updated_doc["canonical_title"] = "Committed Title"
            with self.assertRaises(CatalogPersistenceError):
                self.repo.update(EntityType.WORK, "AST-WRK-000001", updated_doc)

        # Verify we do NOT blindly rollback or corrupt the file; the replaced state is present
        current = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertEqual(current["canonical_title"], "Committed Title")

    # R. SAME-ID CONCURRENT CREATE
    def test_same_id_concurrent_create(self):
        errors: list[Exception] = []
        successes: list[str] = []

        def worker(worker_id: int):
            rec = copy.deepcopy(self.work_fixture)
            rec["canonical_title"] = f"Worker {worker_id}"
            local_repo = LocalJsonCatalogRepository(self.repo_root)
            try:
                local_repo.create(EntityType.WORK, rec)
                successes.append(f"Worker {worker_id}")
            except CatalogConflictError as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(successes), 1, "Exactly one worker must succeed in creating the ID")
        self.assertEqual(len(errors), 9, "All 9 other workers must fail with CatalogConflictError")

        # Canonical record remains valid
        final_doc = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertIn(final_doc["canonical_title"], [f"Worker {i}" for i in range(10)])

    def test_same_id_concurrent_create_multiprocess(self):
        """Independent OS processes racing to create the exact same AST ID."""
        worker_code = """
import sys
import copy
from pathlib import Path
from packages.catalog.identifiers import EntityType
from packages.catalog.local_repository import LocalJsonCatalogRepository
from packages.catalog.repository import CatalogConflictError
from packages.catalog.validation import parse_strict_json

repo_root = Path(sys.argv[1])
proc_id = sys.argv[2]
fixture_path = Path(sys.argv[3])
fixture = parse_strict_json(fixture_path.read_text(encoding='utf-8'))
fixture['canonical_title'] = f"Process {proc_id}"

repo = LocalJsonCatalogRepository(repo_root)
print('READY', flush=True)
sys.stdin.readline()
try:
    repo.create(EntityType.WORK, fixture)
    print("SUCCESS")
except CatalogConflictError:
    print("CONFLICT")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
"""
        num_procs = 5
        fixture_file = EXAMPLES_DIR / "work.single-recording.json"
        procs = []
        for i in range(num_procs):
            p = subprocess.Popen(
                [sys.executable, "-c", worker_code, str(self.repo_root), str(i), str(fixture_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                cwd=str(Path(__file__).resolve().parent.parent),
            )
            procs.append(p)

        # Wait for all processes to report READY
        for p in procs:
            line = p.stdout.readline().strip()
            self.assertEqual(line, "READY")

        # Release all processes simultaneously
        for p in procs:
            p.stdin.write("\n")
            p.stdin.flush()

        results = []
        for p in procs:
            stdout, stderr = p.communicate()
            res = stdout.strip()
            results.append(res)

        self.assertEqual(results.count("SUCCESS"), 1, f"Expected 1 SUCCESS, got {results}")
        self.assertEqual(results.count("CONFLICT"), num_procs - 1, f"Expected {num_procs - 1} CONFLICTs, got {results}")

        final_doc = self.repo.get(EntityType.WORK, "AST-WRK-000001")
        self.assertIn(final_doc["canonical_title"], [f"Process {i}" for i in range(num_procs)])


    # S. DIFFERENT-ID CONCURRENT CREATE
    def test_different_id_concurrent_create(self):
        count = 10

        def worker(index: int):
            rec = copy.deepcopy(self.work_fixture)
            rec["astrazit_work_id"] = f"AST-WRK-{index:06d}"
            rec["canonical_title"] = f"Work {index}"
            local_repo = LocalJsonCatalogRepository(self.repo_root)
            return local_repo.create(EntityType.WORK, rec)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker, i + 1) for i in range(count)]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                self.assertTrue(res["astrazit_work_id"].startswith("AST-WRK-"))

        ids = self.repo.list_ids(EntityType.WORK)
        self.assertEqual(len(ids), count)
        self.assertEqual(ids, [f"AST-WRK-{i+1:06d}" for i in range(count)])

    def test_same_instance_concurrent_create(self):
        """One repository instance must safely serialize its shared FileLock handle."""
        count = 20
        def worker(index: int):
            rec = copy.deepcopy(self.work_fixture)
            rec["astrazit_work_id"] = f"AST-WRK-{index:06d}"
            return self.repo.create(EntityType.WORK, rec)["astrazit_work_id"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            ids = list(executor.map(worker, range(1, count + 1)))
        self.assertEqual(set(ids), {f"AST-WRK-{i:06d}" for i in range(1, count + 1)})
        self.assertEqual(self.repo.list_ids(EntityType.WORK), sorted(ids))

    # T. CWD INDEPENDENCE
    def test_cwd_independence(self):
        original_cwd = os.getcwd()
        try:
            temp_cwd = tempfile.mkdtemp()
            os.chdir(temp_cwd)

            # Repository operating on absolute repo_root
            repo = LocalJsonCatalogRepository(self.repo_root)
            repo.create(EntityType.WORK, self.work_fixture)

            self.assertTrue(repo.exists(EntityType.WORK, "AST-WRK-000001"))
            retrieved = repo.get(EntityType.WORK, "AST-WRK-000001")
            self.assertEqual(retrieved["astrazit_work_id"], "AST-WRK-000001")
        finally:
            os.chdir(original_cwd)
            try:
                shutil.rmtree(temp_cwd)
            except OSError:
                pass

    # U. RELOCATED CHECKOUT
    def test_relocated_checkout(self):
        # Verify repository functions cleanly from another filesystem directory
        other_dir = Path(self.temp_dir.name) / "relocated_repo"
        repo = LocalJsonCatalogRepository(other_dir)
        repo.create(EntityType.WORK, self.work_fixture)
        self.assertTrue(repo.exists(EntityType.WORK, "AST-WRK-000001"))
        self.assertEqual(repo.list_ids(EntityType.WORK), ["AST-WRK-000001"])

    # V. LIST DETERMINISM
    def test_list_ids_determinism_and_corruption_detection(self):
        for seq in (3, 1, 2):
            doc = copy.deepcopy(self.work_fixture)
            doc["astrazit_work_id"] = f"AST-WRK-{seq:06d}"
            self.repo.create(EntityType.WORK, doc)

        ids = self.repo.list_ids(EntityType.WORK)
        self.assertEqual(ids, ["AST-WRK-000001", "AST-WRK-000002", "AST-WRK-000003"])

        # Foreign non-JSON file in works directory must fail closed
        bad_file = self.repo_root / "works" / "rogue.txt"
        bad_file.write_text("corrupted", encoding="utf-8")
        with self.assertRaises(CatalogStateError):
            self.repo.list_ids(EntityType.WORK)

        bad_file.unlink()

        # Non-AST json file in works directory must fail closed
        bad_json = self.repo_root / "works" / "not_an_id.json"
        bad_json.write_text("{}", encoding="utf-8")
        with self.assertRaises(CatalogStateError):
            self.repo.list_ids(EntityType.WORK)


    # W. NO DELETE
    def test_no_destructive_delete_api(self):
        self.assertFalse(hasattr(self.repo, "delete"), "CatalogRepository must not expose public delete method")
        self.assertFalse(hasattr(self.repo, "remove"), "CatalogRepository must not expose public remove method")

    # Orchestration Helper test with OS-004 Allocator
    def test_create_with_allocated_id_orchestration(self):
        alloc_path = Path(self.temp_dir.name) / "test_sequences.json"
        seq_store = LocalJsonSequenceStore(alloc_path)
        allocator = IdentifierAllocator(seq_store)

        def make_work(ast_id: str) -> dict:
            doc = copy.deepcopy(self.work_fixture)
            doc["astrazit_work_id"] = ast_id
            return doc

        result = create_with_allocated_id(allocator, self.repo, EntityType.WORK, make_work)
        self.assertEqual(result["astrazit_work_id"], "AST-WRK-000001")
        self.assertTrue(self.repo.exists(EntityType.WORK, "AST-WRK-000001"))
        self.assertEqual(allocator.current_sequence(EntityType.WORK), 1)

    # Path traversal protection
    def test_path_traversal_rejected(self):
        for bad_id in ("../AST-WRK-000001", "AST-WRK-000001/foo", "..\\AST-WRK-000001"):
            with self.assertRaises(CatalogValidationError):
                self.repo.get(EntityType.WORK, bad_id)
            with self.assertRaises(CatalogValidationError):
                self.repo.exists(EntityType.WORK, bad_id)


if __name__ == "__main__":
    unittest.main()
