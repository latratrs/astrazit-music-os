# ASTRAZIT MUSIC OS

## 1. Mission

**ASTRAZIT MUSIC OS** is the centralized operating system and canonical source of truth for the AstraZit music project.

As the AstraZit catalog and ecosystem scale, Music OS provides the foundational infrastructure to own, manage, and govern:
- **Immutable Song Identity**: Persistent, system-wide identifiers decoupled from third-party distribution platforms.
- **Master Music Catalog**: Authoritative tracking of tracks, stems, versions, masters, and derivatives.
- **Release & Distribution Metadata**: Global distribution states, ISRCs, UPCs, and external store mappings.
- **Rights & Content ID State**: Clear title ownership, PRO registrations, split sheets, and Content ID allowlists.
- **Audio, Master & Derivative Relationships**: Lineage tracking from initial composition and project files to final masters, instrumental cuts, and ambient reworks.
- **Lyrics & Artwork Relationships**: Canonical associations between songs, lyric sets, visual artwork, and promotional assets.
- **Gemini-Assisted Metadata Enrichment**: Structured catalog intelligence, semantic tagging, and mood/genre classification performed offline and staged for human review.
- **Analytics & Catalog Intelligence**: Performance aggregation across distribution channels and radio play.
- **Content Workflows**: Automated scheduling, packaging, and derivative asset generation.
- **Future Artist Applications**: A platform upon which new listening experiences, interactive projects, and creative tools are constructed.

---

## 2. Core Architecture Philosophy

The operational integrity of AstraZit Music OS rests upon a strict four-layer hierarchy:

$$\text{DATABASE} = \text{truth} \quad\vert\quad \text{CODE} = \text{execution} \quad\vert\quad \text{AI} = \text{reasoning} \quad\vert\quad \text{HUMAN} = \text{gatekeeper}$$

| Layer | Role | Governance Rule |
| :--- | :--- | :--- |
| **DATABASE** | **Truth** | The database is the sole canonical state. No memory, cache, or external platform record overrides it. |
| **CODE** | **Execution** | Deterministic, testable, reproducible logic carries out system functions without speculative drift. |
| **AI** | **Reasoning** | AI (e.g., Google Gemini) provides analytical, advisory, and synthesis capabilities. It is never authoritative on its own. |
| **HUMAN** | **Gatekeeper** | Humans hold absolute veto and approval authority over critical legal, financial, and canonical state transitions. |

### The Four Foundational Principles

1. **Canonical-Data Principle**
   All applications and services must read from and write to the central Music OS catalog. AI-generated metadata must **never** silently become canonical metadata. AI proposals exist in provisional staging until explicitly approved and promoted by human review.

2. **Immutable Identity Principle**
   External platform identifiers are **adapters**, not identity. Musical Works, Sound Recordings, and Releases receive separate immutable identifiers (`AST-WRK-000001`, `AST-REC-000001`, `AST-REL-000001`) under ADR-012. Third-party IDs—including DistroKid IDs, ISRCs, UPCs, Spotify IDs, Apple Music IDs, and YouTube video IDs—are platform-specific foreign keys subject to deprecation, migration, or collision. They must never replace or define the core AstraZit identity.

3. **Deterministic-Code Principle**
   Critical operations—including catalog transformations, database migrations, and audio playback—must execute deterministically. No LLM or external AI API call may ever be placed in a live broadcast song-change hot path without an explicit future architectural decision.

4. **Human Approval Principle**
   Rights, ownership, publishing, PRO registrations, split sheets, Content ID allowlists, financial records, production deployments, and destructive database/filesystem operations strictly require human approval before execution.

---

## 3. Relationship: Music OS vs. AstraZit Radio

**ASTRAZIT RADIO** is **Application #1** built on top of the AstraZit Music OS.

```
+--------------------------------------------------------------------+
|                         ASTRAZIT MUSIC OS                          |
|  (Canonical Catalog, Immutable IDs, Rights, Audio Masters, Assets) |
+---------------------------------+----------------------------------+
                                  |
                                  | Consumes Canonical Data
                                  v
                   +------------------------------+
                   |       ASTRAZIT RADIO         |
                   |       (Application #1)       |
                   |   Continuous 24/7 Stream     |
                   |   Liquidsoap + FFmpeg        |
                   +------------------------------+
```

- **The Radio is a Consumer**: AstraZit Radio does not possess its own independent song database or metadata authority. It consumes verified tracks and metadata published by Music OS.
- **Separation of Concerns**: Radio playback scheduling, rotation rules, and stream encoding reside in `apps/radio` and infrastructure services, but song truth resides strictly in the `catalog`.
- **Broadcast Resilience**: The live radio pipeline must be impervious to network outages, rate limits, or latency spikes in external APIs.

---

## 4. Current Project Phase

**Current Phase: Phase 0 — Foundation (OS-001 & OS-002)**
- Repository structure, cross-platform git rules, and operational safeguards established.
- Agent governance, workflows, skills, and architectural decision records (ADRs) codified.
- No live deployments, database schemas, or streaming pipelines are active yet.

### Explicit Non-Goals for OS-001 & OS-002
The following components are intentionally deferred to future designated tickets:
- **Catalog Schema & AST ID Allocator**: Scheduled for `OS-003` and `OS-004`.
- **Google Cloud Deployment**: No GCP resources, IAM policies, or buckets are created in this ticket.
- **Radio VPS Provisioning**: Dedicated Linux streaming host setup belongs to future `RADIO-*` tickets.
- **Audio Media Ingestion**: Importing master FLAC/WAV files and building catalog indices is deferred.
- **Liquidsoap & FFmpeg Streaming**: Pipeline scripts and RTMP broadcast loops are out of scope.
- **Gemini API Integration**: LLM enrichment service code is out of scope.
