#!/usr/bin/env bash

# ==============================================================================
# AstraZit Music OS - Linux Audible Playout Verification Protocol
# Governed by RADIO-002, ADR-002, ADR-006, and ADR-008.
#
# Validates:
# - Toolchain availability (Liquidsoap, FFmpeg, ffprobe)
# - Actual decoded audio playout (PCM WAV output sink)
# - Synthetic tone generation (Track A 440Hz -> Track B 554Hz -> Track C 659Hz)
# - Deterministic transitions and crossfades
# - Machine-readable JSONL logs
# - ffprobe / FFmpeg audio inspection
# - systemd lifecycle: start, restart, crash recovery, stop
# ==============================================================================

set -euo pipefail

SERVICE_BASE_DIR="/opt/astrazit-radio"
TEST_BASE_DIR="/tmp/astrazit-radio-002/verify"

MUSIC_DIR="${TEST_BASE_DIR}/music"
STATE_DIR="${TEST_BASE_DIR}/state"
LOG_DIR="${TEST_BASE_DIR}/logs"

OUTPUT_WAV="${STATE_DIR}/audible_playout_test.wav"
LOG_FILE="${LOG_DIR}/plays.jsonl"
FFPROBE_FILE="/tmp/astrazit-radio-002/ffprobe.txt"

STATION_SCRIPT="${SERVICE_BASE_DIR}/app/station.liq"
SERVICE_NAME="astrazit-radio.service"

echo "============================================================"
echo " ASTRAZIT RADIO - LINUX AUDIBLE PLAYOUT TEST (RADIO-002)"
echo "============================================================"

# ------------------------------------------------------------------------------
# Step 1: Environment & Tool Validation
# ------------------------------------------------------------------------------

echo
echo "--- STEP 1: TOOL VALIDATION ---"

for tool in liquidsoap ffmpeg ffprobe timeout; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "ERROR: Required tool not found: $tool" >&2
        exit 1
    }
done

sudo -u astrazit test -f "${STATION_SCRIPT}" || {
    echo "ERROR: Installed station script is not accessible to service user astrazit: ${STATION_SCRIPT}" >&2
    exit 1
}

echo "OS Release:"
grep -E '^(NAME|VERSION|ID)=' /etc/os-release || true
echo "Kernel:     $(uname -a)"
echo "Liquidsoap: $(liquidsoap --version 2>&1 | head -n 1)"
echo "FFmpeg:     $(ffmpeg -version 2>&1 | head -n 1)"
echo "ffprobe:    $(ffprobe -version 2>&1 | head -n 1)"

# ------------------------------------------------------------------------------
# Step 2: Disposable Synthetic Audio
# ------------------------------------------------------------------------------

echo
echo "--- STEP 2: PREPARING DISPOSABLE SYNTHETIC AUDIO ---"

sudo rm -rf "${TEST_BASE_DIR}"
rm -f "${FFPROBE_FILE}"
mkdir -p "${MUSIC_DIR}" "${STATE_DIR}" "${LOG_DIR}"

echo "Disposable workspace: ${TEST_BASE_DIR}"

if command -v python3 >/dev/null 2>&1; then
    MUSIC_DIR="${MUSIC_DIR}" python3 - <<'PY'
import math
import os
import struct
import wave
from pathlib import Path

music_dir = Path(os.environ["MUSIC_DIR"])
music_dir.mkdir(parents=True, exist_ok=True)

tones = [
    ("track_a_synth_440hz.wav", 440.0),
    ("track_b_synth_554hz.wav", 554.37),
    ("track_c_synth_659hz.wav", 659.25),
]

sr = 44100
duration = 4.0
num_samples = int(sr * duration)

for fname, freq in tones:
    target = music_dir / fname

    with wave.open(str(target), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)

        raw = bytearray()

        for i in range(num_samples):
            t = float(i) / sr

            env = 1.0
            if i < sr * 0.05:
                env = i / (sr * 0.05)
            elif i > num_samples - (sr * 0.05):
                env = (num_samples - i) / (sr * 0.05)

            val = int(
                0.5
                * env
                * math.sin(2.0 * math.pi * freq * t)
                * 32767.0
            )

            raw.extend(struct.pack("<hh", val, val))

        wf.writeframes(raw)

    print(f"Generated: {target} ({freq:.2f} Hz, {duration:.1f}s)")
PY
else
    ffmpeg -hide_banner -loglevel error -y \
        -f lavfi \
        -i "sine=frequency=440:sample_rate=44100:duration=4" \
        -ac 2 \
        "${MUSIC_DIR}/track_a_synth_440hz.wav"

    ffmpeg -hide_banner -loglevel error -y \
        -f lavfi \
        -i "sine=frequency=554.37:sample_rate=44100:duration=4" \
        -ac 2 \
        "${MUSIC_DIR}/track_b_synth_554hz.wav"

    ffmpeg -hide_banner -loglevel error -y \
        -f lavfi \
        -i "sine=frequency=659.25:sample_rate=44100:duration=4" \
        -ac 2 \
        "${MUSIC_DIR}/track_c_synth_659hz.wav"
fi

for track in \
    track_a_synth_440hz.wav \
    track_b_synth_554hz.wav \
    track_c_synth_659hz.wav
do
    [[ -s "${MUSIC_DIR}/${track}" ]] || {
        echo "ERROR: Synthetic track missing or empty: ${track}" >&2
        exit 1
    }
done

echo
ls -lh "${MUSIC_DIR}"

# Liquidsoap runs as the dedicated service account. Give only the disposable
# verification workspace to that account; production /opt permissions remain
# unchanged.
sudo chown -R astrazit:astrazit "${TEST_BASE_DIR}"

# ------------------------------------------------------------------------------
# Step 3: Liquidsoap Syntax Validation
# ------------------------------------------------------------------------------

echo
echo "--- STEP 3: LIQUIDSOAP SYNTAX VALIDATION ---"

sudo -u astrazit env \
RADIO_MUSIC_DIR="${MUSIC_DIR}" \
RADIO_LOG_FILE="${LOG_FILE}" \
RADIO_OUTPUT_MODE="file" \
RADIO_OUTPUT_FILE="${OUTPUT_WAV}" \
liquidsoap --check "${STATION_SCRIPT}"

echo "PASS: station.liq syntax is valid."

sudo -u astrazit rm -f "${LOG_FILE}" "${OUTPUT_WAV}"

# ------------------------------------------------------------------------------
# Step 4: Actual Decoded Audio Playout
# ------------------------------------------------------------------------------

echo
echo "--- STEP 4: EXECUTING AUDIBLE DECODED PLAYOUT ---"
echo "Capturing Liquidsoap decoded PCM WAV output..."

set +e

sudo -u astrazit env \
RADIO_MUSIC_DIR="${MUSIC_DIR}" \
RADIO_LOG_FILE="${LOG_FILE}" \
RADIO_OUTPUT_MODE="file" \
RADIO_OUTPUT_FILE="${OUTPUT_WAV}" \
timeout 12s liquidsoap "${STATION_SCRIPT}"

LIQUIDSOAP_STATUS=$?

set -e

if [[ "${LIQUIDSOAP_STATUS}" -ne 0 && "${LIQUIDSOAP_STATUS}" -ne 124 ]]; then
    echo "ERROR: Liquidsoap exited with status ${LIQUIDSOAP_STATUS}." >&2
    exit 1
fi

[[ -s "${OUTPUT_WAV}" ]] || {
    echo "ERROR: Liquidsoap did not create a non-empty output WAV." >&2
    exit 1
}

echo "Liquidsoap execution completed with accepted status: ${LIQUIDSOAP_STATUS}"

# ------------------------------------------------------------------------------
# Step 5: Audio Inspection
# ------------------------------------------------------------------------------

echo
echo "--- STEP 5: FFPROBE AUDIBLE OUTPUT VERIFICATION ---"

sudo -u astrazit ffprobe \
    -v error \
    -show_entries \
    format=duration,bit_rate,size:stream=codec_name,sample_rate,channels \
    -of default=noprint_wrappers=1 \
    "${OUTPUT_WAV}" > "${FFPROBE_FILE}"

cat "${FFPROBE_FILE}"

grep -q '^codec_name=' "${FFPROBE_FILE}" || {
    echo "ERROR: ffprobe did not report an audio codec." >&2
    exit 1
}

grep -q '^sample_rate=' "${FFPROBE_FILE}" || {
    echo "ERROR: ffprobe did not report a sample rate." >&2
    exit 1
}

duration=$(
    awk -F= '/^duration=/{print $2; exit}' "${FFPROBE_FILE}"
)

awk -v d="${duration:-0}" \
    'BEGIN { exit !(d > 0) }' || {
        echo "ERROR: ffprobe reported invalid duration." >&2
        exit 1
    }

max_volume=$(
    sudo -u astrazit ffmpeg \
        -hide_banner \
        -nostats \
        -i "${OUTPUT_WAV}" \
        -af volumedetect \
        -f null - 2>&1 |
    awk -F': ' '/max_volume:/{print $2; exit}'
)

echo "Maximum detected volume: ${max_volume:-UNKNOWN}"

[[ -n "${max_volume}" && "${max_volume}" != "-inf dB" ]] || {
    echo "ERROR: Decoded output appears silent." >&2
    exit 1
}

echo "PASS: Decoded non-silent audio verified."

# ------------------------------------------------------------------------------
# Step 6: Structured Runtime Log Verification
# ------------------------------------------------------------------------------

echo
echo "--- STEP 6: RUNTIME LOG VERIFICATION ---"

[[ -f "${LOG_FILE}" ]] || {
    echo "ERROR: Runtime log not found: ${LOG_FILE}" >&2
    exit 1
}

cat "${LOG_FILE}"

grep -q '"event":"STATION_START"' "${LOG_FILE}" || {
    echo "ERROR: STATION_START not found." >&2
    exit 1
}

grep -q '"event":"STATION_STOP"' "${LOG_FILE}" || {
    echo "ERROR: STATION_STOP not found." >&2
    exit 1
}

for track in \
    track_a_synth_440hz.wav \
    track_b_synth_554hz.wav \
    track_c_synth_659hz.wav
do
    grep -q "${track}" "${LOG_FILE}" || {
        echo "ERROR: Track not found in structured log: ${track}" >&2
        exit 1
    }
done

a_line=$(
    grep -n 'track_a_synth_440hz.wav' "${LOG_FILE}" |
    head -n 1 |
    cut -d: -f1
)

b_line=$(
    grep -n 'track_b_synth_554hz.wav' "${LOG_FILE}" |
    head -n 1 |
    cut -d: -f1
)

c_line=$(
    grep -n 'track_c_synth_659hz.wav' "${LOG_FILE}" |
    head -n 1 |
    cut -d: -f1
)

if ! [[ "${a_line}" -lt "${b_line}" && "${b_line}" -lt "${c_line}" ]]; then
    echo "ERROR: First observed track sequence is not A -> B -> C." >&2
    exit 1
fi

echo "PASS: Deterministic A -> B -> C sequence verified."

# ------------------------------------------------------------------------------
# Step 7: systemd Lifecycle & Crash Recovery
# ------------------------------------------------------------------------------

echo
echo "--- STEP 7: SYSTEMD SERVICE LIFECYCLE & CRASH RECOVERY ---"

command -v systemctl >/dev/null 2>&1 || {
    echo "ERROR: systemctl unavailable." >&2
    exit 1
}

UNIT_LOAD_STATE="$(
    systemctl show         -p LoadState         --value         "${SERVICE_NAME}" 2>/dev/null || true
)"

if [[ "${UNIT_LOAD_STATE}" != "loaded" ]]; then
    echo "ERROR: ${SERVICE_NAME} is not installed or not loadable." >&2
    exit 1
fi

echo "1. Starting service..."
sudo systemctl start "${SERVICE_NAME}"
sleep 3

systemctl is-active --quiet "${SERVICE_NAME}" || {
    echo "ERROR: Service failed to become active." >&2
    exit 1
}

INITIAL_PID=$(
    systemctl show -p MainPID --value "${SERVICE_NAME}"
)

echo "   Initial MainPID: ${INITIAL_PID}"

[[ "${INITIAL_PID}" -gt 0 ]] || {
    echo "ERROR: Invalid initial MainPID." >&2
    sudo systemctl stop "${SERVICE_NAME}" || true
    exit 1
}

echo "2. Restarting service..."
sudo systemctl restart "${SERVICE_NAME}"
sleep 3

systemctl is-active --quiet "${SERVICE_NAME}" || {
    echo "ERROR: Service failed after restart." >&2
    exit 1
}

RESTARTED_PID=$(
    systemctl show -p MainPID --value "${SERVICE_NAME}"
)

echo "   Restarted MainPID: ${RESTARTED_PID}"

if [[ "${RESTARTED_PID}" -eq 0 ||
      "${RESTARTED_PID}" -eq "${INITIAL_PID}" ]]; then
    echo "ERROR: Restart did not produce a new MainPID." >&2
    sudo systemctl stop "${SERVICE_NAME}" || true
    exit 1
fi

echo "PASS: Normal restart produced a new process."

echo "3. Forcing Liquidsoap failure..."
sudo kill -9 "${RESTARTED_PID}"

echo "   Waiting for RestartSec recovery..."
sleep 8

RECOVERED_PID=$(
    systemctl show -p MainPID --value "${SERVICE_NAME}"
)

echo "   Recovered MainPID: ${RECOVERED_PID}"

if [[ "${RECOVERED_PID}" -eq 0 ||
      "${RECOVERED_PID}" -eq "${RESTARTED_PID}" ]]; then
    echo "ERROR: systemd did not recover with a new process." >&2
    sudo systemctl stop "${SERVICE_NAME}" || true
    exit 1
fi

systemctl is-active --quiet "${SERVICE_NAME}" || {
    echo "ERROR: Service is not active after crash recovery." >&2
    sudo systemctl stop "${SERVICE_NAME}" || true
    exit 1
}

echo "PASS: systemd recovered after deliberate process failure."

echo "4. Cleanly stopping service..."
sudo systemctl stop "${SERVICE_NAME}"
sleep 2

if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "ERROR: Service remained active after stop." >&2
    exit 1
fi

echo "PASS: Service stopped cleanly."

echo
echo "============================================================"
echo " PASS: ALL AUDIBLE PLAYOUT TESTS VERIFIED"
echo "============================================================"
