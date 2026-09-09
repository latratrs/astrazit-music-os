# AstraZit Music OS — Internal Identifier Allocation Architecture

## 1. Context & Purpose

In accordance with [ADR-003](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-003-internal-astrazit-identifiers-are-immutable), [ADR-004](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-004-external-platform-identifiers-are-adapters-not-identity), [ADR-012](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-012-tripartite-identity-model-work-recording-and-release-namespaces), and [ADR-014](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md#adr-014-deterministic-ast-identifier-allocator--replaceable-sequencestore-boundary), **AstraZit Music OS** governs an authoritative, deterministic internal identifier allocation service.

This service issues persistent, system-wide internal identities for all catalog entities. It defines **HOW** identifiers are deterministically generated and assigned, while [OS-003](file:///c:/AI-PROJECTS/astrazit-music-os/tasks/OS-003.md) and [CATALOG_SCHEMA.md](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/CATALOG_SCHEMA.md) govern **WHAT** these entities represent.

---

## 2. Canonical Identifier Contract

### The Three Namespaces
Exactly three entity types exist for the allocator:

| Entity Type | Prefix | Regex Pattern | Example | Canonical Scope |
| :--- | :--- | :--- | :--- | :--- |
| **WORK** | `AST-WRK-` | `^AST-WRK-[0-9]{6}$` | `AST-WRK-000001` | Musical Work / Composition / Lyrics |
| **RECORDING** | `AST-REC-` | `^AST-REC-[0-9]{6}$` | `AST-REC-000001` | Sound Recording / Performance Cut / Master |
| **RELEASE** | `AST-REL-` | `^AST-REL-[0-9]{6}$` | `AST-REL-000001` | Commercial Release Product / Tracklist Container |

### Numeric Component & Range
- **Component Format**: 6 decimal digits zero-padded (`{:06d}`).
- **Valid Production Range**: `000001` through `999999`.
- **Start Value**: Allocation starts strictly at `000001`.
- **Prohibited Numbers**:
  - `000000` is never valid and must never be issued.
  - Numbers above `999999` are invalid and trigger allocator exhaustion.

### Sequence Independence
The three sequence counters are completely **independent**:
```
AST-WRK-000001
AST-REC-000001
AST-REL-000001
```
There is no shared global sequence counter across entity types. An allocation in the `RECORDING` namespace does not advance the `WORK` or `RELEASE` counters.

---

## 3. Non-Negotiable Allocator Invariants

1. **Immutability**: Once allocated, an identifier is immutable and permanent.
2. **No Recycling**: Entity withdrawal, archival, or deletion must never lower a counter. The local store enforces this only while its latest state and coordination artifacts are preserved; see recovery limitations below.
3. **Monotonicity**: Allocations advance strictly in increasing sequential order (`1, 2, 3...`).
4. **Namespace Isolation**: Counters for `WORK`, `RECORDING`, and `RELEASE` operate independently.
5. **No Synthetic Inference**: AST identifiers are opaque internal keys. No identifier may ever be derived, hashed, or inferred from titles, artist names, ISRCs, ISWCs, UPCs, filenames, or content hashes.
6. **Decoupling from External Adapters**: External platform codes (ISRC, ISWC, UPC, DistroKid IDs, Spotify URIs, Apple IDs, YouTube IDs) are strictly foreign adapters. They must NEVER influence identifier allocation.
7. **Fail-Closed on Unknown Entity**: Requests for invalid entity types fail immediately with `InvalidEntityTypeError` and do not alter sequence state.
8. **Inspection Safety**: Read-only operations (`peek_next()`, `current_sequence()`) must never advance or alter sequence state.
9. **Fail-Closed on Corruption**: Malformed or invalid persisted state halts the allocator (`SequenceStateError`) without automatic reset or recovery. Valid-looking edits or rollback cannot be detected by this local counter.
10. **Persistence Verification**: If state commit fails, the allocator fails closed with `SequencePersistenceError`; it must never report an ID as allocated unless durable commit succeeded.

---

## 4. Exhaustion Policy

When any namespace reaches its maximum capacity of `999999`, that namespace is **exhausted**.

The subsequent allocation attempt for that namespace raises `SequenceExhaustedError`. Under NO circumstances will the allocator:
- Wrap around to `000000` or `000001`.
- Automatically expand the digit width to 7 digits.
- Switch prefixes or steal counters from another entity type.
- Silently reset or create new namespaces.

Exhaustion is isolated to the exhausted namespace. An exhaustion of `AST-WRK-` does not impair operations in `AST-REC-` or `AST-REL-`.

---

## 5. Persistence Architecture & `SequenceStore` Abstraction

The identifier allocator decouples domain logic from physical storage through a replaceable `SequenceStore` abstraction:

```
+------------------------------------+
|        IdentifierAllocator         |
|   (Domain Rules, Formatting, API)  |
+-----------------+------------------+
                  |
                  | Depends strictly on interface
                  v
+------------------------------------+
|          SequenceStore             |
|  - get_sequence(entity_type)       |
|  - get_next_sequence(entity_type)  |
+-----------------+------------------+
                  |
       +----------+----------+
       |                     |
       v                     v
+---------------+   +-----------------------------+
| LocalJson     |   | Future Production Database  |
| SequenceStore |   | (PostgreSQL / Cloud SQL /   |
| (OS-004 Local)|   |  Cloud Spanner)             |
+---------------+   +-----------------------------+
```

Domain logic in `packages.catalog.identifiers` contains zero knowledge of files, locks, SQL, or cloud APIs.

### Local Durable Store (`LocalJsonSequenceStore`)
For development and contract verification in OS-004, `LocalJsonSequenceStore` provides a lightweight, durable file-backed store:
- **Location**: Explicitly parameterized file path. Use `.local/allocator/catalog_sequences.json` or an external private temporary directory. `.local/allocator/` and the legacy example filename `catalog_sequences.json` plus its sidecars are ignored by Git. Arbitrary custom paths outside these locations need their own ignore rules.
- **Sidecars**: Append `.lock` and `.initialized` to the complete resolved state filename. Reserve these names exclusively for this store; do not use a sidecar as another store's state file.
- **Format**: Strictly formatted JSON with `schema_version` and closed namespace map.
  ```json
  {
    "schema_version": 1,
    "sequences": {
      "WORK": 0,
      "RECORDING": 0,
      "RELEASE": 0
    }
  }
  ```
- **Strict Parsing**:
  - Rejects NaN, Infinity, -Infinity (`reject_json_constant`).
  - Rejects duplicate JSON keys (`unique_json_pairs`).
  - Rejects booleans disguised as integers (e.g., `true`/`false` in JSON or `bool` in Python).
  - Rejects floats, strings, negative numbers, or numbers exceeding `999999`.
  - Rejects missing or unknown root keys.

---

## 6. Crash Safety & Durability Semantics

To prevent partial writes, corrupted states, or torn pages upon process interruption:
1. **Validation Pre-Flight**: The new state dictionary is verified against all schema rules before any I/O occurs.
2. **Write to Temporary File**: Serialized JSON is written to a hidden temporary file in the **same directory** as the canonical state file (to guarantee cross-directory filesystem boundary equivalence).
3. **Flushing & Syncing**: File buffers are flushed (`flush()`) and `os.fsync()` is requested before closing.
4. **Atomic Replacement**: The temporary file replaces the target via `os.replace()` on a supported local filesystem. The operation occurs inside the allocation lock.
5. **Failure Boundary**: A failure before replacement leaves existing canonical state unchanged; the writer attempts to remove only its own unique temporary file. There is no restoration of old canonical state. If replacement succeeds but an exception or process exit prevents the response, the sequence is consumed; retry reads the advanced state and issues the following number. Filesystem errors may have an ambiguous commit outcome: an exception does not prove the counter stayed unchanged.

### Limitations of Local Store
The parent directory is not fsynced after replacement or marker creation. File fsync and atomic replacement do not establish a guarantee against power loss, filesystem caching, storage faults, or lost directory updates. A process crash before replacement leaves the previous counter (or an initialization marker requiring recovery); a crash after replacement normally leaves the advanced counter, potentially burning an unreturned ID. No global never-reuse or distributed clustering guarantee is provided.

---

## 7. Concurrency Guarantees

### Local Concurrency Boundary
The OS-004 implementation guarantees that **concurrent allocations on a single host within the supported local execution model will never yield duplicate identifiers or corrupt sequence monotonicity**:
- **Multi-Threading**: Synchronized via re-entrant mutual exclusion (`threading.RLock`).
- **Multi-Process**: Synchronized via OS-level advisory file locking (`FileLock` utilizing `msvcrt.locking` on Windows and `fcntl.flock` on POSIX).

The allocation critical section covers lock acquisition, reading current state, validation, exhaustion checking, increment calculation, initialization marker persistence, temporary write/flush/fsync, replacement, and successful return from the store before unlock. Separate instances coordinate through the same OS lock, not through their instance-local RLocks alone.

Windows locks byte range [0, 1) on a separately opened `.lock` file, including when the file is empty (locking beyond EOF is supported in the tested Windows environment). Both lock and unlock explicitly seek to zero. Nonblocking attempts retry every 5 ms for at most approximately 30 seconds; OS call latency may extend elapsed time. Closing the handle releases the lock, including on exceptions. State replacement never replaces the lock file. Windows subprocess contention was runtime-tested by AUDIT-OS-004-R1; the POSIX flock path was inspected statically only, not runtime-verified.

Paths are resolved at construction, covering relative paths, parent traversal, and stable symlink/junction aliases. Windows case aliases refer to the same lock resource. All writers must cooperate and use stable paths on a supported local filesystem in a private directory. Hard-link aliases, retargeted links, hostile directory changes, and manual lock deletion/replacement during allocation are outside this guarantee. Never delete or replace the lock file while an allocator may be running.

Inspection reads one atomically replaced JSON snapshot without acquiring or creating locks, directories, markers, or state files. A concurrent allocation may make the result stale immediately; `peek_next()` is not a reservation. During first initialization, inspection may fail closed if it sees the marker before the state.

### Explicit Non-Claims
- **No Distributed Atomicity**: Does NOT coordinate across multiple hosts, virtual machines, or separate container instances without shared POSIX lock capability.
- **No Database Engine**: Does not implement MVCC, distributed two-phase commit, or Raft consensus.
- **Production Replacement**: When transitioning to multi-host production (Phase 1+), a relational or cloud-native `SequenceStore` implementation will supersede `LocalJsonSequenceStore`.

---

## 8. Recovery & Corruption Handling

The sequence service enforces a strict **fail-closed** corruption policy:
- If a state file is unreadable, syntactically malformed, or structurally incomplete, the service immediately throws `SequenceStateError`.
- **Zero Automatic Repair**: The service NEVER resets counters to 0, guesses values, or truncates files.
- **Human Gatekeeping**: Restoring corrupted sequence state requires human operator intervention, state validation, and audit sign-off.

Before the first commit, allocation creates and fsyncs a persistent `.initialized` marker under the same lock. A missing state file with this marker raises `SequenceStateError`, including after constructing a new store or restarting the process. Marker-only state following a failed first write requires recovery; it is never automatically reset. Existing valid state is adopted and marked on its next allocation.

Absence of both state and marker is treated as a fresh development store. Deleting both, restoring an older valid state or backup, or losing writes to power failure can therefore allow reuse. The marker is evidence of initialization, not a historical high-water ledger. Deleting the lock alone between allocations does not reset counters, but deletion during active use can break mutual exclusion. Recovery must stop all writers and establish counters at least as high as every possibly issued ID from authoritative evidence. Do not resume from an old backup or guess a counter. No production IDs are authorized for this local development backend.

## 9. Public API Input Semantics

`allocate`, `peek_next`, and `current_sequence` accept `EntityType` members or strings normalized with `strip().upper()`. Thus `"WORK"`, `"work"`, `" WORK "`, and `"RECORDING\n"` select their existing namespaces. `None`, booleans, numbers, containers, unrelated objects, prefixes, and unknown names raise `InvalidEntityTypeError` before filesystem access. The store methods also validate entity inputs. Formatting takes an `EntityType` and a non-boolean integer in [1, 999999]; parsing requires an exact canonical string with no trailing newline or whitespace. No metadata or external identifiers are allocation inputs.
