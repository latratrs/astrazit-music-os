#!/usr/bin/env python3
"""Create resumable local radio WAV derivatives from an explicit QC-approved map."""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.catalog.audio_qc import AudioQcError, inspect_wav
from scripts.create_radio_derivatives import (
    OUTPUT_BIT_DEPTH,
    OUTPUT_CHANNELS,
    OUTPUT_SAMPLE_RATE_HZ,
    PROCESSING_TRUE_PEAK_DBTP,
    TARGET_LUFS,
    VERIFIED_TRUE_PEAK_MAX_DBTP,
    RadioDerivativeError,
    first_pass,
    second_pass,
    sha256,
    tool_version,
    verify_output,
)


MAP_COLUMNS = (
    "source_row", "title", "wav_path", "expected_source_sha256", "expected_duration_seconds",
)


class CatalogDerivativeError(ValueError):
    """Raised when a batch derivative map or checkpoint is invalid."""


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized[:80] or "untitled"


def output_name(row: dict[str, Any]) -> str:
    return f"row-{row['source_row']:03d}__{slug(row['title'])}__radio.wav"


def load_map(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_rows: set[int] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != MAP_COLUMNS:
            raise CatalogDerivativeError(f"map columns must exactly equal {','.join(MAP_COLUMNS)}")
        for line, raw in enumerate(reader, start=2):
            try:
                source_row = int(raw["source_row"])
            except (TypeError, ValueError) as error:
                raise CatalogDerivativeError(f"map row {line}: source_row must be an integer") from error
            if source_row in seen_rows:
                raise CatalogDerivativeError(f"map repeats source_row {source_row}")
            title = (raw["title"] or "").strip()
            wav_path = Path((raw["wav_path"] or "").strip())
            expected_hash = (raw["expected_source_sha256"] or "").strip().upper()
            try:
                duration = float(raw["expected_duration_seconds"])
            except (TypeError, ValueError) as error:
                raise CatalogDerivativeError(f"map row {line}: expected_duration_seconds must be numeric") from error
            if not title or not wav_path.is_absolute() or wav_path.suffix.casefold() not in {".wav", ".wave"}:
                raise CatalogDerivativeError(f"map row {line}: title and absolute WAV path are required")
            if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
                raise CatalogDerivativeError(f"map row {line}: expected_source_sha256 is invalid")
            if duration <= 0:
                raise CatalogDerivativeError(f"map row {line}: expected_duration_seconds must be positive")
            seen_rows.add(source_row)
            rows.append({
                "source_row": source_row,
                "title": title,
                "source_path": wav_path,
                "expected_source_sha256": expected_hash,
                "expected_duration_seconds": duration,
            })
    if not rows:
        raise CatalogDerivativeError("map contains no tracks")
    return rows


def write_atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, indent=2, sort_keys=True, ensure_ascii=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def summary(tracks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(tracks),
        "passed": sum(track.get("status") == "PASS" for track in tracks),
        "failed": sum(track.get("status") == "ERROR" for track in tracks),
        "pending": sum(track.get("status") == "PENDING" for track in tracks),
    }


def _resumable_item(prior: dict[str, Any], row: dict[str, Any], destination: Path) -> bool:
    source = row["source_path"].resolve()
    return (
        prior.get("status") == "PASS"
        and prior.get("source_row") == row["source_row"]
        and prior.get("source_path") == str(row["source_path"])
        and source.is_file()
        and prior.get("source_sha256") == row["expected_source_sha256"]
        and sha256(source) == row["expected_source_sha256"]
        and prior.get("destination") == str(destination)
        and destination.is_file()
        and prior.get("output_sha256") == sha256(destination)
    )


def run_batch(
    map_path: Path,
    output_dir: Path,
    report_path: Path,
    *,
    ffmpeg: Path,
    ffprobe: Path,
    workers: int = 4,
    inspector: Callable[..., dict[str, Any]] = inspect_wav,
    progress: Callable[[str], None] | None = print,
) -> dict[str, Any]:
    if workers < 1 or workers > 6:
        raise CatalogDerivativeError("workers must be between 1 and 6")
    map_path = map_path.resolve()
    output_dir = output_dir.resolve()
    report_path = report_path.resolve()
    ffmpeg = ffmpeg.resolve()
    ffprobe = ffprobe.resolve()
    rows = load_map(map_path)
    if not ffmpeg.is_file() or not ffprobe.is_file():
        raise CatalogDerivativeError("FFmpeg and FFprobe executables must exist")
    destinations = {(output_dir / output_name(row)).resolve() for row in rows}
    temporary_outputs = {
        destination.with_name(f".{destination.stem}.partial.wav")
        for destination in destinations
    }
    source_paths = {row["source_path"].resolve() for row in rows}
    report_temporary = report_path.with_name(f".{report_path.name}.tmp")
    protected_inputs = source_paths | {map_path, ffmpeg, ffprobe}
    if (destinations | temporary_outputs) & protected_inputs:
        raise CatalogDerivativeError("batch output paths cannot overwrite an input or audio tool")
    if {report_path, report_temporary} & (protected_inputs | destinations | temporary_outputs):
        raise CatalogDerivativeError("batch report cannot overwrite an input, tool, or WAV")
    if report_path.suffix.casefold() != ".json":
        raise CatalogDerivativeError("batch report must be a JSON file")
    output_dir.mkdir(parents=True, exist_ok=True)
    map_hash = sha256(map_path)
    previous_by_row: dict[int, dict[str, Any]] = {}
    if report_path.is_file():
        try:
            prior = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogDerivativeError("existing batch checkpoint is unreadable") from error
        if prior.get("input_map_sha256") != map_hash:
            raise CatalogDerivativeError("existing batch checkpoint belongs to a different map")
        previous_by_row = {int(item["source_row"]): item for item in prior.get("tracks", [])}

    tracks: list[dict[str, Any]] = []
    for row in rows:
        destination = (output_dir / output_name(row)).resolve()
        prior_item = previous_by_row.get(row["source_row"])
        if prior_item and _resumable_item(prior_item, row, destination):
            tracks.append(prior_item)
        else:
            tracks.append({
                "source_row": row["source_row"], "title": row["title"],
                "source_path": str(row["source_path"]), "destination": str(destination),
                "status": "PENDING",
            })

    report: dict[str, Any] = {
        "report_version": 1,
        "status": "RUNNING",
        "input_map_sha256": map_hash,
        "toolchain": {"ffmpeg": tool_version(ffmpeg)},
        "profile": {
            "codec": "pcm_s16le", "sample_rate_hz": OUTPUT_SAMPLE_RATE_HZ,
            "bit_depth": OUTPUT_BIT_DEPTH, "channels": OUTPUT_CHANNELS,
            "target_lufs": TARGET_LUFS, "processing_true_peak_dbtp": PROCESSING_TRUE_PEAK_DBTP,
            "verified_true_peak_max_dbtp": VERIFIED_TRUE_PEAK_MAX_DBTP,
        },
        "tracks": tracks,
        "summary": summary(tracks),
    }
    write_atomic_json(report, report_path)

    row_by_source = {row["source_row"]: row for row in rows}

    def process(item: dict[str, Any]) -> dict[str, Any]:
        row = row_by_source[item["source_row"]]
        source = row["source_path"].resolve()
        destination = Path(item["destination"])
        temporary = destination.with_name(f".{destination.stem}.partial.wav")
        try:
            if not source.is_file():
                raise CatalogDerivativeError(f"source WAV does not exist: {source}")
            if source == destination:
                raise CatalogDerivativeError("source and destination cannot be the same path")
            source_before_hash = sha256(source)
            source_before_size = source.stat().st_size
            if source_before_hash != row["expected_source_sha256"]:
                raise CatalogDerivativeError("source hash differs from approved OS-010A evidence")
            if destination.exists():
                raise CatalogDerivativeError(f"destination already exists: {destination}")
            measurement = first_pass(ffmpeg, source)
            if temporary.exists():
                temporary.unlink()
            render_measurement = second_pass(ffmpeg, source, temporary, measurement)
            output_qc = inspector(temporary, ffprobe_path=ffprobe, ffmpeg_path=ffmpeg)
            verify_output(output_qc, row["expected_duration_seconds"])
            source_after_hash = sha256(source)
            source_after_size = source.stat().st_size
            if source_before_hash != source_after_hash or source_before_size != source_after_size:
                raise CatalogDerivativeError("source WAV changed during derivative creation")
            os.replace(temporary, destination)
            item.update({
                "status": "PASS", "source_sha256": source_before_hash,
                "source_preserved": True, "first_pass": measurement,
                "second_pass": render_measurement, "output_qc": output_qc,
                "output_sha256": sha256(destination), "output_size_bytes": destination.stat().st_size,
            })
        except (AudioQcError, OSError, subprocess.SubprocessError, RadioDerivativeError, CatalogDerivativeError) as error:
            item.update({"status": "ERROR", "error": str(error)})
            if temporary.exists():
                temporary.unlink()
        return item

    pending = [(index, item) for index, item in enumerate(tracks, start=1) if item["status"] == "PENDING"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process, item): (index, item) for index, item in pending}
        for future in concurrent.futures.as_completed(futures):
            index, item = futures[future]
            future.result()
            if progress:
                progress(f"[{index}/{len(tracks)}] source row {item['source_row']}: {item['status'].lower()}")
            report["summary"] = summary(tracks)
            write_atomic_json(report, report_path)
    report["summary"] = summary(tracks)
    report["status"] = "COMPLETE" if report["summary"]["failed"] == 0 else "COMPLETE_WITH_ERRORS"
    write_atomic_json(report, report_path)
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Create resumable local catalog radio derivatives.")
    parser.add_argument("wav_map", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        report = run_batch(
            args.wav_map.resolve(), args.output_dir.resolve(), args.report.resolve(),
            ffmpeg=args.ffmpeg.resolve(), ffprobe=args.ffprobe.resolve(), workers=args.workers,
        )
    except (CatalogDerivativeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
