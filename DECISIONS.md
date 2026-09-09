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
