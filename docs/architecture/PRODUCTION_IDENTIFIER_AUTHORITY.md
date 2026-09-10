# AstraZit Music OS — Production Identifier Authority Architecture

## 1. Context & Purpose
In accordance with [ADR-003](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-003-internal-astrazit-identifiers-are-immutable), [ADR-004](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-004-external-platform-identifiers-are-adapters-not-identity), [ADR-012](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-012-tripartite-identity-model-work-recording-and-release-namespaces), [ADR-014](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-014-deterministic-ast-identifier-allocator--replaceable-sequencestore-boundary), and [ADR-016](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-016-firestore-as-production-identifier-authority-backend), this document specifies the production authoritative backend for AST internal identifier allocation.

Production backend selected: **Google Cloud Firestore (Standard edition, Native mode)**.

The identifier allocator decouples domain allocation logic from physical persistence via the `SequenceStore` interface. `FirestoreSequenceStore` serves as the distributed, production-grade implementation of this interface.

---

## 2. Firestore Data Model

The production authority utilizes three distinct internal collections in Firestore Native mode:

```
astrazit_id_authority/
  current                  <-- Authority lifecycle state & schema version

astrazit_id_sequences/
  WORK                     <-- Monotonic high-water mark for Musical Works
  RECORDING                <-- Monotonic high-water mark for Sound Recordings
  RELEASE                  <-- Monotonic high-water mark for Releases

astrazit_id_allocations/
  {NAMESPACE}-{NUMBER}     <-- Append-only immutable proof of allocation
```

### 1. Authority Metadata (`astrazit_id_authority/current`)
- `schema_version`: integer (`1`)
- `authority_id`: string (e.g. `"astrazit-prod-authority"`)
- `state`: enum string:
  - `INITIALIZING`: Store bootstrap in progress.
  - `ACTIVE`: Normal allocation permitted.
  - `RECOVERY_REQUIRED`: Restore or regression detected; all allocations fail closed.
- `created_at`: server timestamp
- `updated_at`: server timestamp

### 2. Sequence Documents (`astrazit_id_sequences/{NAMESPACE}`)
Exactly three documents: `WORK`, `RECORDING`, and `RELEASE`.
- `namespace`: `"WORK"` | `"RECORDING"` | `"RELEASE"`
- `last_issued`: integer (`0` to `999999`)
- `schema_version`: integer (`1`)
- `updated_at`: server timestamp

### 3. Allocation Ledger (`astrazit_id_allocations/{NAMESPACE}-{NUMBER:06d}`)
Append-only collection. Deterministic document IDs: e.g. `WORK-000001`, `RECORDING-000042`.
- `namespace`: `"WORK"` | `"RECORDING"` | `"RELEASE"`
- `sequence_number`: integer (`1` to `999999`)
- `astrazit_id`: string (e.g. `"AST-WRK-000001"`)
- `allocated_at`: server timestamp
- `schema_version`: integer (`1`)
- `authority_id`: string

---

## 3. Atomic Allocation Transaction Semantics

Every identifier allocation executes in a single Firestore transaction:
1. **Validate Authority**: Read `astrazit_id_authority/current`. State must be strictly `ACTIVE`. If `RECOVERY_REQUIRED`, missing, or malformed, fail closed immediately.
2. **Read Sequence Document**: Read `astrazit_id_sequences/{NAMESPACE}`. Validate `namespace`, `schema_version`, and non-boolean integer `last_issued`.
3. **Exhaustion Guard**: If `last_issued >= 999999`, raise `SequenceExhaustedError` and abort.
4. **Compute Next Number**: `next_seq = last_issued + 1`.
5. **Ledger Pre-check**: Format ledger key `{NAMESPACE}-{next_seq:06d}`. Read ledger document: if it already exists, raise `SequenceStoreConflictError`.
6. **Update Sequence Counter**: Set `last_issued = next_seq` and update timestamp.
7. **Append Ledger Record**: Create ledger document with complete audit metadata.
8. **Commit & Format**: On transaction commit, return `next_seq` to `IdentifierAllocator`, which formats the canonical AST string.

---

## 4. Anti-Rollback & Disaster Recovery Gate

Firestore snapshot restoration or point-in-time recovery can recreate an older sequence counter state.

### Core Anti-Rollback Rules:
1. **No Automatic Activation**: Restored databases must NEVER immediately resume allocation.
2. **RECOVERY_REQUIRED State**: Upon any restore, replacement, or suspected rollback, authority state must be set to `RECOVERY_REQUIRED`. Normal `get_next_sequence()` calls fail closed.
3. **Ledger Max Integrity**: If $\max(\text{ledger}) > \text{sequence counter}$, the state is inconsistent. Allocation fails closed.
4. **Counters Never Decrease**: Anti-rollback reconciliation (`reconcile_high_water_marks()`) can only advance sequence counters forward to match ledger evidence. Counters are NEVER decreased.
5. **Explicit Activation**: Transitioning authority back to `ACTIVE` requires operator execution after complete ledger reconciliation passes.

### Restore boundary

Firestore-internal reconciliation alone cannot detect a fully self-consistent stale restore of the counter, allocation ledger, and `ACTIVE` authority metadata together. A restored database must therefore be forced through an external recovery process that sets `RECOVERY_REQUIRED` before it is accepted as authoritative; that process may require independent durable evidence from outside the restored database. OS-006 does not claim protection against an arbitrary rollback of every copy of its own evidence.

---

## 5. Burned Identifiers & Decoupled Boundaries

In accordance with ADR-014 and OS-005:
- Identifier allocation and catalog record persistence remain separate operations.
- If an allocation transaction commits successfully in Firestore, but the downstream caller experiences a network failure or repository validation failure, that AST identifier remains **burned**.
- Counters are never decremented and ledger documents are never deleted to "recover" an identifier. Gaps are expected and safe.

---

## 6. Development vs. Production Split-Brain Prevention

- `LocalJsonSequenceStore`: Local file-based development and test contract verification only. Single-host thread and process safe.
- `FirestoreSequenceStore`: Distributed production authority backend.
- A production runtime must never treat both backends as co-authoritative.
- Zero import-time cloud connections exist in `packages.catalog`.
