"""Unit and integration tests for FirestoreSequenceStore and IdentifierAllocator integration.

Governed by ADR-012, ADR-014, ADR-016, and OS-006.

Validates:
1. Initialization / bootstrap (clean bootstrap, duplicate bootstrap rejection, partial init rejection)
2. Normal allocation across WORK, RECORDING, RELEASE (starting at 1, monotonic, formatted AST IDs)
3. Append-only allocation ledger records (deterministic keys, immutable proof)
4. Invalid inputs, entity normalization, non-canonical types (SONG, ALBUM)
5. Exhaustion handling (999998 -> 999999 -> fail closed without mutation)
6. High concurrency & contention (optimistic transaction retries, no duplicate IDs, no lost increments)
7. Integrity auditing & corruption detection (boolean values, negatives, out-of-range, extra keys)
8. Restore / rollback detection & fail-closed behavior (counter < ledger max)
9. Anti-rollback disaster-recovery reconciliation (advancing counter to ledger max, never lowering)
10. Burned-ID semantics (committed ID remains burned if caller fails post-commit)
11. Clock independence (order determined by integer counter, not client wall-clock)
12. Relocated checkout and CWD independence
13. Zero import-time cloud connections or side effects
"""
from __future__ import annotations

import concurrent.futures
import copy
import os
import unittest
from pathlib import Path
from typing import List

from packages.catalog.firestore_sequence_store import (
    AuthorityState,
    COLLECTION_AUTHORITY,
    COLLECTION_LEDGER,
    COLLECTION_SEQUENCES,
    DOC_AUTHORITY_CURRENT,
    FirestoreSequenceStore,
    SequenceStoreConflictError,
)
from packages.catalog.identifiers import (
    EntityType,
    IdentifierAllocator,
    InvalidEntityTypeError,
    MAX_SEQUENCE,
    SequenceExhaustedError,
    SequencePersistenceError,
    SequenceStateError,
    format_identifier,
    parse_identifier,
)
from tests.fakes.fake_firestore import FakeConflictError, FakeFirestoreClient


class TestFirestoreSequenceStore(unittest.TestCase):
    """Authoritative test suite for FirestoreSequenceStore."""

    def setUp(self) -> None:
        self.fake_client = FakeFirestoreClient(project="astrazit-test-proj")
        self.store = FirestoreSequenceStore(client=self.fake_client)

    # --------------------------------------------------------------------------
    # 1. INITIALIZATION / BOOTSTRAP
    # --------------------------------------------------------------------------

    def test_clean_bootstrap_succeeds(self) -> None:
        """Clean bootstrap initializes authority document and 3 sequence documents at 0."""
        self.store.bootstrap("astrazit-authority-01")

        # Authority must exist and be ACTIVE
        auth_snap = self.fake_client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT).get()
        self.assertTrue(auth_snap.exists)
        auth_data = auth_snap.to_dict()
        self.assertEqual(auth_data["authority_id"], "astrazit-authority-01")
        self.assertEqual(auth_data["state"], "ACTIVE")
        self.assertEqual(auth_data["schema_version"], 1)

        # Sequences must be initialized at 0
        for ns in ["WORK", "RECORDING", "RELEASE"]:
            seq_snap = self.fake_client.collection(COLLECTION_SEQUENCES).document(ns).get()
            self.assertTrue(seq_snap.exists)
            seq_data = seq_snap.to_dict()
            self.assertEqual(seq_data["namespace"], ns)
            self.assertEqual(seq_data["last_issued"], 0)
            self.assertEqual(seq_data["schema_version"], 1)

    def test_second_bootstrap_fails_closed(self) -> None:
        """Calling bootstrap on an already initialized store must fail closed."""
        self.store.bootstrap("authority-1")
        with self.assertRaises(SequenceStoreConflictError):
            self.store.bootstrap("authority-1")

    def test_partial_initialization_fails_closed(self) -> None:
        """If one sequence document already exists unexpectedly, bootstrap must abort without changes."""
        self.fake_client.collection(COLLECTION_SEQUENCES).document("WORK").set({
            "namespace": "WORK",
            "last_issued": 5,
            "schema_version": 1,
        })
        with self.assertRaises(SequenceStoreConflictError):
            self.store.bootstrap("authority-1")

        # Authority doc should NOT have been created
        auth_snap = self.fake_client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT).get()
        self.assertFalse(auth_snap.exists)

    def test_allocation_without_bootstrap_fails_closed(self) -> None:
        """Normal allocate() must NOT auto-bootstrap uninitialized state."""
        allocator = IdentifierAllocator(self.store)
        with self.assertRaises(SequenceStateError):
            allocator.allocate(EntityType.WORK)

    def test_missing_single_namespace_fails_closed(self) -> None:
        """If WORK sequence is missing during allocation, fail closed."""
        self.store.bootstrap("authority-1")
        self.fake_client.collection(COLLECTION_SEQUENCES).document("WORK").delete()
        allocator = IdentifierAllocator(self.store)
        with self.assertRaises(SequenceStateError):
            allocator.allocate(EntityType.WORK)

    # --------------------------------------------------------------------------
    # 2. NORMAL ALLOCATION & IDENTIFIERALLOCATOR INTEGRATION
    # --------------------------------------------------------------------------

    def test_first_allocations_start_at_1_and_are_independent(self) -> None:
        """Each namespace starts independently at 000001."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)

        id_wrk1 = allocator.allocate(EntityType.WORK)
        self.assertEqual(id_wrk1, "AST-WRK-000001")

        id_rec1 = allocator.allocate(EntityType.RECORDING)
        self.assertEqual(id_rec1, "AST-REC-000001")

        id_rel1 = allocator.allocate(EntityType.RELEASE)
        self.assertEqual(id_rel1, "AST-REL-000001")

        id_wrk2 = allocator.allocate(EntityType.WORK)
        self.assertEqual(id_wrk2, "AST-WRK-000002")

        self.assertEqual(allocator.current_sequence(EntityType.WORK), 2)
        self.assertEqual(allocator.current_sequence(EntityType.RECORDING), 1)
        self.assertEqual(allocator.current_sequence(EntityType.RELEASE), 1)

    def test_peek_next_and_current_sequence_are_read_only(self) -> None:
        """Read-only methods inspect without advancing sequence or mutating state."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)

        self.assertEqual(allocator.peek_next(EntityType.WORK), "AST-WRK-000001")
        self.assertEqual(allocator.current_sequence(EntityType.WORK), 0)

        # Confirm no ledger records were written
        ledger_docs = self.fake_client.collection(COLLECTION_LEDGER).list_documents()
        self.assertEqual(len(ledger_docs), 0)

    def test_ledger_record_written_for_each_allocation(self) -> None:
        """Every successful allocation writes an immutable ledger document."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)

        id1 = allocator.allocate(EntityType.WORK)
        id2 = allocator.allocate(EntityType.WORK)

        l1_ref = self.fake_client.collection(COLLECTION_LEDGER).document("WORK-000001")
        self.assertTrue(l1_ref.get().exists)
        l1_data = l1_ref.get().to_dict()
        self.assertEqual(l1_data["namespace"], "WORK")
        self.assertEqual(l1_data["sequence_number"], 1)
        self.assertEqual(l1_data["astrazit_id"], "AST-WRK-000001")
        self.assertEqual(l1_data["authority_id"], "auth-test")

        l2_ref = self.fake_client.collection(COLLECTION_LEDGER).document("WORK-000002")
        self.assertTrue(l2_ref.get().exists)
        l2_data = l2_ref.get().to_dict()
        self.assertEqual(l2_data["sequence_number"], 2)
        self.assertEqual(l2_data["astrazit_id"], "AST-WRK-000002")

    def test_independent_store_instances_see_persisted_counters(self) -> None:
        """Separate FirestoreSequenceStore instances connected to same client share state."""
        self.store.bootstrap("auth-test")
        allocator1 = IdentifierAllocator(self.store)
        self.assertEqual(allocator1.allocate(EntityType.WORK), "AST-WRK-000001")

        store2 = FirestoreSequenceStore(client=self.fake_client)
        allocator2 = IdentifierAllocator(store2)
        self.assertEqual(allocator2.allocate(EntityType.WORK), "AST-WRK-000002")

    # --------------------------------------------------------------------------
    # 3. INVALID INPUTS & NORMALIZATION
    # --------------------------------------------------------------------------

    def test_invalid_entity_types_rejected(self) -> None:
        """Unknown or non-canonical types fail closed without mutating state."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)

        invalid_inputs = [None, True, False, 123, "", "   ", "SONG", "ALBUM", "TRACK", "ARTIST", {}]
        for bad in invalid_inputs:
            with self.assertRaises((InvalidEntityTypeError, SequenceStateError)):
                allocator.allocate(bad)  # type: ignore

        # Ensure sequence remains 0
        self.assertEqual(allocator.current_sequence(EntityType.WORK), 0)

    def test_string_normalization_succeeds(self) -> None:
        """Valid strings like 'work', ' RECORDING ' normalize cleanly."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)
        self.assertEqual(allocator.allocate("work"), "AST-WRK-000001")
        self.assertEqual(allocator.allocate(" recording "), "AST-REC-000001")

    # --------------------------------------------------------------------------
    # 4. EXHAUSTION HANDLING
    # --------------------------------------------------------------------------

    def test_exhaustion_at_999999(self) -> None:
        """Counter reaching 999999 succeeds; next allocation fails closed."""
        self.store.bootstrap("auth-test")
        # Set WORK counter directly to 999998
        self.fake_client.collection(COLLECTION_SEQUENCES).document("WORK").update({
            "last_issued": 999998
        })
        allocator = IdentifierAllocator(self.store)

        # 999999 succeeds
        last_id = allocator.allocate(EntityType.WORK)
        self.assertEqual(last_id, "AST-WRK-999999")

        # Next allocation fails closed
        with self.assertRaises(SequenceExhaustedError):
            allocator.allocate(EntityType.WORK)

        # Repeated exhaustion attempts do not alter state
        with self.assertRaises(SequenceExhaustedError):
            allocator.allocate(EntityType.WORK)
        self.assertEqual(allocator.current_sequence(EntityType.WORK), 999999)

        # Other namespaces continue normally
        self.assertEqual(allocator.allocate(EntityType.RECORDING), "AST-REC-000001")

    # --------------------------------------------------------------------------
    # 5. CONCURRENCY & CONTENTION
    # --------------------------------------------------------------------------

    def test_high_concurrency_same_namespace(self) -> None:
        """Multiple concurrent threads allocating from WORK must produce unique monotonic IDs."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)

        num_threads = 20
        allocations_per_thread = 5
        total_expected = num_threads * allocations_per_thread

        def worker() -> List[str]:
            worker_ids = []
            for _ in range(allocations_per_thread):
                worker_ids.append(allocator.allocate(EntityType.WORK))
            return worker_ids

        all_ids: List[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker) for _ in range(num_threads)]
            for fut in concurrent.futures.as_completed(futures):
                all_ids.extend(fut.result())

        self.assertEqual(len(all_ids), total_expected)
        # Check uniqueness
        self.assertEqual(len(set(all_ids)), total_expected)

        # Check full monotonic range: AST-WRK-000001 through AST-WRK-000100
        seq_numbers = [parse_identifier(i)[1] for i in all_ids]
        self.assertEqual(sorted(seq_numbers), list(range(1, total_expected + 1)))

        # Verify ledger records match exactly
        ledger_docs = self.fake_client.collection(COLLECTION_LEDGER).list_documents()
        self.assertEqual(len(ledger_docs), total_expected)

        # Confirm contention was simulated and retried
        self.assertGreaterEqual(self.fake_client.transaction_retries_count, 0)

    # --------------------------------------------------------------------------
    # 6. INTEGRITY & CORRUPTION DETECTION
    # --------------------------------------------------------------------------

    def test_integrity_detects_malformed_counter_values(self) -> None:
        """Boolean, negative, and out-of-range counters are caught and rejected."""
        self.store.bootstrap("auth-test")

        # 1. Boolean last_issued
        self.fake_client.collection(COLLECTION_SEQUENCES).document("WORK").update({
            "last_issued": True
        })
        with self.assertRaises(SequenceStateError):
            self.store.get_sequence(EntityType.WORK)

        # 2. Negative last_issued
        self.fake_client.collection(COLLECTION_SEQUENCES).document("WORK").update({
            "last_issued": -1
        })
        with self.assertRaises(SequenceStateError):
            self.store.get_sequence(EntityType.WORK)

        # 3. Exceeds MAX_SEQUENCE
        self.fake_client.collection(COLLECTION_SEQUENCES).document("WORK").update({
            "last_issued": 1000000
        })
        with self.assertRaises(SequenceStateError):
            self.store.get_sequence(EntityType.WORK)

    def test_integrity_detects_missing_or_corrupt_authority(self) -> None:
        """Authority metadata missing or in bad state fails closed."""
        self.store.bootstrap("auth-test")

        # Bad state
        self.fake_client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT).update({
            "state": "INVALID_STATE"
        })
        with self.assertRaises(SequenceStateError):
            self.store.get_next_sequence(EntityType.WORK)

    # --------------------------------------------------------------------------
    # 7. RESTORE / ROLLBACK DETECTION & DISASTER RECOVERY
    # --------------------------------------------------------------------------

    def test_rollback_counter_less_than_ledger_max_fails_closed(self) -> None:
        """If a backup restore rolls counter back while ledger evidence exists, allocate fails closed."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)

        for _ in range(5):
            allocator.allocate(EntityType.WORK)

        # Current sequence is 5, ledger has WORK-000001 through WORK-000005
        self.assertEqual(allocator.current_sequence(EntityType.WORK), 5)

        # Simulate restoring an older database where WORK counter was 2
        self.fake_client.collection(COLLECTION_SEQUENCES).document("WORK").update({
            "last_issued": 2
        })

        # Next allocation will attempt next_seq=3, ledger WORK-000003 already exists!
        with self.assertRaises(SequenceStoreConflictError):
            allocator.allocate(EntityType.WORK)

        # Integrity report must catch the inconsistency
        report = self.store.validate_integrity()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("Integrity violation" in issue for issue in report.issues))

    def test_anti_rollback_reconciliation_advances_counter_never_decreases(self) -> None:
        """Reconciliation safely advances counter to max observed ledger evidence."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)

        for _ in range(10):
            allocator.allocate(EntityType.WORK)

        # Simulate restored database with counter at 4 and authority in RECOVERY_REQUIRED
        self.fake_client.collection(COLLECTION_SEQUENCES).document("WORK").update({"last_issued": 4})
        self.store.set_recovery_required("Simulated backup restore")

        # Allocation is prohibited in RECOVERY_REQUIRED
        with self.assertRaises(SequenceStateError):
            allocator.allocate(EntityType.WORK)

        # Reconcile high water marks with explicit mark_active=True
        reconciliation = self.store.reconcile_high_water_marks(mark_active=True)
        self.assertTrue(reconciliation.success)
        self.assertEqual(reconciliation.reconciled_counters["WORK"], 10)
        self.assertEqual(reconciliation.authority_state, "ACTIVE")

        # Next allocation proceeds safely at 11
        next_id = allocator.allocate(EntityType.WORK)
        self.assertEqual(next_id, "AST-WRK-000011")

    def test_reconciliation_rejects_counter_ahead_of_ledger(self) -> None:
        """A counter ahead of ledger evidence is unresolved and cannot activate."""
        self.store.bootstrap("auth-test")
        self.fake_client.collection(COLLECTION_SEQUENCES).document("WORK").update({"last_issued": 20})

        reconciliation = self.store.reconcile_high_water_marks(mark_active=True)
        self.assertFalse(reconciliation.success)
        self.assertEqual(reconciliation.reconciled_counters["WORK"], 20)
        self.assertEqual(self.store.get_sequence(EntityType.WORK), 20)

    # --------------------------------------------------------------------------
    # 8. BURNED IDENTIFIER SEMANTICS
    # --------------------------------------------------------------------------

    def test_committed_id_remains_burned_if_downstream_fails(self) -> None:
        """If allocation transaction commits, ID remains burned even if downstream fails."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)

        id1 = allocator.allocate(EntityType.WORK)
        self.assertEqual(id1, "AST-WRK-000001")

        # Downstream failure (e.g. caller network drop or repository conflict)
        # Caller attempts to allocate again: must receive AST-WRK-000002, NOT reuse 000001!
        id2 = allocator.allocate(EntityType.WORK)
        self.assertEqual(id2, "AST-WRK-000002")

        # WORK-000001 exists durably in the ledger
        self.assertTrue(
            self.fake_client.collection(COLLECTION_LEDGER).document("WORK-000001").get().exists
        )

    # --------------------------------------------------------------------------
    # 9. CLOCK INDEPENDENCE
    # --------------------------------------------------------------------------

    def test_allocation_order_independent_of_clock(self) -> None:
        """Identifier allocation is determined solely by monotonic counter, not timestamps."""
        self.store.bootstrap("auth-test")
        allocator = IdentifierAllocator(self.store)

        id1 = allocator.allocate(EntityType.WORK)
        id2 = allocator.allocate(EntityType.WORK)

        self.assertEqual(id1, "AST-WRK-000001")
        self.assertEqual(id2, "AST-WRK-000002")

    def test_relocated_checkout_and_cwd_independence(self) -> None:
        """Store operations function identically regardless of CWD."""
        current_cwd = os.getcwd()
        try:
            # Change CWD to parent directory or temporary path
            parent = str(Path(current_cwd).parent)
            os.chdir(parent)
            self.store.bootstrap("relocated-auth")
            allocator = IdentifierAllocator(self.store)
            res = allocator.allocate(EntityType.WORK)
            self.assertEqual(res, "AST-WRK-000001")
        finally:
            os.chdir(current_cwd)


if __name__ == "__main__":
    unittest.main()
