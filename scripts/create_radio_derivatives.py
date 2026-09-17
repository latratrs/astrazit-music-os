#!/usr/bin/env python3
"""Create verified local radio WAV derivatives without modifying source masters."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.catalog.audio_qc import AudioQcError, inspect_wav


DAYPARTS = ("SUNRISE", "DAY", "FUTURE", "SUNSET", "NIGHT", "DEEP SPACE")
MAP_COLUMNS = ("daypart", "source_row", "title", "wav_path", "expected_source_sha256")
TARGET_LUFS = -14.0
PROCESSING_TRUE_PEAK_DBTP = -1.5
VERIFIED_TRUE_PEAK_MAX_DBTP = -1.0
OUTPUT_SAMPLE_RATE_HZ = 44100
OUTPUT_BIT_DEPTH = 16
OUTPUT_CHANNELS = 2


class RadioDerivativeError(ValueError):
    """Raised when a derivative cannot be created or verified safely."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_map(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != MAP_COLUMNS:
            raise RadioDerivativeError(f"map columns must exactly equal {','.join(MAP_COLUMNS)}")
        for line, raw in enumerate(reader, start=2):
            daypart = (raw["daypart"] or "").strip().upper()
            if daypart not in DAYPARTS:
                raise RadioDerivativeError(f"map row {line}: unknown daypart {daypart!r}")
            try:
                source_row = int(raw["source_row"])
            except (TypeError, ValueError) as error:
                raise RadioDerivativeError(f"map row {line}: source_row must be an integer") from error
            title = (raw["title"] or "").strip()
            if not title:
                raise RadioDerivativeError(f"map row {line}: title is empty")
            source_path = Path((raw["wav_path"] or "").strip())
            if not source_path.is_absolute() or source_path.suffix.casefold() not in {".wav", ".wave"}:
                raise RadioDerivativeError(f"map row {line}: wav_path must be an absolute WAV path")
            expected_hash = (raw["expected_source_sha256"] or "").strip().upper()
            if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
                raise RadioDerivativeError(f"map row {line}: expected_source_sha256 is invalid")
            rows.append({
                "daypart": daypart,
                "source_row": source_row,
                "title": title,
                "source_path": source_path,
                "expected_source_sha256": expected_hash,
            })
    if len(rows) != len(DAYPARTS) or {row["daypart"] for row in rows} != set(DAYPARTS):
        raise RadioDerivativeError("map must contain exactly one row for each frozen daypart")
    if len({row["source_row"] for row in rows}) != len(rows):
        raise RadioDerivativeError("map source_row values must be unique")
    return rows


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized[:80] or "untitled"


def output_name(row: dict[str, Any]) -> str:
    daypart = row["daypart"].casefold().replace(" ", "-")
    return f"{daypart}__{slug(row['title'])}__row-{row['source_row']:03d}__radio.wav"


def parse_loudnorm(stderr: str, required_prefix: str) -> dict[str, float | str]:
    matches = re.findall(r"\{\s*\"input_i\".*?\}", stderr, flags=re.DOTALL)
    if not matches:
        raise RadioDerivativeError(f"{required_prefix} returned no loudnorm JSON")
    try:
        data = json.loads(matches[-1])
    except json.JSONDecodeError as error:
        raise RadioDerivativeError(f"{required_prefix} returned malformed loudnorm JSON") from error
    return data


def first_pass(ffmpeg: Path, source: Path) -> dict[str, float | str]:
    command = [
        str(ffmpeg), "-nostdin", "-hide_banner", "-nostats", "-i", str(source),
        "-map", "0:a:0", "-af",
        f"loudnorm=I={TARGET_LUFS}:TP={PROCESSING_TRUE_PEAK_DBTP}:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, shell=False, timeout=900)
    if result.returncode != 0:
        raise RadioDerivativeError(f"FFmpeg first pass failed: {result.stderr.strip()[-400:]}")
    return parse_loudnorm(result.stderr, "FFmpeg first pass")


def second_pass_filter(measurement: dict[str, float | str]) -> str:
    required = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    try:
        values = {key: float(measurement[key]) for key in required}
    except (KeyError, TypeError, ValueError) as error:
        raise RadioDerivativeError("first-pass loudnorm measurement is incomplete") from error
    loudnorm = (
        f"loudnorm=I={TARGET_LUFS}:TP={PROCESSING_TRUE_PEAK_DBTP}:LRA=11:"
        f"measured_I={values['input_i']}:measured_TP={values['input_tp']}:"
        f"measured_LRA={values['input_lra']}:measured_thresh={values['input_thresh']}:"
        f"offset={values['target_offset']}:linear=true:print_format=json"
    )
    resample = f"aresample={OUTPUT_SAMPLE_RATE_HZ}:dither_method=triangular"
    return f"{loudnorm},{resample}"


def second_pass(ffmpeg: Path, source: Path, temporary_output: Path, measurement: dict[str, Any]) -> dict[str, Any]:
    command = [
        str(ffmpeg), "-nostdin", "-hide_banner", "-nostats", "-y", "-i", str(source),
        "-map", "0:a:0", "-vn", "-af", second_pass_filter(measurement),
        "-c:a", "pcm_s16le", "-ar", str(OUTPUT_SAMPLE_RATE_HZ), "-ac", str(OUTPUT_CHANNELS),
        "-map_metadata", "-1", "-bitexact", str(temporary_output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, shell=False, timeout=1200)
    if result.returncode != 0:
        raise RadioDerivativeError(f"FFmpeg second pass failed: {result.stderr.strip()[-400:]}")
    return parse_loudnorm(result.stderr, "FFmpeg second pass")


def verify_output(qc: dict[str, Any], source_duration: float) -> None:
    pcm = qc["basic_pcm"]
    loudness = qc["loudness"]
    if pcm["sample_rate_hz"] != OUTPUT_SAMPLE_RATE_HZ:
        raise RadioDerivativeError("derivative sample rate verification failed")
    if pcm["bit_depth"] != OUTPUT_BIT_DEPTH or pcm["channels"] != OUTPUT_CHANNELS:
        raise RadioDerivativeError("derivative PCM format verification failed")
    if pcm["clipped_pcm_samples"] != 0:
        raise RadioDerivativeError("derivative contains clipped PCM samples")
    if abs(pcm["duration_seconds"] - source_duration) > 0.05:
        raise RadioDerivativeError("derivative duration differs from source")
    if not (-14.8 <= loudness["integrated_lufs"] <= -13.5):
        raise RadioDerivativeError("derivative integrated loudness is outside verification tolerance")
    if loudness["true_peak_dbtp"] > VERIFIED_TRUE_PEAK_MAX_DBTP:
        raise RadioDerivativeError("derivative true peak exceeds -1 dBTP")


def write_atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, indent=2, sort_keys=True, ensure_ascii=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def tool_version(executable: Path) -> str:
    if not executable.is_file():
        raise RadioDerivativeError(f"FFmpeg executable does not exist: {executable}")
    result = subprocess.run([str(executable), "-version"], capture_output=True, text=True, shell=False, timeout=15)
    if result.returncode != 0 or not result.stdout.strip():
        raise RadioDerivativeError("FFmpeg version check failed")
    return result.stdout.splitlines()[0].strip()


def create_derivatives(map_path: Path, output_dir: Path, report_path: Path, *, ffmpeg: Path, ffprobe: Path) -> dict[str, Any]:
    map_path = map_path.resolve()
    output_dir = output_dir.resolve()
    report_path = report_path.resolve()
    ffmpeg = ffmpeg.resolve()
    ffprobe = ffprobe.resolve()
    rows = load_map(map_path)
    destinations = {(output_dir / output_name(row)).resolve() for row in rows}
    temporary_outputs = {
        destination.with_name(f".{destination.stem}.partial.wav")
        for destination in destinations
    }
    source_paths = {row["source_path"].resolve() for row in rows}
    report_temporary = report_path.with_name(f".{report_path.name}.tmp")
    protected_inputs = source_paths | {map_path, ffmpeg, ffprobe}
    if (destinations | temporary_outputs) & protected_inputs:
        raise RadioDerivativeError("derivative output paths cannot overwrite an input or audio tool")
    if {report_path, report_temporary} & (protected_inputs | destinations | temporary_outputs):
        raise RadioDerivativeError("derivative report cannot overwrite an input, tool, or WAV")
    if report_path.suffix.casefold() != ".json":
        raise RadioDerivativeError("derivative report must be a JSON file")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not ffprobe.is_file():
        raise RadioDerivativeError(f"FFprobe executable does not exist: {ffprobe}")
    report: dict[str, Any] = {
        "report_version": 1,
        "status": "RUNNING",
        "input_map_sha256": sha256(map_path),
        "toolchain": {"ffmpeg": tool_version(ffmpeg)},
        "profile": {
            "codec": "pcm_s16le",
            "sample_rate_hz": OUTPUT_SAMPLE_RATE_HZ,
            "bit_depth": OUTPUT_BIT_DEPTH,
            "channels": OUTPUT_CHANNELS,
            "target_lufs": TARGET_LUFS,
            "processing_true_peak_dbtp": PROCESSING_TRUE_PEAK_DBTP,
            "verified_true_peak_max_dbtp": VERIFIED_TRUE_PEAK_MAX_DBTP,
        },
        "tracks": [],
    }
    write_atomic_json(report, report_path)
    for row in rows:
        destination = (output_dir / output_name(row)).resolve()
        temporary = destination.with_name(f".{destination.stem}.partial.wav")
        item: dict[str, Any] = {
            "daypart": row["daypart"], "source_row": row["source_row"], "title": row["title"],
            "source_path": str(row["source_path"]), "destination": str(destination), "status": "PENDING",
        }
        report["tracks"].append(item)
        try:
            source = row["source_path"].resolve()
            if not source.is_file():
                raise RadioDerivativeError(f"source WAV does not exist: {source}")
            before_stat = source.stat()
            before_hash = sha256(source)
            if before_hash != row["expected_source_sha256"]:
                raise RadioDerivativeError("source WAV hash differs from approved OS-010A evidence")
            if destination.exists():
                raise RadioDerivativeError(f"destination already exists: {destination}")
            source_qc = inspect_wav(source, ffprobe_path=ffprobe, ffmpeg_path=ffmpeg)
            measurement = first_pass(ffmpeg, source)
            if temporary.exists():
                temporary.unlink()
            render_measurement = second_pass(ffmpeg, source, temporary, measurement)
            output_qc = inspect_wav(temporary, ffprobe_path=ffprobe, ffmpeg_path=ffmpeg)
            verify_output(output_qc, source_qc["basic_pcm"]["duration_seconds"])
            after_stat = source.stat()
            after_hash = sha256(source)
            if before_hash != after_hash or before_stat.st_size != after_stat.st_size:
                raise RadioDerivativeError("source WAV changed during derivative creation")
            os.replace(temporary, destination)
            item.update({
                "status": "PASS", "source_sha256": before_hash,
                "source_clipped_pcm_samples": source_qc["basic_pcm"]["clipped_pcm_samples"],
                "first_pass": measurement, "second_pass": render_measurement,
                "output_sha256": sha256(destination), "output_size_bytes": destination.stat().st_size,
                "output_qc": output_qc, "source_preserved": True,
            })
        except (AudioQcError, OSError, subprocess.SubprocessError, RadioDerivativeError) as error:
            item.update({"status": "ERROR", "error": str(error)})
            if temporary.exists():
                temporary.unlink()
        report["summary"] = {
            "total": len(rows),
            "passed": sum(track["status"] == "PASS" for track in report["tracks"]),
            "failed": sum(track["status"] == "ERROR" for track in report["tracks"]),
        }
        write_atomic_json(report, report_path)
    report["status"] = "COMPLETE" if report["summary"]["failed"] == 0 else "COMPLETE_WITH_ERRORS"
    write_atomic_json(report, report_path)
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Create six verified local radio WAV derivatives.")
    parser.add_argument("representative_map", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        report = create_derivatives(
            args.representative_map.resolve(), args.output_dir.resolve(), args.report.resolve(),
            ffmpeg=args.ffmpeg.resolve(), ffprobe=args.ffprobe.resolve(),
        )
    except (OSError, RadioDerivativeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
