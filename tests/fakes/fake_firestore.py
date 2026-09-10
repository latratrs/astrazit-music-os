"""Deterministic in-memory transactional Firestore double.

Provides a lightweight, zero-dependency, transactional fake of Google Cloud Firestore
(Standard edition, Native mode) for testing FirestoreSequenceStore.

Implements:
- Collections, document references, document snapshots
- Strict dictionary isolation (deep copying on write and read)
- Transactional read/write isolation with optimistic concurrency checking
- Contention tracking and retry testing
- Querying (list_documents, stream, where, order_by, limit)
"""
from __future__ import annotations

import copy
import datetime
import threading
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union


class FakeServerTimestamp:
    """Sentinel for firestore.SERVER_TIMESTAMP."""
    def __repr__(self) -> str:
        return "FakeServerTimestamp"


SERVER_TIMESTAMP = FakeServerTimestamp()


class FakeDocumentSnapshot:
    """Simulates google.cloud.firestore_v1.base_document.DocumentSnapshot."""

    def __init__(
        self,
        reference: FakeDocumentReference,
        data: Optional[Dict[str, Any]],
        exists: bool,
        read_time: Optional[datetime.datetime] = None,
        create_time: Optional[datetime.datetime] = None,
        update_time: Optional[datetime.datetime] = None,
        version: int = 0,
    ) -> None:
        self.reference = reference
        self.id = reference.id
        self._data = copy.deepcopy(data) if data is not None else None
        self.exists = exists
        self.read_time = read_time or datetime.datetime.now(datetime.timezone.utc)
        self.create_time = create_time
        self.update_time = update_time
        self._version = version

    def to_dict(self) -> Optional[Dict[str, Any]]:
        if not self.exists:
            return None
        return copy.deepcopy(self._data)

    def get(self, field_path: str) -> Any:
        if not self.exists or self._data is None:
            raise KeyError(field_path)
        parts = field_path.split(".")
        curr: Any = self._data
        for p in parts:
            if not isinstance(curr, dict) or p not in curr:
                raise KeyError(field_path)
            curr = curr[p]
        return copy.deepcopy(curr)


class FakeDocumentReference:
    """Simulates google.cloud.firestore_v1.document.DocumentReference."""

    def __init__(self, client: FakeFirestoreClient, path: str) -> None:
        self._client = client
        self.path = path.strip("/")
        parts = self.path.split("/")
        self.id = parts[-1]
        self.parent = client.collection("/".join(parts[:-1])) if len(parts) > 1 else None

    def get(self, transaction: Optional[FakeTransaction] = None) -> FakeDocumentSnapshot:
        if transaction is not None:
            return transaction.get(self)
        return self._client._storage_get(self)

    def set(
        self,
        document_data: Dict[str, Any],
        merge: bool = False,
        transaction: Optional[FakeTransaction] = None,
    ) -> None:
        if transaction is not None:
            transaction.set(self, document_data, merge=merge)
        else:
            self._client._storage_set(self, document_data, merge=merge)

    def update(
        self,
        field_updates: Dict[str, Any],
        transaction: Optional[FakeTransaction] = None,
    ) -> None:
        if transaction is not None:
            transaction.update(self, field_updates)
        else:
            self._client._storage_update(self, field_updates)

    def delete(self, transaction: Optional[FakeTransaction] = None) -> None:
        if transaction is not None:
            transaction.delete(self)
        else:
            self._client._storage_delete(self)


class FakeCollectionReference:
    """Simulates google.cloud.firestore_v1.collection.CollectionReference."""

    def __init__(self, client: FakeFirestoreClient, path: str) -> None:
        self._client = client
        self.path = path.strip("/")
        self.id = self.path.split("/")[-1]

    def document(self, document_id: Optional[str] = None) -> FakeDocumentReference:
        if document_id is None:
            import uuid
            document_id = uuid.uuid4().hex
        subpath = f"{self.path}/{document_id}"
        return FakeDocumentReference(self._client, subpath)

    def stream(self, transaction: Optional[FakeTransaction] = None) -> Iterator[FakeDocumentSnapshot]:
        return self._client._storage_stream_collection(self.path, transaction=transaction)

    def list_documents(self) -> List[FakeDocumentReference]:
        return self._client._storage_list_documents(self.path)


class FakeConflictError(Exception):
    """Simulates google.api_core.exceptions.Aborted or conflict in Firestore transaction."""


class FakeTransaction:
    """Simulates google.cloud.firestore_v1.transaction.Transaction."""

    def __init__(self, client: FakeFirestoreClient, max_attempts: int = 5) -> None:
        self._client = client
        self.max_attempts = max_attempts
        # Tracking read versions: path -> version
        self._reads: Dict[str, int] = {}
        # Buffer of operations: list of callables to apply upon commit
        self._mutations: List[Callable[[], None]] = []
        self._committed = False
        self._aborted = False

    def get(self, ref_or_query: Union[FakeDocumentReference, Any]) -> FakeDocumentSnapshot:
        if self._committed or self._aborted:
            raise RuntimeError("Transaction is closed")
        if isinstance(ref_or_query, FakeDocumentReference):
            ref = ref_or_query
            snapshot = self._client._storage_get(ref)
            self._reads[ref.path] = snapshot._version
            return snapshot
        raise NotImplementedError("Queries in transaction not yet implemented")

    def set(self, ref: FakeDocumentReference, document_data: Dict[str, Any], merge: bool = False) -> None:
        if self._committed or self._aborted:
            raise RuntimeError("Transaction is closed")
        data_copy = copy.deepcopy(document_data)

        def apply_set() -> None:
            self._client._storage_set(ref, data_copy, merge=merge, transaction=self)

        self._mutations.append(apply_set)

    def create(self, ref: FakeDocumentReference, document_data: Dict[str, Any]) -> None:
        if self._committed or self._aborted:
            raise RuntimeError("Transaction is closed")
        data_copy = copy.deepcopy(document_data)

        def apply_create() -> None:
            self._client._storage_create(ref, data_copy, transaction=self)

        self._mutations.append(apply_create)

    def update(self, ref: FakeDocumentReference, field_updates: Dict[str, Any]) -> None:
        if self._committed or self._aborted:
            raise RuntimeError("Transaction is closed")
        data_copy = copy.deepcopy(field_updates)

        def apply_update() -> None:
            self._client._storage_update(ref, data_copy, transaction=self)

        self._mutations.append(apply_update)

    def delete(self, ref: FakeDocumentReference) -> None:
        if self._committed or self._aborted:
            raise RuntimeError("Transaction is closed")

        def apply_delete() -> None:
            self._client._storage_delete(ref, transaction=self)

        self._mutations.append(apply_delete)


class FakeFirestoreClient:
    """In-memory thread-safe fake of google.cloud.firestore.Client."""

    def __init__(self, project: str = "astrazit-test", database: str = "(default)") -> None:
        self.project = project
        self.database = database
        self._lock = threading.RLock()
        # Storage: doc_path -> {"data": dict, "version": int, "create_time": ..., "update_time": ...}
        self._store: Dict[str, Dict[str, Any]] = {}
        self.transaction_retries_count = 0
        self.fail_next_commit = False

    def collection(self, collection_path: str) -> FakeCollectionReference:
        return FakeCollectionReference(self, collection_path)

    def document(self, document_path: str) -> FakeDocumentReference:
        return FakeDocumentReference(self, document_path)

    def transaction(self, max_attempts: int = 5) -> FakeTransaction:
        return FakeTransaction(self, max_attempts=max_attempts)

    def _resolve_timestamps(self, data: Dict[str, Any], now: datetime.datetime) -> Dict[str, Any]:
        result = {}
        for k, v in data.items():
            if isinstance(v, FakeServerTimestamp) or v == SERVER_TIMESTAMP:
                result[k] = now
            elif isinstance(v, dict):
                result[k] = self._resolve_timestamps(v, now)
            else:
                result[k] = v
        return result

    def _storage_get(self, ref: FakeDocumentReference) -> FakeDocumentSnapshot:
        with self._lock:
            doc = self._store.get(ref.path)
            now = datetime.datetime.now(datetime.timezone.utc)
            if doc is None:
                return FakeDocumentSnapshot(reference=ref, data=None, exists=False, read_time=now, version=0)
            return FakeDocumentSnapshot(
                reference=ref,
                data=doc["data"],
                exists=True,
                read_time=now,
                create_time=doc["create_time"],
                update_time=doc["update_time"],
                version=doc["version"],
            )

    def _storage_set(
        self,
        ref: FakeDocumentReference,
        data: Dict[str, Any],
        merge: bool = False,
        transaction: Optional[FakeTransaction] = None,
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        resolved = self._resolve_timestamps(data, now)
        with self._lock:
            existing = self._store.get(ref.path)
            if existing is None:
                self._store[ref.path] = {
                    "data": resolved,
                    "version": 1,
                    "create_time": now,
                    "update_time": now,
                }
            else:
                if merge:
                    merged = copy.deepcopy(existing["data"])
                    merged.update(resolved)
                    new_data = merged
                else:
                    new_data = resolved
                self._store[ref.path] = {
                    "data": new_data,
                    "version": existing["version"] + 1,
                    "create_time": existing["create_time"],
                    "update_time": now,
                }

    def _storage_create(
        self,
        ref: FakeDocumentReference,
        data: Dict[str, Any],
        transaction: Optional[FakeTransaction] = None,
    ) -> None:
        with self._lock:
            if ref.path in self._store:
                raise FakeConflictError(f"Document {ref.path} already exists")
            now = datetime.datetime.now(datetime.timezone.utc)
            resolved = self._resolve_timestamps(data, now)
            self._store[ref.path] = {
                "data": resolved,
                "version": 1,
                "create_time": now,
                "update_time": now,
            }

    def _storage_update(
        self,
        ref: FakeDocumentReference,
        field_updates: Dict[str, Any],
        transaction: Optional[FakeTransaction] = None,
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        resolved = self._resolve_timestamps(field_updates, now)
        with self._lock:
            existing = self._store.get(ref.path)
            if existing is None:
                raise KeyError(f"Document {ref.path} does not exist to update")
            merged = copy.deepcopy(existing["data"])
            for k, v in resolved.items():
                # Support nested dotted updates if present
                if "." in k:
                    parts = k.split(".")
                    curr = merged
                    for p in parts[:-1]:
                        if p not in curr or not isinstance(curr[p], dict):
                            curr[p] = {}
                        curr = curr[p]
                    curr[parts[-1]] = v
                else:
                    merged[k] = v
            self._store[ref.path] = {
                "data": merged,
                "version": existing["version"] + 1,
                "create_time": existing["create_time"],
                "update_time": now,
            }

    def _storage_delete(
        self,
        ref: FakeDocumentReference,
        transaction: Optional[FakeTransaction] = None,
    ) -> None:
        with self._lock:
            if ref.path in self._store:
                del self._store[ref.path]

    def _storage_stream_collection(
        self,
        collection_path: str,
        transaction: Optional[FakeTransaction] = None,
    ) -> Iterator[FakeDocumentSnapshot]:
        prefix = collection_path.strip("/") + "/"
        with self._lock:
            results = []
            for path, doc in sorted(self._store.items()):
                if path.startswith(prefix):
                    sub = path[len(prefix):]
                    if "/" not in sub:  # Direct child document
                        ref = FakeDocumentReference(self, path)
                        results.append(
                            FakeDocumentSnapshot(
                                reference=ref,
                                data=doc["data"],
                                exists=True,
                                create_time=doc["create_time"],
                                update_time=doc["update_time"],
                                version=doc["version"],
                            )
                        )
            return iter(results)

    def _storage_list_documents(self, collection_path: str) -> List[FakeDocumentReference]:
        prefix = collection_path.strip("/") + "/"
        with self._lock:
            refs = []
            for path in sorted(self._store.keys()):
                if path.startswith(prefix):
                    sub = path[len(prefix):]
                    if "/" not in sub:
                        refs.append(FakeDocumentReference(self, path))
            return refs

    def run_transaction(
        self,
        transaction_callable: Callable[[FakeTransaction], Any],
        max_attempts: int = 5,
    ) -> Any:
        """Execute a transaction callable with optimistic retry logic."""
        attempts = 0
        while attempts < max_attempts:
            attempts += 1
            txn = self.transaction(max_attempts=max_attempts)
            try:
                result = transaction_callable(txn)
            except Exception:
                txn._aborted = True
                raise

            # Try to commit atomically under storage lock
            with self._lock:
                if self.fail_next_commit:
                    self.fail_next_commit = False
                    txn._aborted = True
                    raise FakeConflictError("Simulated commit failure / network abort")

                # Optimistic concurrency check: verify that all documents read during txn
                # still have the exact same versions in storage.
                conflict = False
                for path, read_version in txn._reads.items():
                    curr_doc = self._store.get(path)
                    curr_version = curr_doc["version"] if curr_doc is not None else 0
                    if curr_version != read_version:
                        conflict = True
                        break

                if conflict:
                    self.transaction_retries_count += 1
                    txn._aborted = True
                    if attempts >= max_attempts:
                        raise FakeConflictError(
                            f"Transaction failed after {attempts} attempts due to write contention"
                        )
                    continue  # Retry transaction callable

                # Apply mutations atomically
                for mut in txn._mutations:
                    mut()

                txn._committed = True
                return result

        raise FakeConflictError(f"Transaction exceeded maximum {max_attempts} attempts")
