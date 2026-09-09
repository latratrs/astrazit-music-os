---
name: astrazit-catalog
description: Manages the canonical AstraZit music catalog, immutable entity identities (AST-WRK / AST-REC / AST-REL), track metadata, and asset lineages.
---

# AstraZit Catalog Skill

## 1. Purpose
This skill provides authoritative guidelines and procedures for managing the canonical AstraZit music catalog. It ensures all musical works, recordings, master files, stems, and derivatives maintain strict data integrity, immutable identity, and relational consistency.

## 2. Activation Context
Activate this skill when:
- Creating, modifying, or querying song or recording metadata.
- Allocating or validating AstraZit internal identifiers (`AST-WRK-XXXXXX`, `AST-REC-XXXXXX`, `AST-REL-XXXXXX`).
- Handling track relationships (e.g., original vs. instrumental, acoustic, remix, or derivative versions).
- Associating lyrics, cover art, and stem assets with catalog entities.

## 3. Constraints
- **Immutable Identity**: Internal IDs (e.g., `AST-WRK-000001`, `AST-REC-000001`, `AST-REL-000001`) must never be modified or reassigned once allocated.
- **Adapters vs. Identity**: DSP IDs (Spotify, Apple, YouTube) and standard codes (ISRC, UPC) are external adapters, never the primary key.
- **Provisional Staging**: AI-generated tags and metadata must never be directly committed to the canonical catalog without human gatekeeping.
- **Zero Schema Fabrication**: Schema implementation belongs to ticket `OS-003`; do not invent schema fields prematurely.

## 4. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [DECISIONS.md - ADR-001, ADR-003, ADR-012, ADR-013](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md)
- [CATALOG_SCHEMA.md](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/CATALOG_SCHEMA.md)
- [packages/schemas/work.schema.json](file:///c:/AI-PROJECTS/astrazit-music-os/packages/schemas/work.schema.json)
- [packages/schemas/recording.schema.json](file:///c:/AI-PROJECTS/astrazit-music-os/packages/schemas/recording.schema.json)
- [packages/schemas/release.schema.json](file:///c:/AI-PROJECTS/astrazit-music-os/packages/schemas/release.schema.json)
- TODO: AST ID Allocator documentation (to be created in OS-004)
