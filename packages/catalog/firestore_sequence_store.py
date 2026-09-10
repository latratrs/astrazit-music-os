"""Google Cloud Firestore implementation of SequenceStore.

Governed by ADR-012, ADR-014, ADR-016, and OS-006.

Authoritative production identifier allocation backend:
- Google Cloud Firestore (Standard edition, Native mode)
- Exact three namespaces: WORK, RECORDING, RELEASE
- Range: 000001 to 999999
- Atomic increment + append-only allocation ledger in a single transaction
- Explicit authority state model: INITIALIZING, ACTIVE, RECOVERY_REQUIRED
- Anti-rollback disaster-recovery reconciliation gate
- Zero import-time Google Cloud connections or side effects
"""
from __future__ import annotations

import enum
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Union

from packages.catalog.identifiers import (
    ENTITY_PREFIXES,
    EntityType,
    MAX_SEQUENCE,
    MIN_SEQUENCE,
    SEQUENCE_DIGITS,
    SequenceExhaustedError,
    SequencePersistenceError,
    SequenceStateError,
    format_identifier,
)
from packages.catalog.sequence_store import SequenceStore

# Canonical collection names
COLLECTION_SEQUENCES = "astrazit_id_sequences"
COLLECTION_LEDGER = "astrazit_id_allocations"
COLLECTION_AUTHORITY = "astrazit_id_authority"
DOC_AUTHORITY_CURRENT = "current"

SCHEMA_VERSION = 1
REQUIRED_NAMESPACES = {e.value for e in EntityType}


class AuthorityState(enum.Enum):
    """Authority state machine lifecycle for production identifier allocation."""
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

    @classmethod
    def from_value(cls, val: Any) -> AuthorityState:
        if isinstance(val, cls):
            return val
        if isinstance(val, str):
            try:
                return cls[val.strip().upper()]
            except KeyError:
                raise SequenceStateError(f"Unknown authority state: {val!r}")
        raise SequenceStateError(f"Invalid authority state type: {type(val).__name__}")


class SequenceStoreConflictError(SequencePersistenceError):
    """Raised when an allocation or bootstrap encounters a state conflict or contention."""


class IntegrityReport(NamedTuple):
    """Result of an authoritative integrity inspection."""
    is_valid: bool
    authority_state: str
    counters: Dict[str, int]
    ledger_maxes: Dict[str, int]
    ledger_counts: Dict[str, int]
    issues: List[str]


class ReconciliationReport(NamedTuple):
    """Result of an anti-rollback reconciliation operation."""
    success: bool
    previous_counters: Dict[str, int]
    reconciled_counters: Dict[str, int]
    authority_state: str
    audit_notes: List[str]


def _format_ledger_key(namespace: str, seq: int) -> str:
    """Format deterministic document key for allocation ledger: e.g. 'WORK-000042'."""
    return f"{namespace}-{seq:0{SEQUENCE_DIGITS}d}"


class FirestoreSequenceStore(SequenceStore):
    """Production SequenceStore backed by Google Cloud Firestore.

    Ensures serializable atomic allocation via Firestore transactions, append-only
    durable ledger records, fail-closed corruption detection, and explicit recovery
    states to prevent identifier reuse upon backup restore.
    """

    def __init__(
        self,
        client: Optional[Any] = None,
        project: Optional[str] = None,
        database: Optional[str] = None,
        client_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Initialize FirestoreSequenceStore.

        Accepts an injected Firestore client, client factory, or project/database config.
        Does NOT perform any network calls, authentication, or collection creation
        at construction time.
        """
        self._client = client
        self._client_factory = client_factory
        self._project = project
        self._database = database

    def _get_client(self) -> Any:
        """Lazily resolve Firestore client without import-time side effects."""
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory()
            return self._client

        # Dynamic lazy import of official google.cloud.firestore
        try:
            from google.cloud import firestore  # type: ignore
        except ImportError as exc:
            raise SequencePersistenceError(
                "google-cloud-firestore is not installed. Install requirements-catalog-firestore.txt "
                "or inject a client/test double."
            ) from exc

        kwargs: Dict[str, Any] = {}
        if self._project:
            kwargs["project"] = self._project
        if self._database:
            kwargs["database"] = self._database

        try:
            self._client = firestore.Client(**kwargs)
            return self._client
        except Exception as exc:
            raise SequencePersistenceError(f"Failed to instantiate Firestore client: {exc}") from exc

    def _get_server_timestamp(self) -> Any:
        """Get Firestore SERVER_TIMESTAMP sentinel safely."""
        try:
            from google.cloud import firestore
            return firestore.SERVER_TIMESTAMP
        except Exception:
            # Fallback if using fake or without google-cloud-firestore installed
            try:
                from tests.fakes.fake_firestore import SERVER_TIMESTAMP
                return SERVER_TIMESTAMP
            except Exception:
                import datetime
                return datetime.datetime.now(datetime.timezone.utc)

    # --------------------------------------------------------------------------
    # Authority & Sequence Document Validation
    # --------------------------------------------------------------------------

    def _validate_authority_doc(self, doc_data: Any) -> Dict[str, Any]:
        """Strictly validate authority state document."""
        if not isinstance(doc_data, dict):
            raise SequenceStateError(f"Authority metadata must be a dict, got {type(doc_data).__name__}")

        expected_keys = {"schema_version", "authority_id", "state", "created_at", "updated_at"}
        if not expected_keys.issubset(set(doc_data.keys())):
            missing = expected_keys - set(doc_data.keys())
            raise SequenceStateError(f"Authority metadata missing required keys: {missing}")

        schema_ver = doc_data.get("schema_version")
        if isinstance(schema_ver, bool) or not isinstance(schema_ver, int):
            raise SequenceStateError(f"Authority schema_version must be integer, got {schema_ver!r}")
        if schema_ver != SCHEMA_VERSION:
            raise SequenceStateError(f"Unsupported authority schema_version {schema_ver}, expected {SCHEMA_VERSION}")

        authority_id = doc_data.get("authority_id")
        if not isinstance(authority_id, str) or not authority_id.strip():
            raise SequenceStateError(f"Invalid authority_id: {authority_id!r}")

        for timestamp_key in ("created_at", "updated_at"):
            if timestamp_key not in doc_data or doc_data[timestamp_key] is None:
                raise SequenceStateError(f"Authority metadata missing {timestamp_key}")

        state_raw = doc_data.get("state")
        state = AuthorityState.from_value(state_raw)

        return {
            "schema_version": schema_ver,
            "authority_id": authority_id,
            "state": state,
            "created_at": doc_data.get("created_at"),
            "updated_at": doc_data.get("updated_at"),
        }

    def _validate_sequence_doc(self, doc_data: Any, expected_namespace: str) -> int:
        """Strictly validate a namespace sequence document and return last_issued."""
        if not isinstance(doc_data, dict):
            raise SequenceStateError(f"Sequence document must be a dict, got {type(doc_data).__name__}")

        ns = doc_data.get("namespace")
        if ns != expected_namespace:
            raise SequenceStateError(f"Sequence document namespace mismatch: expected {expected_namespace}, got {ns!r}")

        schema_ver = doc_data.get("schema_version")
        if isinstance(schema_ver, bool) or not isinstance(schema_ver, int):
            raise SequenceStateError(f"Sequence document schema_version must be integer, got {schema_ver!r}")
        if schema_ver != SCHEMA_VERSION:
            raise SequenceStateError(f"Unsupported sequence schema_version {schema_ver}, expected {SCHEMA_VERSION}")

        val = doc_data.get("last_issued")
        # In Python, bool is an int subclass: explicitly forbid boolean
        if isinstance(val, bool) or not isinstance(val, int):
            raise SequenceStateError(
                f"last_issued for {expected_namespace} must be non-boolean integer, got {type(val).__name__}: {val!r}"
            )
        if val < 0:
            raise SequenceStateError(f"last_issued for {expected_namespace} cannot be negative: {val}")
        if val > MAX_SEQUENCE:
            raise SequenceStateError(f"last_issued for {expected_namespace} exceeds maximum {MAX_SEQUENCE}: {val}")

        if "updated_at" not in doc_data or doc_data["updated_at"] is None:
            raise SequenceStateError(f"Sequence document for {expected_namespace} missing updated_at")

        return val

    # --------------------------------------------------------------------------
    # Explicit Initialization / Bootstrap
    # --------------------------------------------------------------------------

    def bootstrap(self, authority_id: str) -> None:
        """Explicitly bootstrap production authority and three pristine sequence counters.

        Fails closed if authority or any sequence document already exists.
        """
        if not isinstance(authority_id, str) or not authority_id.strip():
            raise SequenceStateError(f"Invalid authority_id: {authority_id!r}")

        client = self._get_client()
        auth_ref = client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT)
        seq_collection = client.collection(COLLECTION_SEQUENCES)
        ledger_collection = client.collection(COLLECTION_LEDGER)

        def txn_bootstrap(transaction: Any) -> None:
            # 1. Check authority
            auth_snap = auth_ref.get(transaction=transaction)
            if auth_snap.exists:
                raise SequenceStoreConflictError("Authority document already exists; cannot bootstrap")

            # 2. Check each sequence namespace
            for ns in REQUIRED_NAMESPACES:
                snap = seq_collection.document(ns).get(transaction=transaction)
                if snap.exists:
                    raise SequenceStoreConflictError(f"Sequence document for {ns} already exists; cannot bootstrap")

            # 3. Create authority record
            server_ts = self._get_server_timestamp()
            auth_data = {
                "schema_version": SCHEMA_VERSION,
                "authority_id": authority_id.strip(),
                "state": AuthorityState.ACTIVE.value,
                "created_at": server_ts,
                "updated_at": server_ts,
            }
            transaction.create(auth_ref, auth_data)

            # 4. Create sequence documents
            for ns in sorted(REQUIRED_NAMESPACES):
                doc_data = {
                    "namespace": ns,
                    "last_issued": 0,
                    "schema_version": SCHEMA_VERSION,
                    "updated_at": server_ts,
                }
                transaction.create(seq_collection.document(ns), doc_data)

        try:
            if hasattr(client, "run_transaction"):
                client.run_transaction(txn_bootstrap)
            else:
                # Direct invocation if custom transactional wrapper
                txn = client.transaction()
                txn_bootstrap(txn)
        except SequenceStoreConflictError:
            raise
        except Exception as exc:
            raise SequencePersistenceError(f"Bootstrap transaction failed: {exc}") from exc

    # --------------------------------------------------------------------------
    # SequenceStore Contract: get_sequence & get_next_sequence
    # --------------------------------------------------------------------------

    def get_sequence(self, entity_type: EntityType) -> int:
        """Return the current sequence number for the given entity type.

        Observational read: does not advance sequence or write any state.
        Fails closed if authority is missing or invalid.
        """
        entity_type = EntityType.from_value(entity_type)
        client = self._get_client()

        # Read authority status
        auth_ref = client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT)
        auth_snap = auth_ref.get()
        if not auth_snap.exists:
            raise SequenceStateError("Authority record does not exist; store must be initialized")
        self._validate_authority_doc(auth_snap.to_dict())

        # Read namespace sequence
        seq_ref = client.collection(COLLECTION_SEQUENCES).document(entity_type.value)
        seq_snap = seq_ref.get()
        if not seq_snap.exists:
            raise SequenceStateError(f"Sequence document for {entity_type.value} does not exist")

        return self._validate_sequence_doc(seq_snap.to_dict(), entity_type.value)

    def get_next_sequence(self, entity_type: EntityType) -> int:
        """Atomically increment and return the next sequence number for the given entity type.

        Executes inside a single Firestore transaction:
        1. Reads and validates authority metadata (state must be ACTIVE).
        2. Reads and validates current namespace sequence document.
        3. Rejects exhaustion if current value >= 999999.
        4. Verifies next ledger record does not already exist.
        5. Updates sequence counter.
        6. Writes immutable append-only ledger record.
        7. Commits transaction and returns next sequence integer.
        """
        entity_type = EntityType.from_value(entity_type)
        client = self._get_client()
        ns = entity_type.value

        auth_ref = client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT)
        seq_ref = client.collection(COLLECTION_SEQUENCES).document(ns)
        ledger_coll = client.collection(COLLECTION_LEDGER)

        def txn_allocate(transaction: Any) -> int:
            # 1. Read & validate authority
            auth_snap = auth_ref.get(transaction=transaction)
            if not auth_snap.exists:
                raise SequenceStateError("Authority record missing during allocation; fail closed")
            auth_info = self._validate_authority_doc(auth_snap.to_dict())
            if auth_info["state"] != AuthorityState.ACTIVE:
                raise SequenceStateError(
                    f"Authority state is {auth_info['state'].value}; allocation prohibited"
                )

            # 2. Read & validate sequence document
            seq_snap = seq_ref.get(transaction=transaction)
            if not seq_snap.exists:
                raise SequenceStateError(f"Sequence document for {ns} missing during allocation")
            curr_val = self._validate_sequence_doc(seq_snap.to_dict(), ns)

            # 3. Exhaustion check
            if curr_val >= MAX_SEQUENCE:
                raise SequenceExhaustedError(
                    f"Namespace {ns} sequence exhausted (current={curr_val}, max={MAX_SEQUENCE})"
                )

            next_val = curr_val + 1
            ast_id = format_identifier(entity_type, next_val)
            ledger_key = _format_ledger_key(ns, next_val)
            ledger_ref = ledger_coll.document(ledger_key)

            # 4. Verify ledger collision safety
            ledger_snap = ledger_ref.get(transaction=transaction)
            if ledger_snap.exists:
                raise SequenceStoreConflictError(
                    f"Ledger entry {ledger_key} already exists! Sequence high-water mark {curr_val} is inconsistent"
                )

            server_ts = self._get_server_timestamp()

            # 5. Update sequence document
            seq_updates = {
                "last_issued": next_val,
                "updated_at": server_ts,
            }
            seq_ref.update(seq_updates, transaction=transaction)

            # 6. Create immutable ledger entry
            ledger_entry = {
                "namespace": ns,
                "sequence_number": next_val,
                "astrazit_id": ast_id,
                "allocated_at": server_ts,
                "schema_version": SCHEMA_VERSION,
                "authority_id": auth_info["authority_id"],
            }
            transaction.create(ledger_ref, ledger_entry)

            return next_val

        try:
            if hasattr(client, "run_transaction"):
                return client.run_transaction(txn_allocate)
            else:
                txn = client.transaction()
                return txn_allocate(txn)
        except (SequenceExhaustedError, SequenceStateError, SequenceStoreConflictError):
            raise
        except Exception as exc:
            raise SequencePersistenceError(f"Allocation transaction failed: {exc}") from exc

    # --------------------------------------------------------------------------
    # Disaster Recovery, Reconciliation & Integrity Auditing
    # --------------------------------------------------------------------------

    def set_recovery_required(self, reason: str) -> None:
        """Mark the authority state as RECOVERY_REQUIRED to lock allocations."""
        client = self._get_client()
        auth_ref = client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT)
        server_ts = self._get_server_timestamp()
        try:
            auth_ref.update(
                {
                    "state": AuthorityState.RECOVERY_REQUIRED.value,
                    "updated_at": server_ts,
                    "recovery_reason": str(reason),
                }
            )
        except Exception as exc:
            raise SequencePersistenceError(f"Failed to set RECOVERY_REQUIRED state: {exc}") from exc

    def validate_integrity(self) -> IntegrityReport:
        """Perform a comprehensive consistency and integrity audit across authority, sequences, and ledger."""
        client = self._get_client()
        issues: List[str] = []
        counters: Dict[str, int] = {}
        ledger_maxes: Dict[str, int] = {ns: 0 for ns in REQUIRED_NAMESPACES}
        ledger_counts: Dict[str, int] = {ns: 0 for ns in REQUIRED_NAMESPACES}
        ledger_sequences: Dict[str, set[int]] = {ns: set() for ns in REQUIRED_NAMESPACES}

        # 1. Authority inspection
        auth_ref = client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT)
        auth_snap = auth_ref.get()
        auth_state = "UNKNOWN"
        if not auth_snap.exists:
            issues.append("Authority document does not exist")
        else:
            try:
                auth_info = self._validate_authority_doc(auth_snap.to_dict())
                auth_state = auth_info["state"].value
            except Exception as exc:
                issues.append(f"Authority document invalid: {exc}")

        # 2. Sequences inspection
        seq_coll = client.collection(COLLECTION_SEQUENCES)
        for seq_snap in seq_coll.stream():
            if seq_snap.id not in REQUIRED_NAMESPACES:
                issues.append(f"Unexpected sequence document namespace: {seq_snap.id!r}")
        for ns in REQUIRED_NAMESPACES:
            snap = seq_coll.document(ns).get()
            if not snap.exists:
                issues.append(f"Missing sequence document for namespace {ns}")
            else:
                try:
                    val = self._validate_sequence_doc(snap.to_dict(), ns)
                    counters[ns] = val
                except Exception as exc:
                    issues.append(f"Invalid sequence document for {ns}: {exc}")

        # 3. Allocation ledger inspection
        ledger_coll = client.collection(COLLECTION_LEDGER)
        for doc_snap in ledger_coll.stream():
            data = doc_snap.to_dict() or {}
            doc_id = doc_snap.id
            ns = data.get("namespace")
            seq = data.get("sequence_number")
            ast_id = data.get("astrazit_id")
            ledger_schema = data.get("schema_version")
            ledger_authority = data.get("authority_id")
            allocated_at = data.get("allocated_at")

            if ns not in REQUIRED_NAMESPACES:
                issues.append(f"Ledger doc {doc_id} contains unknown namespace: {ns!r}")
                continue

            ledger_counts[ns] += 1

            if isinstance(ledger_schema, bool) or not isinstance(ledger_schema, int) or ledger_schema != SCHEMA_VERSION:
                issues.append(f"Ledger doc {doc_id} invalid schema_version: {ledger_schema!r}")
            if not isinstance(ledger_authority, str) or not ledger_authority.strip():
                issues.append(f"Ledger doc {doc_id} invalid authority_id: {ledger_authority!r}")
            elif auth_snap.exists:
                try:
                    current_authority = self._validate_authority_doc(auth_snap.to_dict())["authority_id"]
                    if ledger_authority != current_authority:
                        issues.append(f"Ledger doc {doc_id} authority_id mismatch: got {ledger_authority!r}, expected {current_authority!r}")
                except Exception:
                    pass
            if allocated_at is None:
                issues.append(f"Ledger doc {doc_id} missing allocated_at")

            if isinstance(seq, bool) or not isinstance(seq, int) or seq < MIN_SEQUENCE or seq > MAX_SEQUENCE:
                issues.append(f"Ledger doc {doc_id} invalid sequence_number: {seq!r}")
                continue

            expected_id = format_identifier(EntityType[ns], seq)
            if ast_id != expected_id:
                issues.append(f"Ledger doc {doc_id} astrazit_id mismatch: got {ast_id!r}, expected {expected_id!r}")

            expected_key = _format_ledger_key(ns, seq)
            if doc_id != expected_key:
                issues.append(f"Ledger doc ID mismatch: got {doc_id!r}, expected {expected_key!r}")

            if seq in ledger_sequences[ns]:
                issues.append(f"Ledger doc {doc_id} duplicates logical allocation {ns}-{seq:06d}")
            ledger_sequences[ns].add(seq)

            if seq > ledger_maxes[ns]:
                ledger_maxes[ns] = seq

        # 4. Cross-check: Counter vs. Ledger max
        for ns, counter_val in counters.items():
            l_max = ledger_maxes.get(ns, 0)
            if l_max > counter_val:
                issues.append(
                    f"Integrity violation: {ns} ledger max ({l_max}) exceeds sequence counter ({counter_val})"
                )
            if counter_val > l_max:
                issues.append(
                    f"Integrity violation: {ns} sequence counter ({counter_val}) exceeds ledger max ({l_max}); evidence is incomplete"
                )
            evidence_high_water = max(counter_val, l_max)
            missing = set(range(1, evidence_high_water + 1)) - ledger_sequences.get(ns, set())
            if missing:
                issues.append(f"Ledger gap for {ns}: missing sequence numbers {sorted(missing)[:20]}")

        is_valid = len(issues) == 0
        return IntegrityReport(
            is_valid=is_valid,
            authority_state=auth_state,
            counters=counters,
            ledger_maxes=ledger_maxes,
            ledger_counts=ledger_counts,
            issues=issues,
        )

    def reconcile_high_water_marks(self, mark_active: bool = False) -> ReconciliationReport:
        """Reconcile sequence counters against durable ledger evidence.

        CRITICAL ANTI-ROLLBACK RULE:
        Counters are NEVER decreased.
        Counters may only remain unchanged or advance forward to match or exceed ledger evidence.
        If mark_active is True and all integrity checks pass, sets authority state to ACTIVE.
        """
        audit_notes: List[str] = []
        integrity = self.validate_integrity()
        previous_counters = dict(integrity.counters)
        reconciled_counters = dict(integrity.counters)

        # Filter out "ledger max exceeds counter" from blocking advance, because reconciliation exists to fix that!
        fatal_issues = [
            iss for iss in integrity.issues
            if not iss.startswith("Integrity violation")
            or "exceeds sequence counter" not in iss
        ]
        if fatal_issues:
            audit_notes.append(f"Reconciliation halted due to fatal integrity issues: {fatal_issues}")
            return ReconciliationReport(
                success=False,
                previous_counters=previous_counters,
                reconciled_counters=reconciled_counters,
                authority_state=integrity.authority_state,
                audit_notes=audit_notes,
            )

        client = self._get_client()
        server_ts = self._get_server_timestamp()

        # Determine if any counter must be advanced
        advances_needed: Dict[str, int] = {}
        for ns in REQUIRED_NAMESPACES:
            curr_c = previous_counters.get(ns, 0)
            l_max = integrity.ledger_maxes.get(ns, 0)
            if l_max > curr_c:
                advances_needed[ns] = l_max
                reconciled_counters[ns] = l_max
                audit_notes.append(f"Advancing {ns} counter from {curr_c} to {l_max} to match ledger evidence")
            else:
                audit_notes.append(f"{ns} counter {curr_c} matches or exceeds ledger evidence ({l_max}); unchanged")

        # Apply advances
        for ns, new_val in advances_needed.items():
            seq_ref = client.collection(COLLECTION_SEQUENCES).document(ns)
            seq_ref.update({"last_issued": new_val, "updated_at": server_ts})

        new_state = integrity.authority_state
        if mark_active:
            auth_ref = client.collection(COLLECTION_AUTHORITY).document(DOC_AUTHORITY_CURRENT)
            auth_ref.update(
                {
                    "state": AuthorityState.ACTIVE.value,
                    "updated_at": server_ts,
                    "reconciliation_audit": audit_notes,
                }
            )
            new_state = AuthorityState.ACTIVE.value
            audit_notes.append("Authority state updated to ACTIVE following reconciliation")

        return ReconciliationReport(
            success=True,
            previous_counters=previous_counters,
            reconciled_counters=reconciled_counters,
            authority_state=new_state,
            audit_notes=audit_notes,
        )
