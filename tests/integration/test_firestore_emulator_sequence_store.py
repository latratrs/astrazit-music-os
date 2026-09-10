"""Integration tests for FirestoreSequenceStore against the official Firestore emulator.

SAFETY INVARIANTS:
1. NEVER connects to Google Cloud production.
2. Explicitly requires FIRESTORE_EMULATOR_HOST environment variable.
3. Automatically skipped if FIRESTORE_EMULATOR_HOST is not configured.
4. Uses an explicit test project and isolated namespace.
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import unittest
from typing import List

from packages.catalog.identifiers import (
    EntityType,
    IdentifierAllocator,
    MAX_SEQUENCE,
    SequenceExhaustedError,
    SequencePersistenceError,
    SequenceStateError,
    format_identifier,
    parse_identifier,
)

EMULATOR_HOST_ENV = "FIRESTORE_EMULATOR_HOST"


class TestFirestoreEmulatorSequenceStore(unittest.TestCase):
    """Integration tests running against the official Google Cloud Firestore emulator."""

    @classmethod
    def setUpClass(cls) -> None:
        host = os.environ.get(EMULATOR_HOST_ENV)
        if not host:
            raise unittest.SkipTest(
                f"Skipping Firestore emulator integration tests: {EMULATOR_HOST_ENV} is not set."
            )
        # Never allow this test to turn an environment typo into a production
        # connection.  The integration contract is a local emulator endpoint.
        match = re.fullmatch(r"(?:\[([^\]]+)\]|([^:]+)):(\d{1,5})", host.strip())
        if not match:
            raise unittest.SkipTest(
                f"Skipping Firestore emulator integration tests: invalid {EMULATOR_HOST_ENV} value."
            )
        hostname = (match.group(1) or match.group(2)).lower()
        port = int(match.group(3))
        if port > 65535 or hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise unittest.SkipTest(
                f"Skipping Firestore emulator integration tests: {EMULATOR_HOST_ENV} must target localhost."
            )
        try:
            from google.cloud import firestore
            from google.auth.credentials import AnonymousCredentials
        except ImportError:
            raise unittest.SkipTest("google-cloud-firestore is not installed")

        # Explicitly connect only to emulator with anonymous credentials
        cls.project = "astrazit-emulator-test"
        cls.client = firestore.Client(
            project=cls.project,
            credentials=AnonymousCredentials(),
        )

    def setUp(self) -> None:
        from packages.catalog.firestore_sequence_store import (
            COLLECTION_AUTHORITY,
            COLLECTION_LEDGER,
            COLLECTION_SEQUENCES,
            FirestoreSequenceStore,
        )
        # Clear emulator test collections before each test run
        for col_name in [COLLECTION_AUTHORITY, COLLECTION_SEQUENCES, COLLECTION_LEDGER]:
            coll = self.client.collection(col_name)
            for doc in coll.list_documents():
                doc.delete()

        self.store = FirestoreSequenceStore(client=self.client)

    def test_emulator_bootstrap_clean_and_duplicate(self) -> None:
        """Clean bootstrap succeeds once; second bootstrap fails closed with conflict."""
        from packages.catalog.firestore_sequence_store import (
            COLLECTION_AUTHORITY,
            COLLECTION_SEQUENCES,
            DOC_AUTHORITY_CURRENT,
            SequenceStoreConflictError,
        )
        self.store.bootstrap("emulator-auth-01")

        auth_snap = self.client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT).get()
        self.assertTrue(auth_snap.exists)
        self.assertEqual(auth_snap.to_dict()["authority_id"], "emulator-auth-01")
        self.assertEqual(auth_snap.to_dict()["state"], "ACTIVE")

        for ns in ["WORK", "RECORDING", "RELEASE"]:
            seq_snap = self.client.collection(COLLECTION_SEQUENCES).document(ns).get()
            self.assertTrue(seq_snap.exists)
            self.assertEqual(seq_snap.to_dict()["last_issued"], 0)

        # Duplicate bootstrap must fail closed
        with self.assertRaises(SequenceStoreConflictError):
            self.store.bootstrap("emulator-auth-02")

    def test_emulator_concurrent_bootstrap(self) -> None:
        """Two concurrent bootstrap callers: exactly one succeeds, the other fails."""
        from packages.catalog.firestore_sequence_store import SequenceStoreConflictError

        results = []
        errors = []

        def run_bootstrap(caller_id: str) -> None:
            try:
                from google.cloud import firestore
                from google.auth.credentials import AnonymousCredentials
                from packages.catalog.firestore_sequence_store import FirestoreSequenceStore
                worker_client = firestore.Client(
                    project=self.project,
                    credentials=AnonymousCredentials(),
                )
                store_instance = FirestoreSequenceStore(client=worker_client)
                store_instance.bootstrap(caller_id)
                results.append(caller_id)
            except SequenceStoreConflictError as err:
                errors.append(err)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(run_bootstrap, "caller-A"),
                executor.submit(run_bootstrap, "caller-B"),
            ]
            for future in futures:
                future.result()

        self.assertEqual(len(results), 1, f"Expected exactly 1 bootstrap success, got {results}")
        self.assertEqual(len(errors), 1, f"Expected exactly 1 conflict error, got {errors}")

    def test_emulator_allocation_independence_and_monotonicity(self) -> None:
        """WORK, RECORDING, and RELEASE start at 1 independently."""
        self.store.bootstrap("emulator-auth")
        allocator = IdentifierAllocator(self.store)

        id_w1 = allocator.allocate(EntityType.WORK)
        self.assertEqual(id_w1, "AST-WRK-000001")

        id_r1 = allocator.allocate(EntityType.RECORDING)
        self.assertEqual(id_r1, "AST-REC-000001")

        id_rel1 = allocator.allocate(EntityType.RELEASE)
        self.assertEqual(id_rel1, "AST-REL-000001")

        id_w2 = allocator.allocate(EntityType.WORK)
        self.assertEqual(id_w2, "AST-WRK-000002")

    def test_emulator_high_concurrency_allocation(self) -> None:
        """Concurrent callers allocate WORK without duplicates or lost increments."""
        from packages.catalog.firestore_sequence_store import COLLECTION_LEDGER, FirestoreSequenceStore

        self.store.bootstrap("emulator-concurrency-auth")
        allocator = IdentifierAllocator(self.store)

        # The bundled emulator has a short transaction lock timeout; five
        # independent clients still exercise real optimistic contention while
        # avoiding false failures caused solely by emulator saturation.
        num_callers = 5

        def allocate_one() -> str:
            from google.cloud import firestore
            from google.auth.credentials import AnonymousCredentials
            worker_client = firestore.Client(
                project=self.project,
                credentials=AnonymousCredentials(),
            )
            worker_store = FirestoreSequenceStore(client=worker_client)
            return IdentifierAllocator(worker_store).allocate(EntityType.WORK)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_callers) as executor:
            futures = [executor.submit(allocate_one) for _ in range(num_callers)]
            ids = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(ids), num_callers)
        self.assertEqual(len(set(ids)), num_callers)

        numbers = sorted([parse_identifier(i)[1] for i in ids])
        self.assertEqual(numbers, list(range(1, num_callers + 1)))

        # Ledger entries
        ledger_docs = list(self.client.collection(COLLECTION_LEDGER).list_documents())
        self.assertEqual(len(ledger_docs), num_callers)

    def test_emulator_ledger_immutability(self) -> None:
        """Ledger document cannot be overwritten through normal allocation collision."""
        from packages.catalog.firestore_sequence_store import (
            COLLECTION_LEDGER,
            COLLECTION_SEQUENCES,
            SequenceStoreConflictError,
        )
        self.store.bootstrap("emulator-auth")
        allocator = IdentifierAllocator(self.store)

        id1 = allocator.allocate(EntityType.WORK)
        self.assertEqual(id1, "AST-WRK-000001")

        # Roll back sequence counter to 0 directly in Firestore
        self.client.collection(COLLECTION_SEQUENCES).document("WORK").update({"last_issued": 0})

        # Next allocation attempts 1, but WORK-000001 already exists in ledger!
        with self.assertRaises(SequenceStoreConflictError):
            allocator.allocate(EntityType.WORK)


if __name__ == "__main__":
    unittest.main()
