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
- **Immutable Identity**: Internal IDs (e.g., `AST-WRK-000001`, `AST-REC-000001`, `AST-REL-000001`) must never be modified, reassigned, or recycled once allocated.
- **Independent Monotonic Counters**: Namespaces (`WORK`, `RECORDING`, `RELEASE`) increment independently from `000001` through `999999`. Values above `999999` fail closed with `SequenceExhaustedError`.
- **Adapters vs. Identity**: DSP IDs (Spotify, Apple, YouTube) and standard codes (ISRC, UPC) are external adapters, never the primary key and never inputs to ID allocation.
- **Provisional Staging**: AI-generated tags and metadata must never be directly committed to the canonical catalog without human gatekeeping.
- **Deterministic Allocation**: Use `packages.catalog.IdentifierAllocator` with a durable `SequenceStore` (`LocalJsonSequenceStore` for local development, `FirestoreSequenceStore` for production). Never manually fabricate or synthesize AST identifiers.
- **Canonical Repository Boundary**: Use `packages.catalog.CatalogRepository` (`LocalJsonCatalogRepository`) for canonical persistence. Records must be Draft 2020-12 schema-validated and satisfy referential integrity before persistence.
- **Production Identifier Authority**: Governed by ADR-016. Firestore Native mode enforces atomic sequence counters, append-only allocation ledgers, and anti-rollback reconciliation gates before activation.
- **No Physical Deletion**: Canonical records must never be deleted via public CRUD operations.

## 4. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [DECISIONS.md - ADR-001, ADR-003, ADR-012, ADR-013, ADR-014, ADR-015, ADR-016](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md)
- [CATALOG_SCHEMA.md](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/CATALOG_SCHEMA.md)
- [IDENTIFIER_ALLOCATION.md](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/IDENTIFIER_ALLOCATION.md)
- [PRODUCTION_IDENTIFIER_AUTHORITY.md](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/PRODUCTION_IDENTIFIER_AUTHORITY.md)
- [CATALOG_REPOSITORY.md](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/CATALOG_REPOSITORY.md)
- [LOCAL_DEMO_CATALOG.md](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/LOCAL_DEMO_CATALOG.md)
- [packages/catalog/identifiers.py](file:///c:/AI-PROJECTS/astrazit-music-os/packages/catalog/identifiers.py)
- [packages/catalog/sequence_store.py](file:///c:/AI-PROJECTS/astrazit-music-os/packages/catalog/sequence_store.py)
- [packages/catalog/firestore_sequence_store.py](file:///c:/AI-PROJECTS/astrazit-music-os/packages/catalog/firestore_sequence_store.py)
- [packages/catalog/repository.py](file:///c:/AI-PROJECTS/astrazit-music-os/packages/catalog/repository.py)
- [packages/catalog/local_repository.py](file:///c:/AI-PROJECTS/astrazit-music-os/packages/catalog/local_repository.py)
- [packages/schemas/work.schema.json](file:///c:/AI-PROJECTS/astrazit-music-os/packages/schemas/work.schema.json)
- [packages/schemas/recording.schema.json](file:///c:/AI-PROJECTS/astrazit-music-os/packages/schemas/recording.schema.json)
- [packages/schemas/release.schema.json](file:///c:/AI-PROJECTS/astrazit-music-os/packages/schemas/release.schema.json)
