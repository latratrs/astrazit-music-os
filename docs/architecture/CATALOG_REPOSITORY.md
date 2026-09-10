# AstraZit Music OS — Canonical Catalog Repository Architecture

## 1. Context & Purpose

In accordance with [ADR-001](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-001-music-os-is-the-canonical-database-of-truth), [ADR-003](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-003-internal-astrazit-identifiers-are-immutable), [ADR-012](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-012-tripartite-identity-model-work-recording-and-release-namespaces), and [ADR-015](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-015-catalogrepository-abstraction-and-local-durable-persistence-backend), **AstraZit Music OS** establishes its first canonical repository boundary.

This boundary defines how validated canonical records (`WORK`, `RECORDING`, `RELEASE`) are stored, retrieved, updated, and protected with strict referential integrity and fail-closed persistence while keeping the physical persistence backend completely replaceable.

```
+-------------------------------------------------------------+
|                     Caller / Application                    |
+------------------------------+------------------------------+
                               |
                               | Pure AST Identifiers & Dict Records
                               v
+-------------------------------------------------------------+
|                     CatalogRepository                       |
|  - create(entity_type, record)                              |
|  - get(entity_type, ast_id)                                 |
|  - update(entity_type, ast_id, record)                      |
|  - exists(entity_type, ast_id)                              |
|  - list_ids(entity_type)                                    |
+------------------------------+------------------------------+
                               |
                               | Schema Validation (Draft 2020-12)
                               | Referential Integrity Checks
                               v
+-------------------------------------------------------------+
|             LocalJsonCatalogRepository (OS-005)             |
|   - Atomic writes via mkstemp + os.replace + os.fsync       |
|   - Advisory file locking via cross-platform FileLock       |
|   - Strict JSON deserialization (no NaN, Infinity, dup keys)|
|   - Deep-copy mutation protection                           |
+-------------------------------------------------------------+
                               |
                               v (Future Milestone)
+-------------------------------------------------------------+
|               Production Database Backend                   |
|   (PostgreSQL / Cloud SQL / Cloud Spanner)                  |
+-------------------------------------------------------------+
```

---

## 2. Core Repository Contract

The repository contract decouples domain callers from physical storage:
1. **Entity Boundaries**: Only three canonical top-level entities exist: `WORK`, `RECORDING`, and `RELEASE`. Sub-entities (e.g. rights, assets, tracklists) are embedded within canonical records according to OS-003 schemas.
2. **Pre-Assigned AST Identifiers**: Identifiers are allocated prior to persistence via the OS-004 `IdentifierAllocator`. The repository enforces identity matching and never silently allocates IDs.
3. **Draft 2020-12 Schema Pre-Validation**: Every incoming record must pass offline Draft 2020-12 schema validation before touching persistent storage.
4. **Immutable Identity**: AST identifiers cannot be changed or swapped during update operations.
5. **No Physical Deletion**: Canonical identity records do not casually disappear. No public delete operation is exposed in OS-005.

---

## 3. Referential Integrity Rules

The repository strictly enforces referential integrity on `create()` and `update()` operations:

### RECORDING -> WORK
- Every `RECORDING` record possesses an `astrazit_work_id`.
- The referenced Work must exist in the repository under entity type `WORK`.
- If the referenced Work is absent or corrupted, the operation fails closed with `CatalogIntegrityError`.
- If `astrazit_work_id` has an invalid entity type prefix (e.g. `AST-REC-`), the operation is rejected.

### RELEASE -> RECORDING
- Every track entry in `RELEASE.tracklist` possesses an `astrazit_recording_id`.
- Every referenced Recording must exist in the repository under entity type `RECORDING`.
- If any referenced Recording is absent or corrupted, the operation fails closed with `CatalogIntegrityError`.
- If a track references an invalid entity type prefix (e.g. `AST-WRK-`), the operation is rejected.

---

## 4. Local Durable Persistence Backend (`LocalJsonCatalogRepository`)

The local filesystem implementation provides a transparent, inspectable storage layout:

```
catalog_root/
    works/
        AST-WRK-000001.json
    recordings/
        AST-REC-000001.json
    releases/
        AST-REL-000001.json
    .locks/
        catalog.lock
```

### Concurrency & Locking
- A shared advisory file lock (`catalog_root/.locks/catalog.lock`) is acquired across referential integrity verification and file persistence.
- Each repository instance also serializes callers with an instance-local `RLock` because `FileLock` owns one OS handle; separate instances and processes coordinate through the shared OS lock.
- Lock acquisition uses platform primitives (`msvcrt` on Windows, `fcntl` on POSIX systems).
- Guarantees race-free single-host concurrency across threads and independent operating system processes.

### Atomic Writes & Create-If-Absent Semantics
- Records are serialized to deterministic JSON.
- Records are written to a unique temporary file in the target directory (ensuring same filesystem mount).
- Temporary file is flushed and synced (`os.fsync()`) before atomic replacement.
- In `create()`, the repository verifies target absence inside the lock, raises `CatalogConflictError` if already present, and never overwrites an existing canonical record.
- In `update()`, the repository verifies target presence inside the lock and atomically replaces the file (`os.replace()`).
- Concurrent updates use last-writer-wins ordering determined by lock acquisition. OS-005 has no optimistic version check.

### Copy Safety
- Internal state is never directly exposed.
- All returns from `get()`, `create()`, and `update()` return detached deep copies (`copy.deepcopy()`). Mutating retrieved dictionaries has zero effect on repository state.

---

## 5. Storage Corruption & Strict JSON

Persisted canonical state fails closed on any detected tampering or degradation:
- **Strict JSON**: Rejects NaN, Infinity, -Infinity, duplicate keys, and invalid UTF-8.
- **Root Type Safety**: Rejects non-object JSON roots.
- **Identity Consistency**: Rejects file where content AST ID does not match filename stem.
- **Schema Conformity**: Rejects any persisted file that violates its entity schema upon retrieval or listing.
- **Referential Conformity**: A referenced Recording is checked together with its referenced Work before a Release is accepted; filename existence alone is never sufficient.
- **Release Rights Gates**: `RELEASE_READY` and native `RELEASED` Recordings require approved master and Work composition rights; corresponding Releases require approved provenance and approved rights for every referenced Recording and Work. Existing released historical imports retain the OS-003 exception.
- **Zero Silent Auto-Repair**: Corrupted records raise `CatalogStateError` immediately.

---

## 6. Important Local-Store Limitations

In alignment with ADR-014 and ADR-015, the local filesystem backend has explicit documented boundaries:
1. **Single-Host Only**: Advisory file locking guarantees safety only across processes and threads on a single host. It does not provide distributed multi-host consensus or cloud-scale clustering.
2. **Manual Deletion / File Rollback**: External deletion of catalog files or restoration of stale filesystem backups cannot be automatically prevented by local file locks.
   Deleting the entire root and reconstructing a repository therefore presents as an empty local store. This backend has no durable catalog-initialization marker; recovery and reconciliation are operator responsibilities.
3. **Power Loss Beyond OS Fsync**: While `os.fsync()` commits buffers to OS page cache and drive controllers, hardware drive write-cache failure modes are bounded by underlying host OS and drive semantics.
4. **Cross-Entity Multi-Record Transactions**: Creating a Work and then a Recording are separate canonical operations. If a caller crashes between creating a Work and creating its Recording, the Work exists without the Recording. However, an invalid dangling Recording can NEVER become canonical.

Directory listing skips hidden entries as runtime artifacts; visible non-JSON files, invalid JSON filenames, invalid UTF-8, duplicate keys, schema-invalid records, and filename/content identity mismatches fail closed. Do not place canonical records in hidden filenames.

Pre-replace write failures leave prior canonical bytes intact and clean up only the operation's unique temporary file. If `os.replace()` succeeds and an exception follows, the replacement may already be canonical; the repository never restores the old record.

A future production database backend (ADR-015) will establish distributed transactions and managed enterprise persistence.
