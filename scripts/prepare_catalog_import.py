#!/usr/bin/env python3
"""Prepare a dry-run historical catalog import manifest for human review."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.catalog.audio_qc import AudioQcError, inspect_wav
from packages.catalog.import_staging import (
    ImportStagingError,
    build_staging_manifest,
    write_manifest_atomic,
)


DEFAULT_OUTPUT = REPO_ROOT / ".local" / "catalog" / "import-staging" / "manifest.json"


def validate_output_path(
    csv_path: Path,
    output_path: Path,
    *,
    wav_map_path: Path | None = None,
    ffprobe_path: Path | None = None,
    ffmpeg_path: Path | None = None,
) -> Path:
    """Fail closed before a manifest path can alias any input or executable."""
    source = csv_path.resolve()
    output = output_path.resolve()
    protected = {source}
    protected.update(
        path.resolve()
        for path in (wav_map_path, ffprobe_path, ffmpeg_path)
        if path is not None
    )
    if output in protected:
        raise ImportStagingError("staging output cannot overwrite an input or audio tool")
    if output.suffix.casefold() != ".json":
        raise ImportStagingError("staging output must be a JSON file")
    return output


def load_wav_map(
    mapping_path: Path,
    *,
    ffprobe_path: Path | None,
    ffmpeg_path: Path | None,
) -> dict[int, dict]:
    """Load explicit source-row-to-WAV mappings; filename guessing is forbidden."""
    result: dict[int, dict] = {}
    with mapping_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["source_row", "wav_path"]:
            raise ImportStagingError("WAV map columns must exactly equal source_row,wav_path")
        for map_row, item in enumerate(reader, start=2):
            try:
                source_row = int(item["source_row"])
            except (TypeError, ValueError) as error:
                raise ImportStagingError(
                    f"WAV map row {map_row}: source_row must be an integer"
                ) from error
            if source_row in result:
                raise ImportStagingError(f"WAV map repeats source_row {source_row}")
            raw_path = (item["wav_path"] or "").strip()
            if not raw_path:
                raise ImportStagingError(f"WAV map row {map_row}: wav_path is empty")
            wav_path = Path(raw_path)
            if not wav_path.is_absolute():
                wav_path = mapping_path.resolve().parent / wav_path
            result[source_row] = inspect_wav(
                wav_path, ffprobe_path=ffprobe_path, ffmpeg_path=ffmpeg_path
            )
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Create a staging-only catalog manifest. No AST IDs or canonical records are written."
    )
    parser.add_argument("csv_path", type=Path, help="139-song source CSV")
    parser.add_argument("--wav-map", type=Path, help="CSV with source_row,wav_path columns")
    parser.add_argument("--ffprobe", type=Path, help="Explicit ffprobe executable path")
    parser.add_argument("--ffmpeg", type=Path, help="Explicit ffmpeg executable path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        output_path = validate_output_path(
            args.csv_path,
            args.output,
            wav_map_path=args.wav_map,
            ffprobe_path=args.ffprobe,
            ffmpeg_path=args.ffmpeg,
        )
        qc = None
        if args.wav_map:
            qc = load_wav_map(
                args.wav_map.resolve(), ffprobe_path=args.ffprobe, ffmpeg_path=args.ffmpeg
            )
        manifest = build_staging_manifest(args.csv_path, audio_qc_by_source_row=qc)
        output = write_manifest_atomic(manifest, output_path)
        print(f"STAGING ONLY: {manifest['summary']['staged_rows']} rows written to {output}")
        print("AST ID allocation: DISABLED")
        print("Canonical catalog writes: DISABLED")
        print(f"Ready for radio: {manifest['summary']['ready_for_radio']}")
        return 0
    except (ImportStagingError, AudioQcError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
