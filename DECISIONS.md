# Architectural Decision Records (ADRs)

This document tracks foundational architectural decisions for AstraZit Music OS. Each decision is immutable once accepted; changes require a superseding ADR.

---

## ADR-001: Music OS is the Canonical Database of Truth

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: As the AstraZit music catalog expands across streaming services, social platforms, live radio, and distribution aggregators, metadata often fragments and diverges.
- **Decision**: AstraZit Music OS serves as the single centralized database of truth for all AstraZit musical works, recordings, versions, and associated assets. No external platform or consumer service is authoritative over Music OS.
- **Consequences**: All external platforms sync from Music OS; changes must flow through Music OS catalog ingestion and validation workflows.

---

## ADR-002: AstraZit Radio is an Application/Consumer, Not an Independent Database

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: AstraZit Radio requires music files, metadata, track sequencing, and rotation rules to broadcast 24/7.
- **Decision**: AstraZit Radio (`apps/radio`) is Application #1 built on top of Music OS. It strictly consumes tracks, metadata, and asset references from the canonical Music OS catalog and will never maintain an independent song database or metadata schema.
- **Consequences**: Radio station bugs or schema alterations cannot corrupt core catalog truth. Catalog updates propagate into radio rotation via verified sync pipelines.

---

## ADR-003: Internal AstraZit Identifiers are Immutable

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: Songs undergo multiple releases, remasters, re-recordings, distributor migrations, and title tweaks over time.
- **Decision**: Every canonical musical work and recording in the catalog will be assigned an immutable internal identifier (e.g., `AST-000001`). Once assigned, an internal ID will never be reused, reallocated, or mutated.
- **Consequences**: Cross-system links, asset references, and lineage remain permanent regardless of distributor, label, or platform changes.

---

## ADR-004: External Platform Identifiers are Adapters, Not Identity

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: Music distribution relies on platform-specific identifiers (DistroKid IDs, Spotify Track IDs, Apple Music IDs, YouTube Video IDs, ISRCs, UPCs).
- **Decision**: External identifiers are treated strictly as external adapter references / foreign keys pointing to an internal AstraZit identifier (`AST-XXXXXX`). They must never define or replace internal identity.
- **Consequences**: Songs can change distributors, receive new ISRCs upon remastering, or exist on multiple digital service providers (DSPs) without breaking internal identity or catalog relationships.

---

## ADR-005: AI-Generated Metadata is Provisional Until Promoted by Human

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: LLMs (such as Google Gemini) can rapidly analyze lyrics, suggest mood/genre tags, generate summaries, and enrich track descriptions, but are susceptible to hallucinations or inaccuracy.
- **Decision**: All AI-generated metadata, enrichments, and classification tags are written to a provisional/staging layer. They must never silently or automatically promote into the canonical catalog without explicit human review and approval.
- **Consequences**: The canonical database remains pristine and legally defensible. AI acts as an assistant to human catalog managers, not an autonomous authority.

---

## ADR-006: AI Is Strictly Prohibited in the Broadcast Song-Change Hot Path

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: 24/7 live streaming radio demands ultra-high availability, low jitter, and zero playback halts. External AI API calls introduce unpredictable network latency, rate limits, and failure modes.
- **Decision**: No LLM, Gemini API call, or network-bound AI reasoning model may be placed in the synchronous track-transition, audio-rendering, or song-change hot path of AstraZit Radio.
- **Consequences**: Radio track selection and playback must execute entirely through deterministic local logic (e.g., Liquidsoap rotation scripts, pre-computed schedules, local database queries). AI may only be used offline/asynchronously to prepare schedules or enrich metadata well in advance of broadcast.

---

## ADR-007: Rights, Ownership, Publishing, and Financial State Require Human Gatekeeping

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: Mistakes in intellectual property rights, PRO registrations (BMI, ASCAP, etc.), split sheets, Content ID allowlists, and financial reporting carry legal and financial liabilities.
- **Decision**: All modifications to rights, ownership splits, publishing details, Content ID whitelist policies, and royalty/financial data require human authorization. Automated agents are barred from executing self-approved changes to these fields.
- **Consequences**: Absolute human accountability over legal, financial, and copyright boundaries.

---

## ADR-008: Production Radio Executes on Dedicated Linux VPS, Not Windows Development PC

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: Development occurs on Windows workstations, whereas 24/7 audio streaming engines (Liquidsoap, FFmpeg, Icecast) and Linux system services require uninterrupted uptime, standard POSIX audio pipes, and dedicated server environments.
- **Decision**: The production 24/7 broadcast pipeline will execute on a dedicated Linux VPS (Virtual Private Server) and systemd services. The Windows development environment is used for catalog authoring, local tooling, offline asset processing, and testing, but will not host the live broadcast.
- **Consequences**: Repository tooling must respect cross-platform boundaries (`.gitattributes` LF endings, POSIX paths in runtime scripts, decoupled environments).

---

## ADR-009: Adoption of JSON Schema Draft 2020-12 for Canonical Data Contracts

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: AstraZit Music OS requires cross-platform, multi-language data contracts for canonical entities (songs, albums, assets, rights, radio profiles) before database implementation.
- **Decision**: Adopt JSON Schema Draft 2020-12 (`https://json-schema.org/draft/2020-12/schema`) as the official contract specification. Primary schemas reside in `packages/schemas/`.
- **Consequences**: Standardizes schema referencing (`$defs`, `$id`, `$ref`), enables deterministic multi-language validation (Python, TypeScript, Go), and provides seamless forward migration to document or relational databases.

---

## ADR-010: Provenance Staging and Human Gatekeeping for Catalog Enrichment

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: AI models (such as Google Gemini) can rapidly propose mood descriptors, genre tags, and marketing copy, but must not silently contaminate canonical catalog truth (ADR-005).
- **Decision**: All AI-generated metadata must enter through a `provisional_enrichments` staging property with an explicit `ProvenanceWrapper`. Promotion to canonical attributes requires a human gatekeeper's identity and timestamp.
- **Consequences**: Pure structural clarity between unreviewed machine proposals and certified catalog truth. Complete audit trail for all descriptive metadata.

---

## ADR-011: Delegation of Arithmetic Split Totals to Business-Rule Validation

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: Writer and publisher split sheets legally require that percentage allocations sum to exactly 100.0%. JSON Schema Draft 2020-12 provides bounding (`minimum: 0.0`, `maximum: 100.0`), but cannot compute dynamic arithmetic summations across array elements.
- **Decision**: JSON Schema enforces structural types, ranges, and patterns. Split summation arithmetic and cross-entity release gating rules are explicitly delegated to deterministic business-rule validation code in `scripts/validate_schemas.py` and downstream catalog services.
- **Consequences**: Avoids complex or non-standard schema extensions; maintains clean separation between syntactic schema validation and semantic business rules.

---

## ADR-012: Tripartite Identity Model: Work, Recording, and Release Namespaces

This ADR supersedes the illustrative untyped ID notation in ADR-003/ADR-004; their immutability and adapter principles remain in force.

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: Modeling songs as a single monolithic entity conflates underlying musical works (compositions), specific performance cuts (masters/versions), and commercial products (singles/albums). A single work frequently spawns multiple recordings (e.g., Original, Radio Edit, Instrumental), and recordings appear across multiple commercial releases.
- **Decision**: Adopt a three-tier canonical entity architecture with explicit internal identifier namespaces:
  1. `AST-WRK-XXXXXX` (Musical Work / Composition)
  2. `AST-REC-XXXXXX` (Sound Recording / Master)
  3. `AST-REL-XXXXXX` (Release Product / Tracklist Container)
  Composition rights (writers, publishers, PROs, The MLC) attach to Work. Master rights (master owner, ISRC, SoundExchange, Content ID) and audio assets attach to Recording. Releases own ordered tracklists and packaging UPCs. AstraZit Radio consumes eligible `AST-REC` sound recordings.
- **Consequences**: Pure relational modeling without competing authority. Seamless support for alternate cuts, remixes, and re-releases without identifier collisions.

---

## ADR-013: Native Release Rights Gating and Historical Catalog Import Policy

- **Status**: Accepted
- **Date**: 2026-09-08
- **Context**: Music OS requires strict legal gating before publishing new works, but must also immediately catalog approximately 120 pre-existing AstraZit songs already live across DSPs without falsely certifying that full split sheet audits are complete.
- **Decision**: Introduce an explicit `catalog_origin` discriminator (`NATIVE` vs. `HISTORICAL_IMPORT`). For `NATIVE` works and recordings, transitioning to `RELEASE_READY` or `RELEASED` strictly requires `APPROVED` rights with human audit credentials. For `HISTORICAL_IMPORT` entities, records may reflect existing `RELEASED` status while internal rights review remains `PENDING_HUMAN_APPROVAL`. Historical imports must never silently promote rights to `APPROVED`.
- **Consequences**: Enables immediate ingestion of legacy catalog while strictly enforcing human rights approval gates on all future native releases.

---

## ADR-014: Deterministic AST Identifier Allocator & Replaceable SequenceStore Boundary

- **Status**: Accepted
- **Date**: 2026-09-09
- **Context**: Ticket OS-004 requires a deterministic allocation service for the three canonical entity namespaces (`AST-WRK-`, `AST-REC-`, `AST-REL-`). Allocation must be strictly monotonic, independent across namespaces, non-recycling, and crash-resilient without choosing or provisioning the final production database prematurely.
- **Decision**: Establish an immutable internal identifier allocator architecture:
  1. Namespaces are strictly partitioned: `AST-WRK-000001` through `AST-WRK-999999`, `AST-REC-000001` through `AST-REC-999999`, and `AST-REL-000001` through `AST-REL-999999`.
  2. Numbers are 6 zero-padded decimal digits; `000000` is forbidden, and numbers $\ge 1000000$ trigger fail-closed exhaustion.
  3. External codes (ISRC, ISWC, UPC, DSP IDs) remain adapters and must never influence internal allocation.
  4. The allocator domain logic decouples from physical storage via an abstract `SequenceStore` interface (`get_sequence`, `get_next_sequence`).
  5. For OS-004 local contract verification, implement `LocalJsonSequenceStore` utilizing an atomic replace write strategy (`os.replace` + `fsync`), fail-closed strict JSON parsing (forbidding floats, bools, NaN, Infinity, duplicate keys), and advisory file locking (`msvcrt` on Windows / `fcntl` on POSIX).
  6. OS-004 explicitly documents that this local store provides single-host process and thread safety, but is NOT a distributed multi-host production allocator. Final production database selection is deferred to future tickets.
- **Consequences**: Allocator contract is fully operational and testable today with zero external infrastructure dependencies or cloud provisioning. Downstream callers can transition to a future production database store seamlessly without altering allocator domain logic.
