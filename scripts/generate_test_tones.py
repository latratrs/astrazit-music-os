"""Generate synthetic test tones for AstraZit Radio local playout MVP.

Governed by RADIO-001.
Uses only Python standard library (wave, math, struct).
No external audio files or dependencies needed.
Generates small, harmless test audio files (.wav) for smoke tests and verification.
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
import wave
from pathlib import Path


def generate_sine_wave(
    filepath: Path,
    frequency: float = 440.0,
    duration_seconds: float = 1.0,
    sample_rate: int = 44100,
    amplitude: float = 0.5,
) -> None:
    """Generate a single-channel 16-bit PCM WAV tone."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(sample_rate * duration_seconds)

    with wave.open(str(filepath), "wb") as wf:
        wf.setnchannels(1)  # Mono
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)

        raw_data = bytearray()
        for i in range(num_samples):
            t = float(i) / sample_rate
            # Sine wave with simple decay envelope to avoid speaker clicks
            envelope = 1.0
            if i < sample_rate * 0.05:
                envelope = i / (sample_rate * 0.05)
            elif i > num_samples - (sample_rate * 0.05):
                envelope = (num_samples - i) / (sample_rate * 0.05)

            sample = amplitude * envelope * math.sin(2.0 * math.pi * frequency * t)
            sample_val = int(sample * 32767.0)
            raw_data.extend(struct.pack("<h", sample_val))

        wf.writeframes(raw_data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic test audio files for Radio MVP")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".local/radio/music",
        help="Destination directory for test tones",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=1.0,
        help="Duration of each tone in seconds (default: 1.0s)",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir).resolve()
    print(f"Generating synthetic test tones in: {out_dir}")

    tones = [
        ("track_a_synth_440hz.wav", 440.0),  # A4
        ("track_b_synth_554hz.wav", 554.37), # C#5
        ("track_c_synth_659hz.wav", 659.25), # E5
    ]

    for fname, freq in tones:
        target = out_dir / fname
        generate_sine_wave(target, frequency=freq, duration_seconds=args.duration)
        print(f"  Generated: {target.name} ({freq:.1f} Hz, {args.duration}s)")

    print("Done! Test tracks generated safely.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
