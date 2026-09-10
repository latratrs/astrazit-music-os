"""Local catalog demo sandbox environment and safety boundary.

Governed by OS-007.
Encapsulates LocalJsonCatalogRepository inside an isolated sandbox directory
(defaulting to .local/demo-catalog/), protects against escaping the sandbox root,
enforces safe demo markers, and provides translation between public DEMO- IDs
and isolated internal schema-valid fixture AST- IDs.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from apps.admin.catalog_demo.fixtures import (
    DEMO_TO_INTERNAL_ID,
    INTERNAL_TO_DEMO_ID,
    get_all_demo_fixtures,
)
from packages.catalog.identifiers import EntityType
from packages.catalog.local_repository import LocalJsonCatalogRepository
from packages.catalog.repository import (
    CatalogConflictError,
    CatalogError,
    CatalogIntegrityError,
    CatalogNotFoundError,
    CatalogStateError,
    CatalogValidationError,
)
from packages.catalog.validation import get_default_validator, parse_strict_json

MARKER_FILE_NAME = ".demo-catalog.json"
DEFAULT_SANDBOX_REL_PATH = Path(".local") / "demo-catalog"


class DemoSandboxError(Exception):
    """Base exception for all demo catalog sandbox errors."""


class SandboxUninitializedError(DemoSandboxError):
    """Raised when accessing a demo sandbox that has not been initialized."""


class SandboxSafetyError(DemoSandboxError):
    """Raised when an operation would violate sandbox safety boundaries."""


class DemoMappingError(DemoSandboxError):
    """Raised when demo identifier mapping fails or is corrupted."""


def get_default_sandbox_path() -> Path:
    """Resolve the default sandbox directory relative to the repository root."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return repo_root / DEFAULT_SANDBOX_REL_PATH


class DemoCatalogSandbox:
    """Isolated local demo catalog sandbox environment.

    Safety Guarantees:
    - Never calls Firestore, GCP, or production SequenceStore.
    - Operates exclusively within sandbox_dir.
    - Requires .demo-catalog.json safety marker to exist before reading or mutating.
    - Reset/force-init refuses to delete any directory lacking a valid demo marker.
    - Refuses to operate on paths that resolve outside sandbox_dir.
    """

    def __init__(self, sandbox_dir: Optional[Union[Path, str]] = None) -> None:
        self.sandbox_dir = (
            Path(sandbox_dir).resolve()
            if sandbox_dir is not None
            else get_default_sandbox_path().resolve()
        )
        self.marker_path = self.sandbox_dir / MARKER_FILE_NAME
        self.catalog_root = self.sandbox_dir / "catalog"
        self.validator = get_default_validator()
        self._repository: Optional[LocalJsonCatalogRepository] = None

    @property
    def repository(self) -> LocalJsonCatalogRepository:
        """Get or initialize the underlying LocalJsonCatalogRepository."""
        if self._repository is None:
            self._repository = LocalJsonCatalogRepository(
                self.catalog_root, validator=self.validator
            )
        return self._repository

    def is_initialized(self) -> bool:
        """Check if the sandbox exists and has a valid safety marker."""
        if not self.marker_path.exists():
            return False
        try:
            marker = self._read_marker()
            return (
                marker.get("mode") == "DEMO"
                and marker.get("production") is False
                and marker.get("initialized") is True
            )
        except Exception:
            return False

    def _read_marker(self) -> dict[str, Any]:
        """Read and strictly parse the safety marker file."""
        if not self.marker_path.exists():
            raise SandboxUninitializedError(
                f"Sandbox marker not found at {self.marker_path}. Run 'init' first."
            )
        content = self.marker_path.read_text(encoding="utf-8")
        try:
            data = parse_strict_json(content)
        except Exception as exc:
            raise SandboxSafetyError(
                f"Corrupted demo sandbox marker at {self.marker_path}: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise SandboxSafetyError(
                f"Marker at {self.marker_path} must be a JSON object"
            )

        if (data.get("mode") != "DEMO" or data.get("production") is not False
                or data.get("initialized") is not True):
            raise SandboxSafetyError(
                f"Invalid or incomplete safety marker at {self.marker_path}"
            )
        return data

    def _verify_recoverable_incomplete_sandbox(self) -> dict[str, Any]:
        """Verify a structurally safe, interrupted demo initialization.

        Incomplete markers are intentionally accepted only by destructive
        recovery.  Normal reads continue to use ``_read_marker`` and therefore
        remain fail-closed.
        """
        if not self.sandbox_dir.exists() or not self.sandbox_dir.is_dir():
            raise SandboxSafetyError("Incomplete sandbox root is not a directory")
        if self.sandbox_dir.is_symlink() or getattr(self.sandbox_dir, "is_junction", lambda: False)():
            raise SandboxSafetyError("Refusing to recover a symlink or junction sandbox root")
        resolved = self.sandbox_dir.resolve()
        if resolved.parent == resolved:
            raise SandboxSafetyError("Sandbox path cannot be the filesystem root")
        if not self.marker_path.exists() or self.marker_path.is_symlink():
            raise SandboxSafetyError("Incomplete sandbox marker must be a regular file")
        if not self.marker_path.is_file():
            raise SandboxSafetyError("Incomplete sandbox marker must be a regular file")
        try:
            marker = parse_strict_json(self.marker_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SandboxSafetyError(f"Corrupted demo sandbox marker: {exc}") from exc
        if not isinstance(marker, dict):
            raise SandboxSafetyError("Incomplete sandbox marker must be a JSON object")
        if (
            marker.get("mode") != "DEMO"
            or marker.get("production") is not False
            or marker.get("schema_version") != 1
            # Older interrupted OS-007 initializations predate the explicit
            # field; absence is conservatively treated as incomplete only on
            # this dedicated recovery path.
            or marker.get("initialized", False) is not False
            or marker.get("id_mapping") != DEMO_TO_INTERNAL_ID
        ):
            raise SandboxSafetyError("Marker is not a recoverable incomplete demo marker")
        try:
            children = list(self.sandbox_dir.iterdir())
        except OSError as exc:
            raise SandboxSafetyError("Cannot inspect incomplete sandbox contents") from exc
        allowed = {MARKER_FILE_NAME, "catalog"}
        if {child.name for child in children} - allowed:
            raise SandboxSafetyError("Refusing to recover sandbox containing unexpected files")
        if not self.catalog_root.exists() or not self.catalog_root.is_dir() or self.catalog_root.is_symlink():
            raise SandboxSafetyError("Incomplete sandbox catalog must be a real directory")
        if getattr(self.catalog_root, "is_junction", lambda: False)():
            raise SandboxSafetyError("Refusing to recover a junctioned catalog directory")
        for root, dirs, files in os.walk(self.catalog_root, followlinks=False):
            for name in [*dirs, *files]:
                candidate = Path(root) / name
                if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                    raise SandboxSafetyError("Refusing to recover sandbox containing symlinked state")
        return marker

    def _write_marker(self) -> None:
        """Write a clean safety marker file."""
        marker_data = {
            "mode": "DEMO",
            "production": False,
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "warning": "ASTRAZIT MUSIC OS LOCAL DEMO SANDBOX. NON-PRODUCTION DATA ONLY.",
            "id_mapping": copy.deepcopy(DEMO_TO_INTERNAL_ID),
            "initialized": False,
        }
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        content = json.dumps(marker_data, indent=2) + "\n"
        self.marker_path.write_text(content, encoding="utf-8")

    def init(self, force: bool = False) -> dict[str, int]:
        """Initialize a fresh demo sandbox with sample fixtures.

        Args:
            force: If True, allow resetting an existing valid demo sandbox.

        Returns:
            Dict containing counts of initialized entities.
        """
        if self.sandbox_dir.exists():
            if self.marker_path.exists():
                if not force:
                    raise CatalogConflictError(
                        f"Demo sandbox already exists at {self.sandbox_dir}. Use --force or reset to re-initialize."
                    )
                # Safe to clean only after validating either a ready marker or
                # the narrow recoverable-incomplete marker contract.
                try:
                    self._read_marker()
                    self._safe_wipe_sandbox()
                except SandboxSafetyError:
                    self._verify_recoverable_incomplete_sandbox()
                    self._safe_wipe_sandbox(allow_incomplete=True)
            else:
                # Directory exists but lacks marker - dangerous! Refuse to overwrite.
                raise SandboxSafetyError(
                    f"Target directory {self.sandbox_dir} exists but does not contain a demo safety marker ({MARKER_FILE_NAME}). Refusing to overwrite potentially critical directory."
                )

        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._write_marker()

        # Re-instantiate repository
        self._repository = LocalJsonCatalogRepository(
            self.catalog_root, validator=self.validator
        )

        fixtures = get_all_demo_fixtures()

        # 1. Insert Works
        for work in fixtures["works"]:
            self.repository.create(EntityType.WORK, work)

        # 2. Insert Recordings
        for rec in fixtures["recordings"]:
            self.repository.create(EntityType.RECORDING, rec)

        # 3. Insert Releases
        for rel in fixtures["releases"]:
            self.repository.create(EntityType.RELEASE, rel)

        marker_data = parse_strict_json(self.marker_path.read_text(encoding="utf-8"))
        marker_data["initialized"] = True
        self.marker_path.write_text(json.dumps(marker_data, indent=2) + "\n", encoding="utf-8")

        return {
            "works": len(fixtures["works"]),
            "recordings": len(fixtures["recordings"]),
            "releases": len(fixtures["releases"]),
        }

    def _safe_wipe_sandbox(self, allow_incomplete: bool = False) -> None:
        """Safely wipe the sandbox directory after verifying marker safety."""
        # Double check marker
        marker = (
            self._verify_recoverable_incomplete_sandbox()
            if allow_incomplete
            else self._read_marker()
        )
        if marker.get("mode") != "DEMO" or marker.get("production") is not False:
            raise SandboxSafetyError("Refusing to wipe: not a verified DEMO directory.")

        resolved_sandbox = self.sandbox_dir.resolve()
        is_junction = getattr(self.sandbox_dir, "is_junction", lambda: False)()
        if self.sandbox_dir.is_symlink() or is_junction:
            raise SandboxSafetyError("Refusing to wipe a symlink or junction sandbox root")
        if resolved_sandbox.parent == resolved_sandbox:
            raise SandboxSafetyError(
                f"Sandbox path {resolved_sandbox} cannot be the filesystem root"
            )
        children = list(resolved_sandbox.iterdir())
        allowed = {self.marker_path.name, self.catalog_root.name}
        if any(child.name not in allowed for child in children):
            raise SandboxSafetyError("Refusing to wipe sandbox containing unexpected files")
        if self.catalog_root.is_symlink() or self.marker_path.is_symlink():
            raise SandboxSafetyError("Refusing to wipe sandbox containing symlinked state")
        if self.catalog_root.exists():
            shutil.rmtree(self.catalog_root)
        self.marker_path.unlink(missing_ok=True)
        self.sandbox_dir.rmdir()
        self._repository = None

    def reset(self, confirmed: bool = False, recreate: bool = False) -> None:
        """Reset and wipe the demo sandbox.

        Args:
            confirmed: Must be True (e.g. from --yes) to proceed.
            recreate: If True, re-run init immediately after wipe.
        """
        if not confirmed:
            raise SandboxSafetyError(
                "Reset requires explicit confirmation (pass confirmed=True or --yes flag)."
            )
        if not self.sandbox_dir.exists():
            return
        if not self.marker_path.exists():
            raise SandboxSafetyError(
                f"Cannot reset {self.sandbox_dir}: missing demo marker ({MARKER_FILE_NAME}). Safety boundary prevented deletion."
            )

        try:
            self._safe_wipe_sandbox()
        except SandboxSafetyError:
            self._verify_recoverable_incomplete_sandbox()
            self._safe_wipe_sandbox(allow_incomplete=True)
        if recreate:
            self.init(force=True)

    def summary(self) -> dict[str, Any]:
        """Inspect and return summary statistics for the sandbox."""
        self._read_marker()

        work_ids = self.repository.list_ids(EntityType.WORK)
        rec_ids = self.repository.list_ids(EntityType.RECORDING)
        rel_ids = self.repository.list_ids(EntityType.RELEASE)

        works = [self.repository.get(EntityType.WORK, wid) for wid in work_ids]
        recs = [self.repository.get(EntityType.RECORDING, rid) for rid in rec_ids]
        rels = [self.repository.get(EntityType.RELEASE, rlid) for rlid in rel_ids]

        work_rights = {}
        for w in works:
            st = w["composition_rights"]["approval_status"]
            work_rights[st] = work_rights.get(st, 0) + 1

        rec_rights = {}
        radio_eligible_count = 0
        radio_ineligible_count = 0
        for r in recs:
            st = r["master_rights"]["approval_status"]
            rec_rights[st] = rec_rights.get(st, 0) + 1
            if r.get("radio", {}).get("radio_eligible") is True:
                radio_eligible_count += 1
            else:
                radio_ineligible_count += 1

        rel_lifecycle = {}
        for rel in rels:
            st = rel["lifecycle_status"]
            rel_lifecycle[st] = rel_lifecycle.get(st, 0) + 1

        return {
            "sandbox_path": str(self.sandbox_dir),
            "counts": {
                "works": len(works),
                "recordings": len(recs),
                "releases": len(rels),
            },
            "composition_rights": work_rights,
            "master_rights": rec_rights,
            "radio": {
                "eligible": radio_eligible_count,
                "ineligible": radio_ineligible_count,
            },
            "release_lifecycle": rel_lifecycle,
        }

    def list_entities(self, entity_type: Union[EntityType, str]) -> list[dict[str, Any]]:
        """List entities of the given type with translated demo IDs and summary attributes."""
        self._read_marker()
        etype = EntityType.from_value(entity_type)
        internal_ids = self.repository.list_ids(etype)

        results = []
        for iid in internal_ids:
            doc = self.repository.get(etype, iid)
            demo_id = self.to_demo_id(iid)
            if etype == EntityType.WORK:
                results.append({
                    "demo_id": demo_id,
                    "internal_id": iid,
                    "title": doc.get("canonical_title"),
                    "origin": doc.get("catalog_origin"),
                    "lifecycle": doc.get("lifecycle_status"),
                    "rights": doc["composition_rights"]["approval_status"],
                })
            elif etype == EntityType.RECORDING:
                work_demo_id = self.to_demo_id(doc.get("astrazit_work_id", ""))
                radio_info = doc.get("radio", {})
                results.append({
                    "demo_id": demo_id,
                    "internal_id": iid,
                    "title": f"{doc.get('recording_title')} -- {doc.get('version')}",
                    "work_id": work_demo_id,
                    "origin": doc.get("catalog_origin"),
                    "lifecycle": doc.get("lifecycle_status"),
                    "rights": doc["master_rights"]["approval_status"],
                    "radio": "ELIGIBLE" if radio_info.get("radio_eligible") else "INELIGIBLE",
                    "rotation": radio_info.get("rotation_tier", "-"),
                })
            elif etype == EntityType.RELEASE:
                track_demo_ids = [
                    self.to_demo_id(t["astrazit_recording_id"])
                    for t in doc.get("tracklist", [])
                ]
                results.append({
                    "demo_id": demo_id,
                    "internal_id": iid,
                    "title": doc.get("title"),
                    "type": doc.get("release_type"),
                    "origin": doc.get("catalog_origin"),
                    "lifecycle": doc.get("lifecycle_status"),
                    "tracks_count": len(track_demo_ids),
                    "tracks": track_demo_ids,
                })
        return results

    def get_entity(self, identifier: str) -> tuple[EntityType, dict[str, Any]]:
        """Retrieve entity by public DEMO ID (or internal AST ID)."""
        self._read_marker()
        internal_id = self.to_internal_id(identifier)
        etype = self._detect_entity_type(internal_id)
        doc = self.repository.get(etype, internal_id)
        return etype, doc

    def validate(self) -> dict[str, Any]:
        """Validate repository records, referential integrity, and demo ID mapping."""
        marker = self._read_marker()
        stored_mapping = marker.get("id_mapping", {})

        issues = []
        if stored_mapping != DEMO_TO_INTERNAL_ID:
            issues.append("Demo ID mapping does not match the canonical fixture mapping")
        if len(set(stored_mapping.values())) != len(stored_mapping):
            issues.append("Demo ID mapping contains duplicate internal IDs")

        # Validate through repository list_ids and get
        for etype in (EntityType.WORK, EntityType.RECORDING, EntityType.RELEASE):
            try:
                ids = self.repository.list_ids(etype)
                prefixes = {
                    EntityType.WORK: "AST-WRK-",
                    EntityType.RECORDING: "AST-REC-",
                    EntityType.RELEASE: "AST-REL-",
                }
                expected_ids = {
                    iid for iid in INTERNAL_TO_DEMO_ID
                    if iid.startswith(prefixes[etype])
                }
                if set(ids) != expected_ids:
                    issues.append(f"{etype.value} repository IDs do not match demo mapping")
                for iid in ids:
                    doc = self.repository.get(etype, iid)
                    # Run Draft 2020-12 and business rules
                    errs = self.validator.validate_record(etype, doc)
                    if errs:
                        issues.extend(f"{iid}: {e}" for e in errs)
            except Exception as exc:
                issues.append(f"{etype.value} validation error: {exc}")

        # Check cross-entity references
        try:
            rec_ids = self.repository.list_ids(EntityType.RECORDING)
            for rid in rec_ids:
                rec = self.repository.get(EntityType.RECORDING, rid)
                wid = rec["astrazit_work_id"]
                if not self.repository.exists(EntityType.WORK, wid):
                    issues.append(f"Recording {rid} references missing Work {wid}")

            rel_ids = self.repository.list_ids(EntityType.RELEASE)
            for rlid in rel_ids:
                rel = self.repository.get(EntityType.RELEASE, rlid)
                for track in rel.get("tracklist", []):
                    tr_id = track["astrazit_recording_id"]
                    if not self.repository.exists(EntityType.RECORDING, tr_id):
                        issues.append(f"Release {rlid} references missing Recording {tr_id}")
        except Exception as exc:
            issues.append(f"Referential validation error: {exc}")

        is_valid = len(issues) == 0
        return {
            "valid": is_valid,
            "issues": issues,
        }

    def to_internal_id(self, demo_or_internal_id: str) -> str:
        """Translate public DEMO ID or pass-through valid internal AST ID."""
        if not isinstance(demo_or_internal_id, str):
            raise DemoMappingError(f"ID must be string, got {type(demo_or_internal_id).__name__}")
        trimmed = demo_or_internal_id.strip()
        if trimmed in DEMO_TO_INTERNAL_ID:
            return DEMO_TO_INTERNAL_ID[trimmed]
        if trimmed in INTERNAL_TO_DEMO_ID:
            return trimmed
        raise DemoMappingError(
            f"Unknown or invalid demo identifier: {demo_or_internal_id!r}. "
            f"Valid demo IDs start with DEMO-WRK-, DEMO-REC-, or DEMO-REL-."
        )

    def to_demo_id(self, internal_or_demo_id: str) -> str:
        """Translate internal AST ID to public DEMO ID, or pass-through DEMO ID."""
        if not isinstance(internal_or_demo_id, str):
            raise DemoMappingError(f"ID must be string, got {type(internal_or_demo_id).__name__}")
        trimmed = internal_or_demo_id.strip()
        if trimmed in INTERNAL_TO_DEMO_ID:
            return INTERNAL_TO_DEMO_ID[trimmed]
        if trimmed in DEMO_TO_INTERNAL_ID:
            return trimmed
        return trimmed

    def _detect_entity_type(self, internal_id: str) -> EntityType:
        if internal_id.startswith("AST-WRK-"):
            return EntityType.WORK
        if internal_id.startswith("AST-REC-"):
            return EntityType.RECORDING
        if internal_id.startswith("AST-REL-"):
            return EntityType.RELEASE
        raise DemoMappingError(f"Cannot determine entity type from ID: {internal_id!r}")
