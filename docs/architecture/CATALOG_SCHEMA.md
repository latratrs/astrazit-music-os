# AstraZit Music OS — Canonical Catalog Schema Architecture

## 1. The Tripartite Entity Architecture: Work, Recording, Release

**AstraZit Music OS** acts as the definitive source of truth for the AstraZit music project. Following post-audit architectural governance, the catalog explicitly decouples three core domain entities:

$$\text{MUSICAL WORK} \quad\longrightarrow\quad \text{SOUND RECORDING} \quad\longrightarrow\quad \text{RELEASE / PRODUCT}$$

```
+-------------------------------------------------------------------------------+
|                             MUSICAL WORK (AST-WRK)                            |
|  - Canonical Composition Title                                                |
|  - Composition Rights (Writers, Publishers, Splits, PROs, The MLC, ISWC)      |
|  - Underlying Lyrics & Composition Provenance                                 |
+---------------------------------------+---------------------------------------+
                                        |
                                        | 1-to-Many
                                        v
+-------------------------------------------------------------------------------+
|                            SOUND RECORDING (AST-REC)                          |
|  - Specific Performance Cut / Version (Original, Radio Edit, Instrumental)    |
|  - Master Recording Rights (Master Owner, ISRC, SoundExchange, Content ID)    |
|  - Audio Assets (Master WAV, Stream Derivative, Stems, DAW Project)           |
|  - Musical Attributes (BPM, Key, Duration, Energy, Genre, Moods)              |
|  - Radio Projection Profile (Consumed by AstraZit Radio)                      |
+---------------------------------------+---------------------------------------+
                                        |
                                        | Referenced by Tracklist
                                        v
+-------------------------------------------------------------------------------+
|                              RELEASE / PRODUCT (AST-REL)                      |
|  - Distributed Commercial Container (Single, EP, Album, Compilation)          |
|  - Ordered Tracklist (Positions referencing AST-REC Recordings)               |
|  - Packaging & Artwork Assets (Cover Art, Liner Notes)                        |
|  - Commercial Identifiers (UPC) & Distributor Adapters (DistroKid, DSPs)      |
+-------------------------------------------------------------------------------+
```

### Why Identities Are Separated
1. **One Work, Multiple Recordings**: A single musical composition (e.g. "Midnight Drift") may have an Original Mix, a Radio Edit, an Extended Club Mix, an Acoustic Cut, and an Instrumental version. Each recording possesses distinct acoustic properties, different durations, unique ISRCs, separate audio assets, and independent master ownership states, yet all share identical composition split sheets, writers, and PRO work registrations.
2. **One Recording, Multiple Releases**: A sound recording may appear on an initial promotional single, a subsequent studio album, a deluxe edition, and an ambient compilation. The Release owns the ordered tracklist, package artwork, and UPC. Recordings must not contain competing release membership authority.
3. **Radio Playout Target**: **AstraZit Radio** broadcasts audio recordings, not abstract compositions. By attaching radio curation profiles directly to `AST-REC` recordings, the station accurately targets specific broadcast edits (e.g., Radio Edit with voiceover ducks) rather than unsuitable extended or raw album cuts.

---

## 2. Explicit Internal Identifier Namespaces

Every canonical entity receives an immutable identifier within a controlled namespace:

| Entity | Namespace Pattern | Example | Role |
| :--- | :--- | :--- | :--- |
| **Musical Work** | `^AST-WRK-[0-9]{6}$` | `AST-WRK-000001` | Canonical musical work & composition rights |
| **Sound Recording** | `^AST-REC-[0-9]{6}$` | `AST-REC-000001` | Master performance cut & audio assets |
| **Release Product** | `^AST-REL-[0-9]{6}$` | `AST-REL-000001` | Commercial container & ordered tracklist |

### Adapters vs. Identity
External platform identifiers (DistroKid IDs, Spotify URIs, Apple Music track IDs, YouTube video IDs, ISRCs, UPCs) are **adapters**, never internal identity. Canonical ISWC belongs to Work composition rights, ISRC to Recording master rights, and UPC to Release. Distribution records may carry external identifiers or observations of these codes; these must not override canonical identifiers. External platform mappings are stored within `distribution` records and never serve as canonical primary keys.

---

## 3. Strict Rights Separation

Rights authority is partitioned according to legal reality:

### Composition Rights (Owned by `Work`)
- **Writers & Composers**: Explicit array with legal names, roles (`AUTHOR`, `COMPOSER`, `AUTHOR_COMPOSER`), IPI/CAE numbers, PRO affiliations, and split percentages.
- **Publishers**: Dedicated administering entities and percentage shares.
- **Registrations**: Granular tracking for Performing Rights Organizations (ASCAP, BMI, SESAC, PRS, etc.) and mechanical licensing (The MLC).
- **International Standard Musical Work Code (`iswc`)**.

### Master Rights (Owned by `Recording`)
- **Master Owners**: `master_rights.owners` contains one or more named participants and percentages totaling exactly 100 within the master ownership allocation. Proposed percentages do not certify ownership. `master_rights.approval_status=APPROVED` requires `approved_by` and `approved_at`, separately from record provenance.
- **International Standard Recording Code (`isrc`)**: Unique per sound recording cut.
- **SoundExchange**: Digital performance master rights registration.
- **YouTube Content ID**: Master claim policies (`MONETIZE`, `TRACK`, `BLOCK`) and official allowlist channels.

---

## 4. Historical Import vs. Native Release Policy

To enable immediate catalog ingestion of approximately 120 pre-existing AstraZit tracks without asserting false legal claims or weakening future standards, entities declare a `catalog_origin`:

```json
"catalog_origin": "NATIVE" | "HISTORICAL_IMPORT"
```

### Policy Rules

1. **NATIVE Releases (Future Music OS Pipeline)**:
   - For all newly originated tracks, rights verification is a mandatory release gate.
   - A native recording or release cannot transition to `RELEASE_READY` or `RELEASED` without fully `APPROVED` composition **and master** rights for every included Recording, verified allocations, and human gatekeeper audit metadata (`approved_by`, `approved_at`).

2. **HISTORICAL_IMPORT (Pre-Existing Catalog)**:
   - The ~120 tracks already released on streaming platforms prior to Music OS may be ingested into the catalog with status `RELEASED` while their internal rights verification remains `PENDING_HUMAN_APPROVAL`.
   - **No Silent Promotion**: The historical exception strictly forbids marking rights as `APPROVED` without formal human review.
   - **Review Retained**: Ingested records retain an explicit audit requirement for human rights gatekeepers.
   - **No Weakening of Native Standard**: Future native releases must continue to satisfy the full rights admission gate.

---

## 5. Provenance & Staged AI Promotion Model

Per **ADR-005** and post-audit governance:
- `source`: Retains original creation origin (`AI_GENERATED`, `HUMAN_ENTERED`, `IMPORTED`, `DETERMINISTICALLY_DERIVED`). This value is immutable and never overwritten upon approval.
- `approval_status`: Tracks human verification state (`PENDING_APPROVAL`, `APPROVED`, `REJECTED`).
- `canonical_status`: Distinguishes `PROVISIONAL` machine proposals from `MASTER_METADATA` certified truth.
- **Staged Promotion**: Machine-generated metadata resides in `provisional_enrichments` using a `ProvenanceWrapper`. Once verified by an authorized human gatekeeper, promoted fields are registered in `metadata_provenance` with `canonical_status: "MASTER_METADATA"` and full approver credentials.

---

## 6. Business-Rule Validation vs. Schema Boundaries

| Constraint | Enforcement Mechanism | Rationale |
| :--- | :--- | :--- |
| **Split Sheet Bounds** | JSON Schema (`minimum: 0.0`, `maximum: 100.0`) | Schema enforces range. |
| **Split Sheet Summation** | Deterministic Business Rules (`Decimal(100.0)`) | JSON Schema cannot compute arithmetic sums across array elements. |
| **Cross-Entity Reference Integrity** | Deterministic Business Rules | Verification that `astrazit_work_id` and `astrazit_recording_id` exist across entity graphs. |
| **Release Rights Gate** | Deterministic Business Rules | Cross-entity validation of work composition rights prior to native recording/release publication. |
| **Radio Playout Bounds** | Deterministic Business Rules | Confirming cue durations (`intro_duration_seconds`, `outro_duration_seconds`) do not exceed audio duration. |

---

## 7. Radio Projection (`radio-profile.schema.json`)

**AstraZit Radio** consumes eligible `AST-REC` sound recordings. The embedded `radio` profile defines:
- `radio_eligible`: Playout eligibility gate.
- `eligibility_status`: Detailed curation status (`INELIGIBLE`, `PENDING_CURATION`, `APPROVED`, `RESTRICTED`, `DEPRECATED`).
- `rotation_tier`: Station rotation weight (opaque string key decoupled from premature scheduling vocabularies).
- `daypart_candidates`: Target broadcast time blocks.
- `energy_rating`: Normalized 0.0 to 1.0 vibe score.
- `intro_duration_seconds` & `outro_duration_seconds`: Playout crossfade cues.

*Note: Playout telemetry (e.g. `play_count`, `last_played_at`) is strictly runtime telemetry and is excluded from canonical recording metadata.*

---

## 8. Schema Specification & Versioning

- **Specification**: **JSON Schema Draft 2020-12** (`https://json-schema.org/draft/2020-12/schema`).
- **Entity Schemas**:
  - `work.schema.json`
  - `recording.schema.json`
  - `release.schema.json`
  - `rights.schema.json`
  - `asset-reference.schema.json`
  - `distribution-record.schema.json`
  - `metadata-provenance.schema.json`
  - `radio-profile.schema.json`
  - `revenue-record.schema.json`
  - `event-envelope.schema.json`
- **Versioning**: Each primary entity carries a semantic `schema_version` string (e.g. `1.0.0`).

---

## 9. Intentionally Deferred Scope

- **AST Sequence Allocators**: Reserved for `OS-004`.
- **Database Provisioning**: No SQL tables, Firestore instances, or migrations.
- **Playout Scheduling**: Live Liquidsoap queueing and scheduling algorithms belong to `RADIO-*` tickets.
- **Bulk Catalog Ingestion**: Importing the real ~120 songs belongs to future ingestion tasks.

## 10. R2 Audit Contract Clarifications

### Contributors and allocation totals

`writers` is one contributor table: AUTHOR denotes a text/lyric contributor, COMPOSER a music contributor, and AUTHOR_COMPOSER both. Do not duplicate a participant's allocation merely because they have both roles. `publishers` separately records publishing/administration allocation. Each table is normalized independently to 100 for this internal contract: the writer table covers the full writer allocation, the publisher table the full publishing/administration allocation. These are **not two additive ownership pools**, do not assert 200% ownership, and do not define PRO form conventions, royalty rates, or payout entitlements. Master owners constitute a third, separate recording ownership allocation. All sums use exact Decimal arithmetic; legal source documents and authorized humans establish the actual participants and shares. Pending records contain proposals, not approved facts.

### Historical import evidence and review debt

HISTORICAL_IMPORT requires `historical_import.first_released_at`, `imported_at`, `source_reference`, and `rights_review_required`. The first public release must precede or equal import time. For Releases, `release_date`, when supplied, must match that evidenced date. The validator derives outstanding rights review from Work composition rights, Recording master plus referenced Work rights, or every Recording/Work in a Release and checks the declared review-debt flag.

Only an existing RELEASED historical Recording/Release receives the exception. RELEASE_READY requires approved rights even for historically sourced content. A future NATIVE Release of historical Recordings must approve both rights domains; historical source origin is not inherited as a release bypass. Work ACTIVE is an independent composition lifecycle state and does not itself authorize publication.

Future ingestion/write services must authenticate historical evidence, protect origin/import evidence from arbitrary reclassification, preserve approval history, and classify new products or new recordings as NATIVE. Static JSON validation records and checks these declarations; it cannot prove external release history or authenticate a human. No ingestion or transition service is implemented by OS-003.

### Complete catalog validation

`record_errors` performs structural validation followed by deterministic business rules. Recording validation requires the referenced Work in `catalog_context`; Release validation requires its Recordings and their Works. Missing context, dangling IDs, mismatched map keys, duplicate canonical IDs, invalid child records, and missing approval evidence fail closed. For isolated syntax validation only, use `make_validator`; this is not catalog admission. Release owns positive disc/track positions (disc defaults to 1); duplicate positions are rejected. A one-track SINGLE and multiple discs are valid. UPC remains optional.

The selective provenance map uses JSON Pointers to actual canonical values. Malformed pointers, negative/zero-padded array indexes, missing fields, and staging/audit-container targets fail validation. Promoted AI values retain AI_GENERATED origin plus APPROVED and MASTER_METADATA with human evidence. The fictional AI example demonstrates both pending proposals and an approved canonical mood value.

### Reporting, assets, events, and extensibility

No unbounded revenue or analytics series is embedded in Work or Recording. A standalone revenue record attributes one amount to exactly one typed Work, Recording, or Release target. Splitting a statement requires explicit separate allocations; listing several targets must not multiply an amount. Currency validation enforces only the **three-uppercase-letter currency-code shape**, not ISO 4217 membership. ZZZ is valid by shape.

Assets are URI references; embedded data URIs are prohibited. SHA-256 is named by checksum_sha256; optional MIME type, revision, and parent asset ID describe format and lineage. Storage providers do not determine entity identity. File existence and checksums are not verified without the assets.

Canonical objects use additionalProperties=false. Deliberate extension points are typed distributor URL maps, provenance/staging maps, and the open event payload. Provider names are extensible lowercase namespaces with multiple delivery records per provider. Events support typed Work/Recording/Release subjects; radio subjects use Recording IDs and rights subjects use Work or Recording IDs. Payload data_version supports future major versions independently of the envelope. Transport and deployment are unspecified. Consumers must select supported schema versions explicitly; an unfamiliar version string is not automatic migration compatibility.

Radio belongs to Recording. Rotation/daypart strings are references to future approved programming terms; example strings are illustrative, not an approved schedule. Telemetry remains excluded.

All example names, IDs, rights, approvals, registrations, URIs, hashes, and dates are fictional fixtures. They neither allocate catalog identities nor assert real AstraZit releases.

### Reproducible validation

requirements-schema.txt intentionally pins the exact existing audit dependency closure, including transitive packages. No application framework is introduced. Install into a virtual environment with `python -m pip install -r requirements-schema.txt`, then validate offline:

```text
# Windows
.venv/Scripts/python scripts/validate_schemas.py
# Linux (portable command; Windows is the tested host)
.venv/bin/python scripts/validate_schemas.py
```

All schema IDs are logical HTTPS names registered in memory; no URL is fetched. The runner checks all ten meta-schemas/references, date/date-time/URI formats, strict JSON syntax, positive examples, targeted negative fixtures, and adversarial tests. Relocated-checkout testing verifies path independence.
