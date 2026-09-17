"""Read-only WAV source inspection for catalog import staging.

Original masters are opened only for reading. This module does not normalize,
rename, transcode, move, or create radio derivatives.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import wave
from array import array
from pathlib import Path
from typing import Any, Optional


class AudioQcError(ValueError):
    """Raised when a source cannot be safely inspected as PCM WAV."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _pcm_sample_values(data: bytes, sample_width: int):
    if sample_width == 1:
        for byte in data:
            yield byte - 128
    elif sample_width == 2:
        for index in range(0, len(data) - 1, 2):
            yield int.from_bytes(data[index:index + 2], "little", signed=True)
    elif sample_width == 3:
        for index in range(0, len(data) - 2, 3):
            raw = int.from_bytes(data[index:index + 3], "little", signed=False)
            yield raw - (1 << 24) if raw & (1 << 23) else raw
    elif sample_width == 4:
        for index in range(0, len(data) - 3, 4):
            yield int.from_bytes(data[index:index + 4], "little", signed=True)
    else:
        raise AudioQcError(f"unsupported PCM sample width: {sample_width * 8}-bit")


def _chunk_peak_and_clipping(data: bytes, sample_width: int) -> tuple[int, int]:
    """Return absolute peak and ceiling count without per-sample Python work."""
    if not data:
        return 0, 0
    if sample_width == 1:
        highest = max(data) - 128
        lowest = min(data) - 128
        return max(abs(highest), abs(lowest)), data.count(255) + data.count(0)
    if sample_width in (2, 4):
        usable = len(data) - (len(data) % sample_width)
        values = array("h" if sample_width == 2 else "i")
        values.frombytes(data[:usable])
        if sys.byteorder != "little":
            values.byteswap()
        highest = max(values, default=0)
        lowest = min(values, default=0)
        max_positive = (1 << (sample_width * 8 - 1)) - 1
        min_negative = -(1 << (sample_width * 8 - 1))
        clipped = values.count(max_positive) + values.count(min_negative)
        return max(abs(highest), abs(lowest)), clipped
    if sample_width == 3:
        max_positive = (1 << 23) - 1
        min_negative = -(1 << 23)
        maximum = 0
        clipped = 0
        for sample in _pcm_sample_values(data, sample_width):
            maximum = max(maximum, abs(sample))
            if sample == max_positive or sample == min_negative:
                clipped += 1
        return maximum, clipped
    raise AudioQcError(f"unsupported PCM sample width: {sample_width * 8}-bit")


def _basic_wave_analysis(path: Path) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            if compression != "NONE":
                raise AudioQcError(f"compressed WAV is not accepted as PCM: {compression}")
            max_positive = (1 << (sample_width * 8 - 1)) - 1
            maximum = 0
            clipped = 0
            while True:
                data = source.readframes(65536)
                if not data:
                    break
                chunk_maximum, chunk_clipped = _chunk_peak_and_clipping(data, sample_width)
                maximum = max(maximum, chunk_maximum)
                clipped += chunk_clipped
    except (wave.Error, EOFError) as error:
        raise AudioQcError(f"invalid or unsupported WAV container: {error}") from error
    if channels < 1 or sample_rate < 1 or frame_count < 1:
        raise AudioQcError("WAV must contain at least one non-empty audio channel")
    peak_dbfs = None if maximum == 0 else 20.0 * math.log10(min(maximum / max_positive, 1.0))
    return {
        "codec": f"pcm_s{sample_width * 8}le" if sample_width > 1 else "pcm_u8",
        "sample_rate_hz": sample_rate,
        "bit_depth": sample_width * 8,
        "channels": channels,
        "frame_count": frame_count,
        "duration_seconds": frame_count / sample_rate,
        "sample_peak_dbfs": peak_dbfs,
        "clipped_pcm_samples": clipped,
    }


def _resolve_executable(value: Optional[Path | str], name: str) -> Optional[str]:
    if value is None:
        return shutil.which(name)
    candidate = Path(value).resolve()
    if not candidate.is_file():
        raise AudioQcError(f"configured {name} executable does not exist: {candidate}")
    return str(candidate)


def _run_ffprobe(executable: str, path: Path) -> dict[str, Any]:
    command = [
        executable, "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels,bits_per_raw_sample,bits_per_sample",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, shell=False, timeout=60)
    if result.returncode != 0:
        raise AudioQcError(f"ffprobe rejected WAV source: {result.stderr.strip()[:300]}")
    try:
        streams = json.loads(result.stdout)["streams"]
        stream = streams[0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise AudioQcError("ffprobe returned malformed audio metadata") from error
    return stream


def _run_loudness_analysis(executable: str, path: Path) -> dict[str, float]:
    command = [
        executable, "-hide_banner", "-nostats", "-i", str(path),
        "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, shell=False, timeout=600)
    if result.returncode != 0:
        raise AudioQcError(f"ffmpeg loudness analysis failed: {result.stderr.strip()[-300:]}")
    matches = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr, flags=re.DOTALL)
    if not matches:
        raise AudioQcError("ffmpeg loudness analysis returned no JSON measurement")
    try:
        data = json.loads(matches[-1])
        return {
            "integrated_lufs": float(data["input_i"]),
            "true_peak_dbtp": float(data["input_tp"]),
            "loudness_range_lu": float(data["input_lra"]),
        }
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise AudioQcError("ffmpeg loudness JSON is incomplete") from error


def _validate_probe(probe: dict[str, Any], basic: dict[str, Any]) -> None:
    codec = probe.get("codec_name")
    if not isinstance(codec, str) or not codec.startswith("pcm_"):
        raise AudioQcError(f"ffprobe codec is not uncompressed PCM: {codec!r}")
    try:
        sample_rate = int(probe["sample_rate"])
        channels = int(probe["channels"])
    except (KeyError, TypeError, ValueError) as error:
        raise AudioQcError("ffprobe omitted sample rate or channel count") from error
    if sample_rate != basic["sample_rate_hz"] or channels != basic["channels"]:
        raise AudioQcError("ffprobe metadata conflicts with WAV container inspection")
    raw_depth = probe.get("bits_per_raw_sample") or probe.get("bits_per_sample")
    if raw_depth not in (None, "", 0, "0"):
        try:
            bit_depth = int(raw_depth)
        except (TypeError, ValueError) as error:
            raise AudioQcError("ffprobe returned invalid bit depth") from error
        if bit_depth != basic["bit_depth"]:
            raise AudioQcError("ffprobe bit depth conflicts with WAV container inspection")


def inspect_wav(
    source_path: Path | str,
    *,
    ffprobe_path: Optional[Path | str] = None,
    ffmpeg_path: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Inspect a WAV source without changing its bytes or filesystem metadata."""
    path = Path(source_path).resolve()
    if not path.is_file():
        raise AudioQcError(f"WAV source does not exist: {path}")
    if path.suffix.casefold() not in {".wav", ".wave"}:
        raise AudioQcError("audio QC accepts only WAV sources in OS-010")
    before = path.stat()
    source_hash = _sha256(path)
    basic = _basic_wave_analysis(path)
    ffprobe = _resolve_executable(ffprobe_path, "ffprobe")
    ffmpeg = _resolve_executable(ffmpeg_path, "ffmpeg")
    probe = _run_ffprobe(ffprobe, path) if ffprobe else None
    if probe is not None:
        _validate_probe(probe, basic)
    loudness = _run_loudness_analysis(ffmpeg, path) if ffmpeg else None
    after_hash = _sha256(path)
    after = path.stat()
    if source_hash != after_hash or before.st_size != after.st_size:
        raise AudioQcError("source WAV changed during read-only inspection")

    warnings: list[str] = []
    if basic["duration_seconds"] < 90:
        warnings.append("SHORT_DURATION_REQUIRES_REVIEW")
    if basic["clipped_pcm_samples"]:
        warnings.append("PCM_CLIPPING_DETECTED")
    if loudness and loudness["true_peak_dbtp"] > -1.0:
        warnings.append("TRUE_PEAK_EXCEEDS_RADIO_TARGET")
    if loudness and not (-15.0 <= loudness["integrated_lufs"] <= -13.0):
        warnings.append("LOUDNESS_OUTSIDE_PROVISIONAL_RADIO_TARGET")

    full_qc = loudness is not None
    audio_qc_pass = full_qc and basic["clipped_pcm_samples"] == 0
    derivative_required = None
    if full_qc:
        derivative_required = (
            loudness["true_peak_dbtp"] > -1.0
            or not (-15.0 <= loudness["integrated_lufs"] <= -13.0)
        )
    return {
        "source_path": str(path),
        "source_sha256": source_hash,
        "size_bytes": before.st_size,
        "master_valid": True,
        "analysis_level": "FULL" if full_qc else "BASIC_ONLY",
        "audio_qc_pass": audio_qc_pass,
        "radio_derivative_required": derivative_required,
        "basic_pcm": basic,
        "ffprobe": probe,
        "loudness": loudness,
        "warnings": warnings,
        "source_preserved": True,
    }
