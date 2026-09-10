# Local Admin Catalog Viewer Architecture

Governed by OS-008.

## 1. Overview & Purpose
The Local Admin Catalog Viewer (`apps.admin.catalog_viewer`) provides the first local, browser-based administrative interface for AstraZit Music OS. It allows operators, engineers, and agents to visually inspect the validated demo catalog sandbox, its entity hierarchies, lifecycle states, composition and master rights, and radio playout eligibility metadata without introducing competing catalog models or mutable operations.

## 2. Core Architecture & Safety Boundaries

The viewer operates strictly within the four-tier governance model:
$$\text{DATABASE} = \text{truth} \quad\vert\quad \text{CODE} = \text{execution} \quad\vert\quad \text{AI} = \text{reasoning} \quad\vert\quad \text{HUMAN} = \text{gatekeeper}$$

### Preferred Dependency Flow:
```
Browser
  ↓ HTTP GET (Loopback Only)
CatalogViewerRequestHandler (apps.admin.catalog_viewer.app)
  ↓
CatalogViewerService (apps.admin.catalog_viewer.service)
  ↓ View Models (DEMO-safe presentation)
DemoCatalogSandbox / CatalogRepository (apps.admin.catalog_demo.sandbox)
  ↓
LocalJsonCatalogRepository (packages.catalog.local_repository)
  ↓
.local/demo-catalog/catalog/
```

### Safety Guarantees:
1. **Zero External Dependencies**: Built entirely using Python standard library (`http.server`, `urllib.parse`, `html`, `dataclasses`). Zero React, Node, or third-party web frameworks.
2. **Deterministic Identity Isolation & AST Leak Protection**:
   - Internal AST fixture IDs (`AST-WRK-*`, `AST-REC-*`, `AST-REL-*`) are internal sandbox storage details.
   - All presentation models, URLs, tables, and relationship links map to public DEMO IDs (`DEMO-WRK-*`, `DEMO-REC-*`, `DEMO-REL-*`).
   - Normal rendered HTML is guaranteed free of internal AST fixture IDs.
   - Incoming URLs with `AST-` IDs are rejected with 404 Not Found.
3. **Loopback-Only Binding**: Defaults to `127.0.0.1` (configurable port, default `8765`). Will not bind to public interfaces without explicit request.
4. **Strictly Read-Only (No Mutation Guarantee)**:
   - Viewer exposes only `GET`, `HEAD` routes.
   - All `POST`, `PUT`, `PATCH`, `DELETE` requests are immediately rejected with `405 Method Not Allowed`.
   - Browser viewer has no buttons or forms for creating, editing, deleting, approving, or resetting catalog records.
5. **Production Allocator Isolation**:
   - Never instantiates `IdentifierAllocator`, `LocalJsonSequenceStore`, or `FirestoreSequenceStore`.
   - Zero production identifiers are reserved, allocated, or consumed.
6. **Cloud & Network Safety**:
   - Zero Google Cloud Platform, Firestore emulator, or external network requests.
   - Pure local filesystem operation.

## 3. URL Contract
- `GET /` -> Redirects (302) to `/admin/catalog`
- `GET /health` -> Health check JSON (`{ "status": "ok", "mode": "DEMO_VIEWER", "sandbox_initialized": true }`)
- `GET /admin/catalog` -> Catalog summary dashboard (entity counts, validation status, rights distributions, radio eligibility)
- `GET /admin/catalog/works` -> List of all musical works
- `GET /admin/catalog/works/<demo_id>` -> Detailed musical work page with writers, publishers, splits, and linked recordings
- `GET /admin/catalog/recordings` -> List of all sound recordings
- `GET /admin/catalog/recordings/<demo_id>` -> Detailed sound recording page with master rights, musical metadata, radio rotation, and linked releases
- `GET /admin/catalog/releases` -> List of all commercial releases
- `GET /admin/catalog/releases/<demo_id>` -> Detailed commercial release page with ordered tracklist, distribution state, and artwork metadata
- `GET /admin/catalog/static/catalog.css` -> Local dark-studio stylesheet

## 4. Startup & Execution
Start the viewer via standard Python module execution:
```bash
.venv\Scripts\python.exe -m apps.admin.catalog_viewer
```
Optional flags:
- `--port 8765`: Override port.
- `--host 127.0.0.1`: Override host (defaults to loopback).
- `--sandbox-dir <path>`: Point to custom demo sandbox.

## 5. Relationship Navigation
The viewer visualizes canonical three-tier hierarchy:
- **Work Detail**: Displays and links to all Sound Recordings linked to that composition.
- **Recording Detail**: Displays and links back to the underlying Musical Work, as well as all Releases containing that recording.
- **Release Detail**: Displays an ordered tracklist linking each track directly to its Sound Recording detail page.

## 6. Future Boundary for OS-009+
This viewer is strictly observational. Editing, draft creation, split sheet verification, and promotion workflows belong to future tickets (e.g. OS-009) and must adhere to human approval gates and explicit transactional APIs.
