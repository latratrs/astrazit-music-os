# Local Demo Catalog & Catalog Sandbox Architecture

This document describes the design, boundary protections, identity isolation, and operational interfaces of the AstraZit Music OS local demo catalog sandbox introduced in OS-007.

---

## 1. Purpose & Guarantees

The local demo catalog sandbox (pps.admin.catalog_demo) provides developers, operators, and agents with a safe, offline, hands-on environment to interact with realistic AstraZit catalog data.

### Guarantees:
1. **Zero Production Allocator Invocations**: Neither FirestoreSequenceStore nor production IdentifierAllocator is ever called or initialized.
2. **Deterministic Identity Isolation**: Public demo identifiers (DEMO-WRK-XXXXXX, DEMO-REC-XXXXXX, DEMO-REL-XXXXXX) map to isolated internal schema-valid fixture AST identifiers within the local directory. These AST-shaped fixture values are implementation details, are not issued or reserved production identifiers, and must not be exported as canonical production records without explicit transformation and revalidation.
3. **Draft 2020-12 Compliance**: All sample fixtures strictly pass offline JSON schema validation and OS-003 business rules through the canonical LocalJsonCatalogRepository boundary.
4. **Safety Marker Protection**: The sandbox directory must contain .demo-catalog.json with "mode": "DEMO" and "production": false. Any reset or destructive overwrite on an unverified directory is strictly forbidden.
5. **Completely Offline**: Zero cloud credentials, network calls, or Firestore emulator dependencies are required.

Fixture external registration fields are omitted or explicitly marked as demo-only; no real ISRC, UPC, ISWC, PRO, MLC, distributor, or platform registration is asserted.

An interrupted initialization writes `initialized: false`. Reads continue to
fail closed, while `reset --yes` (and `init --force`) may recover only when the
marker, canonical mapping, directory shape, and symlink boundaries all pass
the dedicated incomplete-sandbox verification. Malformed or unexpected state
still requires manual review and is never deleted automatically.

---

## 2. Directory Layout

The default sandbox resides in /.local/demo-catalog/ (ignored in .gitignore):

`	ext
.local/demo-catalog/
├── .demo-catalog.json            # Safety marker & identity mapping ledger
└── catalog/                      # LocalJsonCatalogRepository root
    ├── .locks/
    │   └── catalog.lock
    ├── works/
    │   ├── AST-WRK-000001.json
    │   ├── AST-WRK-000002.json
    │   └── AST-WRK-000003.json
    ├── recordings/
    │   ├── AST-REC-000001.json
    │   ├── AST-REC-000002.json
    │   ├── AST-REC-000003.json
    │   ├── AST-REC-000004.json
    │   └── AST-REC-000005.json
    └── releases/
        ├── AST-REL-000001.json
        ├── AST-REL-000002.json
        └── AST-REL-000003.json
`

---

## 3. CLI Command Reference

All CLI commands execute via standard Python module syntax:

`ash
# Initialize fresh demo sandbox with sample fixtures
python -m apps.admin.catalog_demo init

# View aggregate summary of sandbox entities, rights, and radio status
python -m apps.admin.catalog_demo summary

# List entities (works, recordings, releases)
python -m apps.admin.catalog_demo list works
python -m apps.admin.catalog_demo list recordings
python -m apps.admin.catalog_demo list releases

# Inspect detailed entity metadata
python -m apps.admin.catalog_demo show DEMO-WRK-000001
python -m apps.admin.catalog_demo show DEMO-REC-000001
python -m apps.admin.catalog_demo show DEMO-REL-000001

# Validate repository consistency, referential integrity, and schemas
python -m apps.admin.catalog_demo validate

# Safely reset/wipe the sandbox
python -m apps.admin.catalog_demo reset --yes
`
