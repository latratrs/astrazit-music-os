"""Comprehensive automated test suite for AST Identifier Allocator & Sequence Store.

Tests all requirements A through O of ticket OS-004.
All test states are temporary and isolated; NO real production IDs are consumed.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.catalog.identifiers import (
    AllocatorError,
    EntityType,
    IdentifierAllocator,
    InvalidEntityTypeError,
    MAX_SEQUENCE,
    MIN_SEQUENCE,
    SequenceExhaustedError,
    SequencePersistenceError,
    SequenceStateError,
    format_identifier,
    parse_identifier,
)
from packages.catalog.sequence_store import (
    LocalJsonSequenceStore,
    SequenceStore,
)


class BaseAllocatorTestCase(unittest.TestCase):
    """Base setup creating temporary isolated state files for testing."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "test_sequences.json"
        self.store = LocalJsonSequenceStore(self.state_path)
        self.allocator = IdentifierAllocator(self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()


class TestIdentifierAllocator(BaseAllocatorTestCase):

    def test_deleted_state_fails_closed_across_instances(self):
        self.allocator.allocate('WORK')
        self.state_path.unlink()
        fresh = IdentifierAllocator(LocalJsonSequenceStore(self.state_path))
        for allocator in (self.allocator, fresh):
            for method in (allocator.allocate, allocator.peek_next, allocator.current_sequence):
                with self.assertRaises(SequenceStateError):
                    method('WORK')
        self.assertFalse(self.state_path.exists())

    def test_inspection_has_no_filesystem_writes(self):
        nested = Path(self.temp_dir.name) / 'absent' / 'state.json'
        allocator = IdentifierAllocator(LocalJsonSequenceStore(nested))
        for _ in range(3):
            self.assertEqual(allocator.current_sequence('WORK'), 0)
            self.assertEqual(allocator.peek_next('WORK'), 'AST-WRK-000001')
        self.assertEqual(list(Path(self.temp_dir.name).iterdir()), [])
        self.allocator.allocate('WORK')
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in Path(self.temp_dir.name).iterdir()}
        for _ in range(3):
            self.allocator.peek_next('WORK')
            self.allocator.current_sequence('WORK')
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                                 for p in Path(self.temp_dir.name).iterdir()})

    def test_entity_input_contract(self):
        for value in ('WORK', 'work', ' WORK '):
            self.assertEqual(EntityType.from_value(value), EntityType.WORK)
        self.assertEqual(EntityType.from_value('RECORDING\n'), EntityType.RECORDING)
        for value in (None, True, False, 1, 0, object(), {}, [], 'AST-WRK-', 'FOURTH'):
            for method in (self.allocator.allocate, self.allocator.peek_next,
                           self.allocator.current_sequence, self.store.get_next_sequence):
                with self.assertRaises(InvalidEntityTypeError):
                    method(value)
        self.assertEqual(list(Path(self.temp_dir.name).iterdir()), [])
        for value in ('AST-WRK-000001\n', 'AST-REC-000001\r\n', 'AST-REL-000001 '):
            with self.assertRaises(AllocatorError):
                parse_identifier(value)

    def test_post_replace_failure_burns_sequence(self):
        self.allocator.allocate('WORK')
        replace = os.replace
        def replace_then_raise(source, target):
            replace(source, target)
            raise OSError('Response lost after replacement')
        with patch('packages.catalog.sequence_store.os.replace', side_effect=replace_then_raise):
            with self.assertRaises(SequencePersistenceError):
                self.allocator.allocate('WORK')
        self.assertEqual(self.allocator.current_sequence('WORK'), 2)
        self.assertEqual(self.allocator.allocate('WORK'), 'AST-WRK-000003')

    def test_pre_replace_failure_stages(self):
        self.allocator.allocate('WORK')
        before = self.state_path.read_bytes()
        for target in ('tempfile.NamedTemporaryFile', 'json.dumps', 'os.fsync', 'os.replace'):
            with self.subTest(stage=target):
                with patch('packages.catalog.sequence_store.' + target, side_effect=OSError('injected')):
                    with self.assertRaises(SequencePersistenceError):
                        self.allocator.allocate('WORK')
                self.assertEqual(self.state_path.read_bytes(), before)
                self.assertEqual(list(self.state_path.parent.glob('.ast_seq_tmp_*')), [])
        original = tempfile.NamedTemporaryFile
        for stage in ('write', 'flush'):
            def failing_file(*args, **kwargs):
                result = original(*args, **kwargs)
                setattr(result, stage, lambda *a, **k: (_ for _ in ()).throw(OSError('injected')))
                return result
            with patch('packages.catalog.sequence_store.tempfile.NamedTemporaryFile', side_effect=failing_file):
                with self.assertRaises(SequencePersistenceError):
                    self.allocator.allocate('WORK')
            self.assertEqual(self.state_path.read_bytes(), before)
            self.assertEqual(list(self.state_path.parent.glob('.ast_seq_tmp_*')), [])
        self.assertEqual(self.allocator.allocate('WORK'), 'AST-WRK-000002')

    def test_failed_initial_commit_requires_recovery(self):
        with patch('packages.catalog.sequence_store.os.replace', side_effect=OSError('injected')):
            with self.assertRaises(SequencePersistenceError):
                self.allocator.allocate('WORK')
        self.assertTrue(self.store.marker_path.exists())
        with self.assertRaises(SequenceStateError):
            self.allocator.allocate('WORK')

    def test_separate_instances_and_path_aliases_contend(self):
        barrier = threading.Barrier(4)
        paths = [self.state_path, self.state_path.parent / '.' / self.state_path.name,
                 self.state_path.parent / '..' / self.state_path.parent.name / self.state_path.name,
                 Path(os.path.relpath(self.state_path))]
        if sys.platform == 'win32':
            paths[-1] = Path(str(self.state_path).upper())
        def worker(path):
            allocator = IdentifierAllocator(LocalJsonSequenceStore(path))
            barrier.wait(timeout=10)
            return [allocator.allocate('WORK') for _ in range(10)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(worker, paths))
        ids = [value for result in results for value in result]
        self.assertEqual(len(ids), 40)
        self.assertEqual(set(ids), {f'AST-WRK-{i:06d}' for i in range(1, 41)})

    def test_real_process_restart(self):
        code = ('import sys; from packages.catalog import *; '
                'print(IdentifierAllocator(LocalJsonSequenceStore(sys.argv[1])).allocate("WORK"))')
        for expected in ('AST-WRK-000001', 'AST-WRK-000002'):
            child = subprocess.run([sys.executable, '-c', code, str(self.state_path)],
                                   cwd=Path(__file__).resolve().parents[1],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stdout.strip(), expected)

    def test_additional_strict_corruption_cases(self):
        cases = ['null', '[' * 1500 + ']' * 1500]
        for value in ('1.0', '-Infinity', 'true', 'false', '[]', '{}'):
            cases.append('{"schema_version":1,"sequences":{"WORK":' + value +
                         ',"RECORDING":0,"RELEASE":0}}')
        cases.append('{"schema_version":1,"sequences":{"WORK":1,"WORK":0,"RECORDING":0,"RELEASE":0}}')
        for ns in ('WORK', 'RECORDING', 'RELEASE'):
            sequences = {'WORK': 0, 'RECORDING': 0, 'RELEASE': 0}
            del sequences[ns]
            cases.append(json.dumps({'schema_version': 1, 'sequences': sequences}))
        for data in [s.encode() for s in cases] + [b'\xff']:
            self.state_path.write_bytes(data)
            for method in (self.allocator.allocate, self.allocator.peek_next, self.allocator.current_sequence):
                with self.assertRaises(SequenceStateError):
                    method('WORK')
            self.assertEqual(self.state_path.read_bytes(), data)

    # =========================================================================
    # A. FIRST ALLOCATION
    # =========================================================================
    def test_first_allocation(self) -> None:
        """WORK -> AST-WRK-000001, RECORDING -> AST-REC-000001, RELEASE -> AST-REL-000001."""
        id_wrk = self.allocator.allocate(EntityType.WORK)
        id_rec = self.allocator.allocate(EntityType.RECORDING)
        id_rel = self.allocator.allocate(EntityType.RELEASE)

        self.assertEqual(id_wrk, "AST-WRK-000001")
        self.assertEqual(id_rec, "AST-REC-000001")
        self.assertEqual(id_rel, "AST-REL-000001")

        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 1)
        self.assertEqual(self.allocator.current_sequence(EntityType.RECORDING), 1)
        self.assertEqual(self.allocator.current_sequence(EntityType.RELEASE), 1)

    # =========================================================================
    # B. MONOTONIC ALLOCATION
    # =========================================================================
    def test_monotonic_allocation(self) -> None:
        """WORK: 000001, 000002, 000003."""
        ids = [self.allocator.allocate(EntityType.WORK) for _ in range(3)]
        self.assertEqual(ids, [
            "AST-WRK-000001",
            "AST-WRK-000002",
            "AST-WRK-000003",
        ])
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 3)

    # =========================================================================
    # C. NAMESPACE INDEPENDENCE
    # =========================================================================
    def test_namespace_independence(self) -> None:
        """Allocate WORK, WORK, RECORDING, RELEASE, RECORDING."""
        res = [
            self.allocator.allocate(EntityType.WORK),
            self.allocator.allocate(EntityType.WORK),
            self.allocator.allocate(EntityType.RECORDING),
            self.allocator.allocate(EntityType.RELEASE),
            self.allocator.allocate(EntityType.RECORDING),
        ]
        expected = [
            "AST-WRK-000001",
            "AST-WRK-000002",
            "AST-REC-000001",
            "AST-REL-000001",
            "AST-REC-000002",
        ]
        self.assertEqual(res, expected)
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 2)
        self.assertEqual(self.allocator.current_sequence(EntityType.RECORDING), 2)
        self.assertEqual(self.allocator.current_sequence(EntityType.RELEASE), 1)

    # =========================================================================
    # D. RESTART PERSISTENCE
    # =========================================================================
    def test_restart_persistence(self) -> None:
        """Allocate IDs, destroy allocator, instantiate new allocator on same store."""
        self.allocator.allocate(EntityType.WORK)
        self.allocator.allocate(EntityType.WORK)
        self.allocator.allocate(EntityType.RECORDING)

        # Re-instantiate against same file
        new_store = LocalJsonSequenceStore(self.state_path)
        new_allocator = IdentifierAllocator(new_store)

        self.assertEqual(new_allocator.current_sequence(EntityType.WORK), 2)
        self.assertEqual(new_allocator.current_sequence(EntityType.RECORDING), 1)
        self.assertEqual(new_allocator.current_sequence(EntityType.RELEASE), 0)

        # Allocate further
        self.assertEqual(new_allocator.allocate(EntityType.WORK), "AST-WRK-000003")
        self.assertEqual(new_allocator.allocate(EntityType.RECORDING), "AST-REC-000002")
        self.assertEqual(new_allocator.allocate(EntityType.RELEASE), "AST-REL-000001")

    # =========================================================================
    # E. INVALID ENTITY TYPE
    # =========================================================================
    def test_invalid_entity_type(self) -> None:
        """Must fail without changing state."""
        self.allocator.allocate(EntityType.WORK)
        initial_seq = self.allocator.current_sequence(EntityType.WORK)

        for bad in ["TRACK", "ALBUM", "SONG", "AST-WRK", "", None, 123, object()]:
            with self.assertRaises(InvalidEntityTypeError):
                self.allocator.allocate(bad)  # type: ignore

            with self.assertRaises(InvalidEntityTypeError):
                self.allocator.peek_next(bad)  # type: ignore

            with self.assertRaises(InvalidEntityTypeError):
                self.allocator.current_sequence(bad)  # type: ignore

        # Ensure state unchanged
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), initial_seq)

    # =========================================================================
    # F. EXHAUSTION
    # =========================================================================
    def test_exhaustion(self) -> None:
        """999999 is final legal value; next allocation fails closed, others continue."""
        # Seed store directly with WORK at 999998
        seed_data = {
            "schema_version": 1,
            "sequences": {
                "WORK": 999998,
                "RECORDING": 0,
                "RELEASE": 0,
            },
        }
        self.state_path.write_text(json.dumps(seed_data), encoding="utf-8")

        store = LocalJsonSequenceStore(self.state_path)
        allocator = IdentifierAllocator(store)

        # 999999 succeeds
        last_id = allocator.allocate(EntityType.WORK)
        self.assertEqual(last_id, "AST-WRK-999999")
        self.assertEqual(allocator.current_sequence(EntityType.WORK), 999999)

        # Peek fails with SequenceExhaustedError
        with self.assertRaises(SequenceExhaustedError):
            allocator.peek_next(EntityType.WORK)

        # 1000000 fails closed with SequenceExhaustedError
        with self.assertRaises(SequenceExhaustedError):
            allocator.allocate(EntityType.WORK)

        # Counter remains 999999 (did not wrap or reset)
        self.assertEqual(allocator.current_sequence(EntityType.WORK), 999999)

        # Other namespaces are independent and continue operating
        self.assertEqual(allocator.allocate(EntityType.RECORDING), "AST-REC-000001")
        self.assertEqual(allocator.allocate(EntityType.RELEASE), "AST-REL-000001")

    # =========================================================================
    # G. CORRUPTED STATE
    # =========================================================================
    def test_corrupted_state_fails_closed(self) -> None:
        """Malformed persisted state must fail closed; no automatic reset."""
        corruptions = [
            "{ not valid json }",
            "",
            "[]",
            "123",
            '"a string"',
            '{"schema_version": 1}',  # missing sequences
            '{"sequences": {"WORK": 0, "RECORDING": 0, "RELEASE": 0}}',  # missing schema_version
            '{"schema_version": 2, "sequences": {"WORK": 0, "RECORDING": 0, "RELEASE": 0}}',  # unsupported version
        ]
        for corrupt in corruptions:
            self.state_path.write_text(corrupt, encoding="utf-8")
            store = LocalJsonSequenceStore(self.state_path)
            allocator = IdentifierAllocator(store)

            with self.assertRaises(SequenceStateError):
                allocator.allocate(EntityType.WORK)

            with self.assertRaises(SequenceStateError):
                allocator.peek_next(EntityType.WORK)

            with self.assertRaises(SequenceStateError):
                allocator.current_sequence(EntityType.WORK)

            # Assert the file was NOT automatically reset or overwritten
            self.assertEqual(self.state_path.read_text(encoding="utf-8"), corrupt)

    # =========================================================================
    # H. WRONG TYPES
    # =========================================================================
    def test_wrong_types_rejected(self) -> None:
        """Reject '1', 1.5, True, False, None, negative values."""
        bad_values = ["1", 1.5, True, False, None, -1, -100, 1000000, 9999999]
        for bad_val in bad_values:
            data = {
                "schema_version": 1,
                "sequences": {
                    "WORK": bad_val,
                    "RECORDING": 0,
                    "RELEASE": 0,
                },
            }
            self.state_path.write_text(json.dumps(data), encoding="utf-8")
            store = LocalJsonSequenceStore(self.state_path)
            allocator = IdentifierAllocator(store)

            with self.assertRaises(SequenceStateError):
                allocator.allocate(EntityType.WORK)

    # =========================================================================
    # I. UNKNOWN STATE FIELDS / NAMESPACES
    # =========================================================================
    def test_unknown_state_fields_rejected(self) -> None:
        """Reject unknown namespaces or unexpected root keys."""
        extra_key_root = {
            "schema_version": 1,
            "sequences": {"WORK": 0, "RECORDING": 0, "RELEASE": 0},
            "extra_field": "disallowed",
        }
        self.state_path.write_text(json.dumps(extra_key_root), encoding="utf-8")
        with self.assertRaises(SequenceStateError):
            IdentifierAllocator(LocalJsonSequenceStore(self.state_path)).allocate(EntityType.WORK)

        extra_namespace = {
            "schema_version": 1,
            "sequences": {"WORK": 0, "RECORDING": 0, "RELEASE": 0, "TRACK": 0},
        }
        self.state_path.write_text(json.dumps(extra_namespace), encoding="utf-8")
        with self.assertRaises(SequenceStateError):
            IdentifierAllocator(LocalJsonSequenceStore(self.state_path)).allocate(EntityType.WORK)

        missing_namespace = {
            "schema_version": 1,
            "sequences": {"WORK": 0, "RECORDING": 0},
        }
        self.state_path.write_text(json.dumps(missing_namespace), encoding="utf-8")
        with self.assertRaises(SequenceStateError):
            IdentifierAllocator(LocalJsonSequenceStore(self.state_path)).allocate(EntityType.WORK)

    # =========================================================================
    # J. READ-ONLY OPERATIONS
    # =========================================================================
    def test_read_only_operations(self) -> None:
        """peek_next and current_sequence must never advance or mutate state."""
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 0)
        self.assertEqual(self.allocator.peek_next(EntityType.WORK), "AST-WRK-000001")
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 0)
        self.assertEqual(self.allocator.peek_next(EntityType.WORK), "AST-WRK-000001")
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 0)

        # Even if the file did not exist initially, peek does not create state
        allocated = self.allocator.allocate(EntityType.WORK)
        self.assertEqual(allocated, "AST-WRK-000001")
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 1)
        self.assertEqual(self.allocator.peek_next(EntityType.WORK), "AST-WRK-000002")
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 1)

    # =========================================================================
    # K. CONCURRENT ALLOCATION
    # =========================================================================
    def test_concurrent_allocation_threads(self) -> None:
        """Threaded concurrent allocations must return unique, monotonic IDs with no misses."""
        num_threads = 8
        allocations_per_thread = 25
        total_expected = num_threads * allocations_per_thread

        def worker(entity_type: EntityType) -> list[str]:
            results = []
            for _ in range(allocations_per_thread):
                results.append(self.allocator.allocate(entity_type))
            return results

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, EntityType.WORK) for _ in range(num_threads)]
            all_allocated = []
            for f in concurrent.futures.as_completed(futures):
                all_allocated.extend(f.result())

        self.assertEqual(len(all_allocated), total_expected)
        self.assertEqual(len(set(all_allocated)), total_expected, "Duplicate IDs returned!")
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), total_expected)

        # Verify exact sequence set: AST-WRK-000001 through AST-WRK-000200
        expected_set = {f"AST-WRK-{i:06d}" for i in range(1, total_expected + 1)}
        self.assertEqual(set(all_allocated), expected_set)

    def test_concurrent_allocation_multiprocess(self) -> None:
        """Independent processes coordinating over the same store file."""
        worker_code = """
import sys
from pathlib import Path
from packages.catalog.identifiers import IdentifierAllocator, EntityType
from packages.catalog.sequence_store import LocalJsonSequenceStore

state_path = Path(sys.argv[1])
count = int(sys.argv[2])
store = LocalJsonSequenceStore(state_path)
allocator = IdentifierAllocator(store)
print('READY', flush=True)
sys.stdin.readline()
for _ in range(count):
    print(allocator.allocate(EntityType.WORK))
"""
        num_procs = 4
        per_proc = 20
        total_expected = num_procs * per_proc

        procs = []
        for _ in range(num_procs):
            p = subprocess.Popen(
                [sys.executable, "-c", worker_code, str(self.state_path), str(per_proc)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                cwd=str(Path(__file__).resolve().parent.parent),
            )
            procs.append(p)

        # Every child has constructed its own store before any first allocation.
        # A bounded future wait prevents a failed startup from hanging the suite.
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_procs) as executor:
                ready = [executor.submit(p.stdout.readline) for p in procs]
                try:
                    for result in ready:
                        self.assertEqual(result.result(timeout=30).strip(), 'READY')
                except BaseException:
                    for p in procs:
                        p.kill()
                    raise
            for p in procs:
                p.stdin.write('GO\n')
                p.stdin.flush()
        except BaseException:
            for p in procs:
                p.kill()
                p.communicate()
            raise

        all_ids = []
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, f"Worker process failed with stderr:\n{err}")
            for line in out.strip().splitlines():
                if line.strip():
                    all_ids.append(line.strip())

        self.assertEqual(len(all_ids), total_expected)
        self.assertEqual(len(set(all_ids)), total_expected, "Duplicate IDs returned across processes!")
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), total_expected)
        expected_set = {f"AST-WRK-{i:06d}" for i in range(1, total_expected + 1)}
        self.assertEqual(set(all_ids), expected_set)

    # =========================================================================
    # L. FAILED PERSISTENCE
    # =========================================================================
    def test_failed_persistence(self) -> None:
        """Simulate persistence failure; allocation reports error and state remains uncommitted."""
        # Initial allocation works
        self.assertEqual(self.allocator.allocate(EntityType.WORK), "AST-WRK-000001")
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 1)

        # Mock os.replace to simulate I/O or disk write failure during atomic commit
        with patch("os.replace", side_effect=OSError("Disk full simulation")):
            with self.assertRaises(SequencePersistenceError):
                self.allocator.allocate(EntityType.WORK)

        # State must remain committed at 1, NOT advanced to 2
        self.assertEqual(self.allocator.current_sequence(EntityType.WORK), 1)

        # Once condition resolves, next allocation resumes at 2
        self.assertEqual(self.allocator.allocate(EntityType.WORK), "AST-WRK-000002")

    # =========================================================================
    # M. PATH PORTABILITY
    # =========================================================================
    def test_path_portability(self) -> None:
        """Allocator works regardless of current working directory."""
        cwd_orig = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as other_dir:
                try:
                    os.chdir(other_dir)
                    # Ensure relative path resolution does not break when absolute path passed
                    store = LocalJsonSequenceStore(self.state_path)
                    allocator = IdentifierAllocator(store)
                    self.assertEqual(allocator.allocate(EntityType.RELEASE), "AST-REL-000001")
                    self.assertEqual(allocator.current_sequence(EntityType.RELEASE), 1)
                finally:
                    os.chdir(cwd_orig)
        finally:
            if os.getcwd() != cwd_orig:
                os.chdir(cwd_orig)

    # =========================================================================
    # ADVERSARIAL EDGE CASES
    # =========================================================================
    def test_strict_json_rejections(self) -> None:
        """Reject duplicate keys, NaN, Infinity, -Infinity in JSON state."""
        # Duplicate keys
        dup_json = '{"schema_version": 1, "sequences": {"WORK": 0, "RECORDING": 0, "RELEASE": 0}, "schema_version": 1}'
        self.state_path.write_text(dup_json, encoding="utf-8")
        store = LocalJsonSequenceStore(self.state_path)
        with self.assertRaises(SequenceStateError):
            store.get_sequence(EntityType.WORK)

        # NaN
        nan_json = '{"schema_version": 1, "sequences": {"WORK": NaN, "RECORDING": 0, "RELEASE": 0}}'
        self.state_path.write_text(nan_json, encoding="utf-8")
        with self.assertRaises(SequenceStateError):
            store.get_sequence(EntityType.WORK)

        # Infinity
        inf_json = '{"schema_version": 1, "sequences": {"WORK": Infinity, "RECORDING": 0, "RELEASE": 0}}'
        self.state_path.write_text(inf_json, encoding="utf-8")
        with self.assertRaises(SequenceStateError):
            store.get_sequence(EntityType.WORK)

    def test_format_and_parse_identifier(self) -> None:
        """Verify format_identifier and parse_identifier invariants."""
        # Formatting bounds
        with self.assertRaises(SequenceStateError):
            format_identifier(EntityType.WORK, 0)
        with self.assertRaises(SequenceStateError):
            format_identifier(EntityType.WORK, -1)
        with self.assertRaises(SequenceStateError):
            format_identifier(EntityType.WORK, 1000000)
        with self.assertRaises(SequenceStateError):
            format_identifier(EntityType.WORK, True)  # bool check

        # Parsing
        self.assertEqual(parse_identifier("AST-WRK-000001"), (EntityType.WORK, 1))
        self.assertEqual(parse_identifier("AST-REC-999999"), (EntityType.RECORDING, 999999))
        self.assertEqual(parse_identifier("AST-REL-000042"), (EntityType.RELEASE, 42))

        # Bad formats
        for bad_id in [
            "AST-000001",
            "AST-WRK-000000",  # zero not permitted in valid allocation range
            "AST-WRK-1000000",
            "AST-WRK-00001",
            "AST-WRK-0000001",
            "AST-WRK-ABCDEF",
            "ast-wrk-000001",
            "AST-XXX-000001",
            123,
            None,
        ]:
            with self.assertRaises(AllocatorError):
                parse_identifier(bad_id)  # type: ignore


if __name__ == "__main__":
    unittest.main()
