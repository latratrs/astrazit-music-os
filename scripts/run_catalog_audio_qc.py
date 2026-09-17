#!/usr/bin/env python3
"""Run resumable, read-only full audio QC for an explicit catalog WAV map."""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.catalog.audio_qc import AudioQcError, inspect_wav


class BatchAudioQcError(ValueError):
    """Raised when a batch QC input or checkpoint is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_wav_map(path: Path) -> list[tuple[int, Path]]:
    rows: list[tuple[int, Path]] = []
    seen: set[int] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["source_row", "wav_path"]:
            raise BatchAudioQcError("WAV map columns must exactly equal source_row,wav_path")
        for map_row, item in enumerate(reader, start=2):
            try:
                source_row = int(item["source_row"])
            except (TypeError, ValueError) as error:
                raise BatchAudioQcError(
                    f"WAV map row {map_row}: source_row must be an integer"
                ) from error
            if source_row in seen:
                raise BatchAudioQcError(f"WAV map repeats source_row {source_row}")
            raw_path = (item["wav_path"] or "").strip()
            if not raw_path:
                raise BatchAudioQcError(f"WAV map row {map_row}: wav_path is empty")
            wav_path = Path(raw_path)
            if not wav_path.is_absolute():
                raise BatchAudioQcError(f"WAV map row {map_row}: wav_path must be absolute")
            seen.add(source_row)
            rows.append((source_row, wav_path))
    if not rows:
        raise BatchAudioQcError("WAV map contains no data rows")
    return rows


def _tool_version(path: Path) -> str:
    if not path.is_file():
        raise BatchAudioQcError(f"audio tool does not exist: {path}")
    result = subprocess.run(
        [str(path), "-version"], capture_output=True, text=True,
        shell=False, timeout=15,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise BatchAudioQcError(f"audio tool version check failed: {path}")
    return result.stdout.splitlines()[0].strip()


def _write_atomic(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with temp.open("w", encoding="utf-8", newline="\n") as output:
        output.write(text)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def _summary(tracks: list[dict[str, Any]]) -> dict[str, int]:
    passed = [item for item in tracks if item.get("status") == "PASS"]
    return {
        "total_tracks": len(tracks),
        "completed_tracks": len(passed),
        "failed_tracks": sum(item.get("status") == "ERROR" for item in tracks),
        "full_qc_tracks": sum(item.get("qc", {}).get("analysis_level") == "FULL" for item in passed),
        "pcm_clipping_tracks": sum(
            "PCM_CLIPPING_DETECTED" in item.get("qc", {}).get("warnings", [])
            for item in passed
        ),
        "radio_derivative_required": sum(
            item.get("qc", {}).get("radio_derivative_required") is True for item in passed
        ),
        "within_provisional_radio_target": sum(
            item.get("qc", {}).get("radio_derivative_required") is False for item in passed
        ),
    }


def run_batch(
    mapping_path: Path,
    output_path: Path,
    *,
    ffprobe_path: Path,
    ffmpeg_path: Path,
    inspector: Callable[..., dict[str, Any]] = inspect_wav,
    tool_versions: dict[str, str] | None = None,
    progress: Callable[[str], None] | None = print,
    workers: int = 1,
) -> dict[str, Any]:
    if workers < 1 or workers > 8:
        raise BatchAudioQcError("workers must be between 1 and 8")
    mapping_path = mapping_path.resolve()
    output_path = output_path.resolve()
    output_temporary = output_path.with_name(f".{output_path.name}.tmp")
    if output_path == mapping_path:
        raise BatchAudioQcError("QC output cannot overwrite the WAV map")
    if output_path.suffix.casefold() != ".json":
        raise BatchAudioQcError("QC output must be a JSON file")
    mappings = load_wav_map(mapping_path)
    source_paths = {wav_path.resolve() for _, wav_path in mappings}
    protected_paths = source_paths | {mapping_path, ffprobe_path.resolve(), ffmpeg_path.resolve()}
    if {output_path, output_temporary} & protected_paths:
        raise BatchAudioQcError("QC output paths cannot overwrite an input or audio tool")
    map_hash = _sha256(mapping_path)
    versions = tool_versions or {
        "ffmpeg": _tool_version(ffmpeg_path),
        "ffprobe": _tool_version(ffprobe_path),
    }
    prior_by_row: dict[int, dict[str, Any]] = {}
    if output_path.is_file():
        try:
            prior = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BatchAudioQcError("existing QC checkpoint is unreadable") from error
        if prior.get("input", {}).get("wav_map_sha256") != map_hash:
            raise BatchAudioQcError("existing QC checkpoint belongs to a different WAV map")
        prior_by_row = {
            int(item["source_row"]): item
            for item in prior.get("tracks", [])
            if item.get("status") == "PASS"
        }

    tracks: list[dict[str, Any]] = []
    for source_row, wav_path in mappings:
        resolved_wav_path = wav_path.resolve()
        prior_item = prior_by_row.get(source_row)
        if prior_item and prior_item.get("wav_path") == str(wav_path):
            if not resolved_wav_path.is_file():
                raise BatchAudioQcError(
                    f"source row {source_row}: previously inspected WAV no longer exists"
                )
            prior_hash = prior_item.get("qc", {}).get("source_sha256")
            if prior_hash != _sha256(resolved_wav_path):
                raise BatchAudioQcError(
                    f"source row {source_row}: WAV bytes changed since the saved checkpoint"
                )
            tracks.append(prior_item)
        else:
            tracks.append({"source_row": source_row, "wav_path": str(wav_path), "status": "PENDING"})

    report: dict[str, Any] = {
        "report_version": 1,
        "status": "RUNNING",
        "input": {
            "wav_map_path": str(mapping_path.resolve()),
            "wav_map_sha256": map_hash,
            "mapped_tracks": len(mappings),
        },
        "toolchain": versions,
        "summary": _summary(tracks),
        "tracks": tracks,
    }
    _write_atomic(report, output_path)

    pending: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(tracks, start=1):
        if item["status"] == "PASS":
            if progress:
                progress(f"[{index}/{len(tracks)}] source row {item['source_row']}: resumed")
            continue
        pending.append((index, item))

    def analyze(item: dict[str, Any]) -> dict[str, Any]:
        try:
            item["qc"] = inspector(
                Path(item["wav_path"]),
                ffprobe_path=ffprobe_path,
                ffmpeg_path=ffmpeg_path,
            )
            item["status"] = "PASS"
            item.pop("error", None)
        except (AudioQcError, OSError, subprocess.SubprocessError) as error:
            item["status"] = "ERROR"
            item["error"] = str(error)
            item.pop("qc", None)
        return item

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(analyze, item): (index, item)
            for index, item in pending
        }
        for future in concurrent.futures.as_completed(futures):
            index, item = futures[future]
            future.result()
            if progress:
                progress(f"[{index}/{len(tracks)}] source row {item['source_row']}: {item['status'].lower()}")
            report["summary"] = _summary(tracks)
            _write_atomic(report, output_path)

    report["status"] = "COMPLETE" if report["summary"]["failed_tracks"] == 0 else "COMPLETE_WITH_ERRORS"
    report["summary"] = _summary(tracks)
    _write_atomic(report, output_path)
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run resumable read-only full QC. No masters or radio derivatives are written."
    )
    parser.add_argument("wav_map", type=Path, help="CSV with source_row,wav_path columns")
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1, help="Concurrent read-only analyses (1-8)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        report = run_batch(
            args.wav_map.resolve(), args.output.resolve(),
            ffprobe_path=args.ffprobe.resolve(), ffmpeg_path=args.ffmpeg.resolve(),
            workers=args.workers,
        )
    except (BatchAudioQcError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
