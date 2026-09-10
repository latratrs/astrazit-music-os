"""Offline Draft 2020-12 JSON schema validation for AstraZit Music OS catalog entities.

Governed by ADR-009, ADR-012, OS-003, and OS-005.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from packages.catalog.identifiers import (
    EntityType,
    ID_PATTERNS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "packages" / "schemas"
DIALECT = "https://json-schema.org/draft/2020-12/schema"

SCHEMA_NAMES = {
    EntityType.WORK: "work.schema.json",
    EntityType.RECORDING: "recording.schema.json",
    EntityType.RELEASE: "release.schema.json",
}
EXPECTED_SCHEMA_NAMES = {
    "asset-reference.schema.json", "distribution-record.schema.json",
    "event-envelope.schema.json", "metadata-provenance.schema.json",
    "radio-profile.schema.json", "recording.schema.json",
    "release.schema.json", "revenue-record.schema.json",
    "rights.schema.json", "work.schema.json",
}

ID_KEYS = {
    EntityType.WORK: "astrazit_work_id",
    EntityType.RECORDING: "astrazit_recording_id",
    EntityType.RELEASE: "astrazit_release_id",
}


def reject_json_constant(value: Any) -> None:
    """Reject non-standard JSON numeric constants (NaN, Infinity, -Infinity)."""
    raise ValueError(f"Non-standard JSON numeric constant rejected: {value!r}")


def unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Strict dict constructor rejecting duplicate JSON object keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key!r}")
        result[key] = value
    return result


def parse_strict_json(content: str) -> Any:
    """Parse JSON string with strict checks against duplicate keys, NaN, and Infinity."""
    return json.loads(
        content,
        parse_float=Decimal,
        parse_constant=reject_json_constant,
        object_pairs_hook=unique_json_pairs,
    )


class CatalogValidator:
    """Offline Draft 2020-12 validator for canonical catalog records.

    Caches schema definitions and registry offline with zero network calls.
    """

    def __init__(self, schemas_dir: Optional[Path] = None) -> None:
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry, Resource

        self.schemas_dir = Path(schemas_dir or SCHEMAS_DIR)
        self._schemas: dict[str, dict[str, Any]] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        registry = Registry()

        expected_names = EXPECTED_SCHEMA_NAMES
        found_names = {path.name for path in self.schemas_dir.glob("*.schema.json")}
        if found_names != expected_names:
            raise ValueError(
                f"Schema set mismatch; missing={sorted(expected_names - found_names)}, "
                f"extra={sorted(found_names - expected_names)}"
            )
        schema_ids: set[str] = set()

        for path in sorted(self.schemas_dir.glob("*.schema.json")):
            data = parse_strict_json(path.read_text(encoding="utf-8"))
            if data.get("$schema") != DIALECT:
                raise ValueError(f"{path.name}: wrong schema dialect {data.get('$schema')}")
            expected_id = "https://schemas.astrazit.com/v1/" + path.name
            if data.get("$id") != expected_id or expected_id in schema_ids:
                raise ValueError(f"{path.name}: invalid schema ID {data.get('$id')}")
            Draft202012Validator.check_schema(data)
            self._schemas[path.name] = data
            schema_ids.add(expected_id)
            registry = registry.with_resource(expected_id, Resource.from_contents(data))

        self.registry = registry

        for name, schema in self._schemas.items():
            resolver = registry.resolver(schema["$id"])
            for node in _walk_schema(schema):
                if "$ref" in node:
                    resolver.lookup(node["$ref"])

        format_checker = FormatChecker()
        for required in ("date", "date-time", "uri"):
            if required not in format_checker.checkers:
                raise RuntimeError(f"Missing {required} checker in jsonschema FormatChecker")

        for name, schema in self._schemas.items():
            self._validators[name] = Draft202012Validator(
                schema,
                registry=self.registry,
                format_checker=format_checker,
            )

    def validate_record(self, entity_type: EntityType, record: dict[str, Any]) -> list[str]:
        """Validate record against the Draft 2020-12 schema for the entity type.

        Returns a list of validation error message strings (empty list if valid).
        """
        schema_name = SCHEMA_NAMES[entity_type]
        validator = self._validators[schema_name]
        errors = sorted(validator.iter_errors(record), key=lambda e: (e.json_path, e.message))
        messages = [f"{e.json_path}: {e.message}" for e in errors]
        if messages:
            return messages

        # Apply the same deterministic, non-structural rules as the OS-003
        # validator. Cross-record rights/reference checks remain the repository's
        # responsibility because this class has no catalog context.
        from scripts.validate_schemas import (
            check_history,
            check_provenance_integrity,
            split_errors,
        )
        semantic: list[str] = []
        if entity_type == EntityType.WORK:
            rights = record["composition_rights"]
            for group in ("writers", "publishers"):
                semantic.extend(split_errors(rights[group], group))
            check_history(record, rights["approval_status"] != "APPROVED", semantic)
            check_provenance_integrity(record, semantic)
        elif entity_type == EntityType.RECORDING:
            semantic.extend(split_errors(record["master_rights"]["owners"], "master owners"))
            for name in ("intro_duration_seconds", "outro_duration_seconds"):
                if record.get("radio", {}).get(name, 0) > record["music"]["duration_seconds"]:
                    semantic.append(f"radio.{name} exceeds track duration")
            check_provenance_integrity(record, semantic)
        elif entity_type == EntityType.RELEASE:
            positions = [(track.get("disc_number", 1), track["track_number"])
                         for track in record["tracklist"]]
            if len(positions) != len(set(positions)):
                semantic.append("tracklist: duplicate disc/track position")
        return sorted(semantic)

    def extract_ast_id(self, entity_type: EntityType, record: dict[str, Any]) -> str:
        """Extract and validate the canonical AST ID from a record dict."""
        id_key = ID_KEYS[entity_type]
        if id_key not in record:
            raise ValueError(f"Record is missing canonical identifier field '{id_key}'")
        val = record[id_key]
        if not isinstance(val, str):
            raise ValueError(f"Canonical identifier '{id_key}' must be a string, got {type(val).__name__}")
        if not ID_PATTERNS[entity_type].fullmatch(val):
            raise ValueError(
                f"Canonical identifier {val!r} does not match required pattern for {entity_type.value}"
            )
        return val


def _walk_schema(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_schema(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_schema(child)


_DEFAULT_VALIDATOR: Optional[CatalogValidator] = None


def get_default_validator() -> CatalogValidator:
    """Return a singleton instance of CatalogValidator."""
    global _DEFAULT_VALIDATOR
    if _DEFAULT_VALIDATOR is None:
        _DEFAULT_VALIDATOR = CatalogValidator()
    return _DEFAULT_VALIDATOR
