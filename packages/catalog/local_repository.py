"""Local durable JSON filesystem implementation of CatalogRepository.

Governed by ADR-001, ADR-003, ADR-012, ADR-014, and OS-005.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Union

from packages.catalog.identifiers import (
    EntityType,
    ID_PATTERNS,
    parse_identifier,
)
from packages.catalog.repository import (
    CatalogConflictError,
    CatalogError,
    CatalogIntegrityError,
    CatalogNotFoundError,
    CatalogPersistenceError,
    CatalogRepository,
    CatalogStateError,
    CatalogValidationError,
)
from packages.catalog.sequence_store import FileLock
from packages.catalog.validation import (
    CatalogValidator,
    get_default_validator,
    parse_strict_json,
)

ENTITY_DIRS = {
    EntityType.WORK: "works",
    EntityType.RECORDING: "recordings",
    EntityType.RELEASE: "releases",
}

ID_FIELD_NAMES = {
    EntityType.WORK: "astrazit_work_id",
    EntityType.RECORDING: "astrazit_recording_id",
    EntityType.RELEASE: "astrazit_release_id",
}


def _json_serial_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        # Format Decimal cleanly without scientific notation if possible
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dump_deterministic_json(data: Any) -> str:
    """Serialize dictionary deterministically to formatted JSON."""
    return json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
        default=_json_serial_default,
    ) + "\n"


class LocalJsonCatalogRepository(CatalogRepository):
    """Local durable filesystem repository storing canonical entities as JSON documents.

    Directory layout:
        root/
            works/
                AST-WRK-000001.json
            recordings/
                AST-REC-000001.json
            releases/
                AST-REL-000001.json
            .locks/
                catalog.lock
    """

    def __init__(
        self,
        root_dir: Union[Path, str],
        validator: Optional[CatalogValidator] = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.validator = validator or get_default_validator()
        self.lock_dir = self.root_dir / ".locks"
        self.lock_path = self.lock_dir / "catalog.lock"
        self._lock = FileLock(self.lock_path)
        # FileLock owns one OS handle; serialize this instance's callers so
        # concurrent threads cannot overwrite its descriptor bookkeeping.
        self._thread_lock = threading.RLock()

        # Ensure entity subdirectories exist
        for subdir in ENTITY_DIRS.values():
            (self.root_dir / subdir).mkdir(parents=True, exist_ok=True)
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _catalog_lock(self):
        with self._thread_lock:
            self._lock.acquire()
            try:
                yield
            finally:
                self._lock.release()

    def _resolve_entity_type(self, entity_type: Union[EntityType, str]) -> EntityType:
        try:
            return EntityType.from_value(entity_type)
        except Exception as exc:
            raise CatalogValidationError(f"Invalid entity type: {entity_type!r}") from exc

    def _validate_ast_id(self, entity_type: EntityType, ast_id: str) -> None:
        if not isinstance(ast_id, str):
            raise CatalogValidationError(f"AST ID must be a string, got {type(ast_id).__name__}")
        pattern = ID_PATTERNS.get(entity_type)
        if not pattern or not pattern.fullmatch(ast_id):
            raise CatalogValidationError(
                f"AST ID {ast_id!r} does not match required pattern for {entity_type.value}"
            )

    def _entity_dir(self, entity_type: EntityType) -> Path:
        return self.root_dir / ENTITY_DIRS[entity_type]

    def _entity_file_path(self, entity_type: EntityType, ast_id: str) -> Path:
        self._validate_ast_id(entity_type, ast_id)
        # Safe from path traversal because _validate_ast_id ensures strictly AST-(WRK|REC|REL)-[0-9]{6}
        return self._entity_dir(entity_type) / f"{ast_id}.json"

    def _read_and_verify_file(
        self,
        entity_type: EntityType,
        ast_id: str,
        file_path: Path,
    ) -> dict[str, Any]:
        """Read and strictly validate a persisted file from disk. Fail closed if corrupted."""
        if not file_path.exists():
            raise CatalogNotFoundError(f"{entity_type.value} record not found: {ast_id}")

        try:
            raw_bytes = file_path.read_bytes()
        except OSError as exc:
            raise CatalogStateError(f"Failed to read file {file_path}: {exc}") from exc

        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CatalogStateError(f"Invalid UTF-8 in {file_path}: {exc}") from exc

        try:
            data = parse_strict_json(raw_text)
        except Exception as exc:
            raise CatalogStateError(f"Malformed JSON in {file_path}: {exc}") from exc

        if not isinstance(data, dict):
            raise CatalogStateError(f"Root of {file_path} must be a JSON object, got {type(data).__name__}")

        id_field = ID_FIELD_NAMES[entity_type]
        if data.get(id_field) != ast_id:
            raise CatalogStateError(
                f"File content ID mismatch in {file_path}: expected {ast_id}, got {data.get(id_field)!r}"
            )

        # Validate schema
        errors = self.validator.validate_record(entity_type, data)
        if errors:
            raise CatalogStateError(
                f"Persisted record in {file_path} violates schema: {'; '.join(errors)}"
            )

        return data

    def _check_referential_integrity(
        self,
        entity_type: EntityType,
        record: dict[str, Any],
    ) -> None:
        """Verify cross-entity references within lock.

        RECORDING -> WORK: astrazit_work_id must exist as a WORK.
        RELEASE -> RECORDING: all astrazit_recording_id in tracklist must exist as RECORDINGS.
        """
        if entity_type == EntityType.RECORDING:
            work_id = record.get("astrazit_work_id")
            if not isinstance(work_id, str):
                raise CatalogValidationError(f"Recording missing or invalid astrazit_work_id: {work_id!r}")
            # Must match AST-WRK pattern
            if not ID_PATTERNS[EntityType.WORK].fullmatch(work_id):
                raise CatalogIntegrityError(
                    f"Recording references invalid work ID: {work_id!r}"
                )
            # Check existence of work
            work_file = self._entity_file_path(EntityType.WORK, work_id)
            if not work_file.exists():
                raise CatalogIntegrityError(
                    f"Referenced Work {work_id} does not exist in repository"
                )
            # Verify the referenced work is not corrupted
            work = self._read_and_verify_file(EntityType.WORK, work_id, work_file)
            if record.get("lifecycle_status") in ("RELEASE_READY", "RELEASED"):
                historical_released = (
                    record.get("catalog_origin") == "HISTORICAL_IMPORT"
                    and record.get("lifecycle_status") == "RELEASED"
                )
                if not historical_released:
                    if record["master_rights"]["approval_status"] != "APPROVED":
                        raise CatalogIntegrityError(
                            "Recording release readiness requires APPROVED master rights"
                        )
                    if work["composition_rights"]["approval_status"] != "APPROVED":
                        raise CatalogIntegrityError(
                            "Recording release readiness requires APPROVED composition rights"
                        )

        elif entity_type == EntityType.RELEASE:
            tracklist = record.get("tracklist")
            if not isinstance(tracklist, list) or not tracklist:
                raise CatalogValidationError("Release tracklist must be a non-empty array")
            referenced_recordings = []
            for idx, track in enumerate(tracklist):
                if not isinstance(track, dict):
                    raise CatalogValidationError(f"Track at index {idx} must be an object")
                rec_id = track.get("astrazit_recording_id")
                if not isinstance(rec_id, str):
                    raise CatalogValidationError(f"Track at index {idx} has invalid recording ID: {rec_id!r}")
                if not ID_PATTERNS[EntityType.RECORDING].fullmatch(rec_id):
                    raise CatalogIntegrityError(
                        f"Release track {idx} references invalid recording ID: {rec_id!r}"
                    )
                rec_file = self._entity_file_path(EntityType.RECORDING, rec_id)
                if not rec_file.exists():
                    raise CatalogIntegrityError(
                        f"Referenced Recording {rec_id} does not exist in repository"
                    )
                # Verify the recording and its own Work reference.
                referenced = self._read_and_verify_file(EntityType.RECORDING, rec_id, rec_file)
                self._check_referential_integrity(EntityType.RECORDING, referenced)
                referenced_recordings.append(referenced)
            if record.get("lifecycle_status") in ("RELEASE_READY", "RELEASED"):
                historical_released = (
                    record.get("catalog_origin") == "HISTORICAL_IMPORT"
                    and record.get("lifecycle_status") == "RELEASED"
                )
                if not historical_released:
                    if record["provenance"]["approval_status"] != "APPROVED":
                        raise CatalogIntegrityError(
                            "Release release readiness requires APPROVED provenance"
                        )
                    for referenced in referenced_recordings:
                        work_id = referenced["astrazit_work_id"]
                        work = self._read_and_verify_file(
                            EntityType.WORK, work_id,
                            self._entity_file_path(EntityType.WORK, work_id),
                        )
                        if referenced["master_rights"]["approval_status"] != "APPROVED":
                            raise CatalogIntegrityError(
                                "Release release readiness requires APPROVED master rights"
                            )
                        if work["composition_rights"]["approval_status"] != "APPROVED":
                            raise CatalogIntegrityError(
                                "Release release readiness requires APPROVED composition rights"
                            )

    def _write_record_atomic(
        self,
        entity_type: EntityType,
        ast_id: str,
        record: dict[str, Any],
        expect_exists: bool,
    ) -> None:
        """Atomically persist record under file lock.

        If expect_exists is False (create), verify absence before write.
        If expect_exists is True (update), verify presence before write.
        """
        dest_path = self._entity_file_path(entity_type, ast_id)
        exists_now = dest_path.exists()

        if not expect_exists and exists_now:
            raise CatalogConflictError(
                f"Cannot create {entity_type.value}: record {ast_id} already exists"
            )
        if expect_exists and not exists_now:
            raise CatalogNotFoundError(
                f"Cannot update {entity_type.value}: record {ast_id} not found"
            )

        # Write to temporary file in same directory
        target_dir = dest_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        serialized = _dump_deterministic_json(record).encode("utf-8")

        temp_path = None
        fd = None
        try:
            fd, temp_path_str = tempfile.mkstemp(
                prefix=f".{ast_id}_tmp_",
                dir=str(target_dir),
            )
            temp_path = Path(temp_path_str)
            try:
                with os.fdopen(fd, "wb") as f:
                    fd = None  # fd ownership transferred to file object
                    f.write(serialized)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if temp_path is not None:
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                raise

            # Double check existence condition right before replace
            if not expect_exists and dest_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                raise CatalogConflictError(
                    f"Cannot create {entity_type.value}: record {ast_id} already exists"
                )

            os.replace(str(temp_path), str(dest_path))


        except (CatalogConflictError, CatalogNotFoundError):
            raise
        except Exception as exc:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise CatalogPersistenceError(
                f"Failed to persist {entity_type.value} {ast_id}: {exc}"
            ) from exc

    def create(self, entity_type: Union[EntityType, str], record: dict[str, Any]) -> dict[str, Any]:
        """Validate, verify referential integrity, and persist a new canonical record."""
        etype = self._resolve_entity_type(entity_type)
        if not isinstance(record, dict):
            raise CatalogValidationError(f"Record must be a dict, got {type(record).__name__}")

        # Deep copy input so caller cannot mutate while we validate
        incoming = copy.deepcopy(record)

        # Schema validation
        errors = self.validator.validate_record(etype, incoming)
        if errors:
            raise CatalogValidationError(f"Record failed schema validation: {'; '.join(errors)}")

        # ID extraction & entity match
        try:
            ast_id = self.validator.extract_ast_id(etype, incoming)
        except ValueError as exc:
            raise CatalogValidationError(str(exc)) from exc

        # Lock critical section for referential integrity check and atomic write
        try:
            with self._catalog_lock():
                self._check_referential_integrity(etype, incoming)
                self._write_record_atomic(etype, ast_id, incoming, expect_exists=False)
        except (CatalogError, CatalogValidationError, CatalogConflictError, CatalogIntegrityError):
            raise
        except Exception as exc:
            raise CatalogPersistenceError(f"Persistence error during create: {exc}") from exc

        return copy.deepcopy(incoming)

    def get(self, entity_type: Union[EntityType, str], ast_id: str) -> dict[str, Any]:
        """Retrieve a canonical record by AST identity. Returns a deep copy."""
        etype = self._resolve_entity_type(entity_type)
        self._validate_ast_id(etype, ast_id)
        file_path = self._entity_file_path(etype, ast_id)

        try:
            with self._catalog_lock():
                data = self._read_and_verify_file(etype, ast_id, file_path)
        except (CatalogNotFoundError, CatalogStateError, CatalogValidationError):
            raise
        except Exception as exc:
            raise CatalogStateError(f"Failed to retrieve {ast_id}: {exc}") from exc

        return copy.deepcopy(data)

    def update(self, entity_type: Union[EntityType, str], ast_id: str, record: dict[str, Any]) -> dict[str, Any]:
        """Validate, verify immutable identity, check referential integrity, and replace an existing record."""
        etype = self._resolve_entity_type(entity_type)
        self._validate_ast_id(etype, ast_id)
        if not isinstance(record, dict):
            raise CatalogValidationError(f"Record must be a dict, got {type(record).__name__}")

        incoming = copy.deepcopy(record)

        # Schema validation
        errors = self.validator.validate_record(etype, incoming)
        if errors:
            raise CatalogValidationError(f"Proposed update failed schema validation: {'; '.join(errors)}")

        # Verify AST ID in incoming record matches ast_id argument
        try:
            record_id = self.validator.extract_ast_id(etype, incoming)
        except ValueError as exc:
            raise CatalogValidationError(str(exc)) from exc

        if record_id != ast_id:
            raise CatalogValidationError(
                f"Proposed update cannot mutate identity: record ID {record_id} does not match {ast_id}"
            )

        try:
            with self._catalog_lock():
                # Ensure record exists and is valid
                dest_path = self._entity_file_path(etype, ast_id)
                self._read_and_verify_file(etype, ast_id, dest_path)

                # Check referential integrity
                self._check_referential_integrity(etype, incoming)

                # Persist replacement
                self._write_record_atomic(etype, ast_id, incoming, expect_exists=True)
        except (CatalogError, CatalogValidationError, CatalogNotFoundError, CatalogIntegrityError):
            raise
        except Exception as exc:
            raise CatalogPersistenceError(f"Persistence error during update: {exc}") from exc

        return copy.deepcopy(incoming)

    def exists(self, entity_type: Union[EntityType, str], ast_id: str) -> bool:
        """Check if a canonical entity ID exists in the repository without mutating state."""
        etype = self._resolve_entity_type(entity_type)
        self._validate_ast_id(etype, ast_id)
        file_path = self._entity_file_path(etype, ast_id)

        try:
            with self._catalog_lock():
                if not file_path.exists():
                    return False
                # Verify that it is valid canonical record
                self._read_and_verify_file(etype, ast_id, file_path)
                return True
        except CatalogStateError:
            # Corrupted record must fail closed
            raise
        except Exception as exc:
            raise CatalogStateError(f"Error checking existence for {ast_id}: {exc}") from exc

    def list_ids(self, entity_type: Union[EntityType, str]) -> list[str]:
        """Return a sorted list of canonical AST IDs for the given entity type."""
        etype = self._resolve_entity_type(entity_type)
        target_dir = self._entity_dir(etype)

        try:
            with self._catalog_lock():
                if not target_dir.exists():
                    return []

                ids: list[str] = []
                for entry in sorted(target_dir.iterdir()):
                    if entry.is_file() and not entry.name.startswith("."):
                        if not entry.name.endswith(".json"):
                            raise CatalogStateError(
                                f"Unexpected non-JSON file {entry.name} in {target_dir}"
                            )
                        stem_id = entry.stem
                        try:
                            self._validate_ast_id(etype, stem_id)
                        except CatalogValidationError as exc:
                            raise CatalogStateError(
                                f"Storage corruption: filename {entry.name} does not have valid AST ID stem: {exc}"
                            ) from exc
                        # Verify file content
                        self._read_and_verify_file(etype, stem_id, entry)
                        ids.append(stem_id)


                return sorted(ids)
        except (CatalogValidationError, CatalogStateError):
            raise
        except Exception as exc:
            raise CatalogStateError(f"Failed to list IDs for {etype.value}: {exc}") from exc
