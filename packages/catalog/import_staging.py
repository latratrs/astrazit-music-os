"""Deterministic, non-canonical staging for historical catalog imports.

This module never allocates AST identifiers and never writes canonical records.
It converts a narrowly defined source CSV into a review manifest whose enriched
metadata, radio programming, rights, and readiness fields remain provisional.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional


class ImportStagingError(ValueError):
    """Raised when source data cannot be staged without assumptions."""


CSV_FIELDS = (
    "song",
    "listeners",
    "streams",
    "saves",
    "release_date",
    "exact_music_genre",
    "radio_daypart",
    "genre_description",
)

DAYPARTS = {
    "AstraZit Sunrise (06:00–09:00)": {
        "key": "SUNRISE", "label": "AstraZit Sunrise", "start": "06:00", "end": "09:00"
    },
    "AstraZit Day (09:00–12:00)": {
        "key": "DAY", "label": "AstraZit Day", "start": "09:00", "end": "12:00"
    },
    "AstraZit Future (12:00–17:00)": {
        "key": "FUTURE", "label": "AstraZit Future", "start": "12:00", "end": "17:00"
    },
    "AstraZit Sunset (17:00–21:00)": {
        "key": "SUNSET", "label": "AstraZit Sunset", "start": "17:00", "end": "21:00"
    },
    "AstraZit Night (21:00–02:00)": {
        "key": "NIGHT", "label": "AstraZit Night", "start": "21:00", "end": "02:00"
    },
    "AstraZit Deep Space (02:00–06:00)": {
        "key": "DEEP_SPACE", "label": "AstraZit Deep Space", "start": "02:00", "end": "06:00"
    },
}


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _identity_key(title: str) -> str:
    """Produce a review-only comparison key, never an AST identity input."""
    return " ".join(unicodedata.normalize("NFC", title).split()).casefold()


def _required_text(value: Optional[str], field: str, row_number: int) -> str:
    text = "" if value is None else value.strip()
    if not text:
        raise ImportStagingError(f"row {row_number}: {field} must be non-empty")
    return text


def _nonnegative_integer(value: Optional[str], field: str, row_number: int) -> int:
    text = _required_text(value, field, row_number)
    if not text.isascii() or not text.isdigit():
        raise ImportStagingError(f"row {row_number}: {field} must be a non-negative integer")
    return int(text)


def _release_date(value: Optional[str], row_number: int) -> str:
    text = _required_text(value, "release_date", row_number)
    try:
        parsed = datetime.strptime(text, "%m/%d/%Y")
    except ValueError as error:
        raise ImportStagingError(
            f"row {row_number}: release_date must use explicit M/D/YYYY source format"
        ) from error
    return parsed.date().isoformat()


def _read_source_rows(csv_path: Path) -> tuple[str, list[dict[str, str]]]:
    if not csv_path.is_file():
        raise ImportStagingError(f"catalog CSV does not exist: {csv_path}")
    source_hash = _source_sha256(csv_path)
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            headers = reader.fieldnames
            if headers is None:
                raise ImportStagingError("catalog CSV has no header row")
            if len(headers) != len(set(headers)):
                raise ImportStagingError("catalog CSV contains duplicate column names")
            if tuple(headers) != CSV_FIELDS:
                raise ImportStagingError(
                    f"catalog CSV columns must exactly equal {list(CSV_FIELDS)!r}; found {headers!r}"
                )
            rows = list(reader)
    except UnicodeDecodeError as error:
        raise ImportStagingError("catalog CSV must be UTF-8 or UTF-8 with BOM") from error
    if not rows:
        raise ImportStagingError("catalog CSV contains no data rows")
    if any(None in row for row in rows):
        raise ImportStagingError("catalog CSV contains data beyond the declared columns")
    return source_hash, rows


def build_staging_manifest(
    csv_path: Path | str,
    *,
    audio_qc_by_source_row: Optional[Mapping[int, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Build a review manifest without allocating IDs or asserting approvals."""
    path = Path(csv_path).resolve()
    source_hash, source_rows = _read_source_rows(path)
    qc_map = dict(audio_qc_by_source_row or {})
    valid_source_rows = set(range(2, len(source_rows) + 2))
    unknown_qc_rows = set(qc_map) - valid_source_rows
    if unknown_qc_rows:
        raise ImportStagingError(f"audio QC references unknown source rows: {sorted(unknown_qc_rows)}")

    staged: list[dict[str, Any]] = []
    title_groups: dict[str, list[int]] = defaultdict(list)
    for row_number, row in enumerate(source_rows, start=2):
        title = _required_text(row["song"], "song", row_number)
        genre = _required_text(row["exact_music_genre"], "exact_music_genre", row_number)
        genre_description = _required_text(
            row["genre_description"], "genre_description", row_number
        )
        daypart_source = _required_text(row["radio_daypart"], "radio_daypart", row_number)
        if daypart_source not in DAYPARTS:
            raise ImportStagingError(f"row {row_number}: unknown frozen daypart {daypart_source!r}")
        listeners = _nonnegative_integer(row["listeners"], "listeners", row_number)
        streams = _nonnegative_integer(row["streams"], "streams", row_number)
        saves = _nonnegative_integer(row["saves"], "saves", row_number)
        normalized_release_date = _release_date(row["release_date"], row_number)
        title_key = _identity_key(title)
        title_groups[title_key].append(row_number)

        qc = dict(qc_map[row_number]) if row_number in qc_map else None
        master_present = qc is not None
        master_valid = bool(qc and qc.get("master_valid") is True)
        audio_qc_pass = bool(qc and qc.get("audio_qc_pass") is True)
        derivative_required = qc.get("radio_derivative_required") if qc else None
        readiness = {
            "master_present": master_present,
            "master_valid": master_valid,
            "audio_qc_pass": audio_qc_pass,
            "radio_derivative_required": derivative_required,
            "rights_verified": False,
            "radio_cleared": False,
            "metadata_approved": False,
            "ready_for_radio": False,
        }
        staged.append(
            {
                "source_row": row_number,
                "source_row_id": f"SHA256:{source_hash}:ROW:{row_number}",
                "source_metadata": {
                    "song": title,
                    "listeners": listeners,
                    "streams": streams,
                    "saves": saves,
                    "release_date_source": row["release_date"].strip(),
                    "release_date_iso": normalized_release_date,
                },
                "identity": {
                    "status": "UNALLOCATED",
                    "astrazit_work_id": None,
                    "astrazit_recording_id": None,
                    "astrazit_release_id": None,
                    "artist": None,
                    "version": None,
                },
                "provisional_enrichment": {
                    "canonical_status": "PROVISIONAL",
                    "genre": genre,
                    "genre_description": genre_description,
                    "radio_daypart": dict(DAYPARTS[daypart_source]),
                    "rotation_tier": None,
                    "rotation_inputs": {
                        "listeners": listeners,
                        "streams": streams,
                        "saves": saves,
                    },
                },
                "rights_review": {
                    "composition_rights": "NOT_SUPPLIED",
                    "master_rights": "NOT_SUPPLIED",
                    "human_approval_required": True,
                },
                "audio_qc": qc,
                "readiness": readiness,
                "review_flags": [],
            }
        )

    duplicates = []
    by_row = {item["source_row"]: item for item in staged}
    for rows in title_groups.values():
        if len(rows) > 1:
            title = by_row[rows[0]]["source_metadata"]["song"]
            duplicates.append({"song": title, "source_rows": rows, "resolution": "HUMAN_REQUIRED"})
            for row_number in rows:
                by_row[row_number]["review_flags"].append("DUPLICATE_TITLE_REQUIRES_DISAMBIGUATION")

    expected_dayparts = {item["key"] for item in DAYPARTS.values()}
    present_dayparts = {
        item["provisional_enrichment"]["radio_daypart"]["key"] for item in staged
    }
    if present_dayparts != expected_dayparts:
        raise ImportStagingError(
            "catalog CSV must contain all six frozen dayparts; "
            f"missing={sorted(expected_dayparts - present_dayparts)}"
        )

    representatives = []
    for daypart_key in ("SUNRISE", "DAY", "FUTURE", "SUNSET", "NIGHT", "DEEP_SPACE"):
        candidates = [
            item for item in staged
            if item["provisional_enrichment"]["radio_daypart"]["key"] == daypart_key
        ]
        candidates.sort(
            key=lambda item: (
                -item["source_metadata"]["streams"],
                _identity_key(item["source_metadata"]["song"]),
                item["source_row"],
            )
        )
        selected = candidates[0]
        representatives.append(
            {
                "daypart": daypart_key,
                "source_row": selected["source_row"],
                "song": selected["source_metadata"]["song"],
                "streams": selected["source_metadata"]["streams"],
                "selection_basis": "HIGHEST_SOURCE_STREAM_COUNT",
                "status": "PROVISIONAL_METADATA_ONLY",
                "radio_cleared": False,
            }
        )

    daypart_counts = Counter(
        item["provisional_enrichment"]["radio_daypart"]["key"] for item in staged
    )
    return {
        "manifest_version": 1,
        "mode": "STAGING_ONLY",
        "canonical_write_permitted": False,
        "ast_id_allocation_permitted": False,
        "source": {
            "filename": path.name,
            "sha256": source_hash,
            "row_count": len(staged),
            "date_format": "M/D/YYYY",
        },
        "summary": {
            "staged_rows": len(staged),
            "unique_normalized_titles": len(title_groups),
            "duplicate_title_groups": len(duplicates),
            "daypart_counts": dict(sorted(daypart_counts.items())),
            "audio_qc_attached": sum(item["audio_qc"] is not None for item in staged),
            "ready_for_radio": 0,
        },
        "duplicate_title_groups": duplicates,
        "representative_candidates": representatives,
        "records": staged,
    }


def write_manifest_atomic(manifest: Mapping[str, Any], destination: Path | str) -> Path:
    """Write deterministic JSON atomically; never overwrite source inputs."""
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target
