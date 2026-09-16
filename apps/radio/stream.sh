#!/usr/bin/env bash
# ==============================================================================
# AstraZit Radio - Production FFmpeg Video Stream Supervisor
# Governed by RADIO-003, ADR-002, ADR-006, and ADR-008.
#
# Multiplexes:
# - Video: 1280x720, 30 fps, H.264, 4 Mbps CBR, 2s GOP (-stream_loop -1)
# - Audio: AAC stereo, 44.1 kHz, 128 kbps from Liquidsoap Harbor (127.0.0.1:8000)
# - Output: RTMPS to YouTube Live or local FLV sink for verification
# ==============================================================================
set -euo pipefail
set +x

# Directory Defaults
BASE_DIR="${BASE_DIR:-/opt/astrazit-radio}"

# Stream Input / Output Configuration (supplied strictly via runtime environment or systemd EnvironmentFile)
STREAM_INPUT_VIDEO="${STREAM_INPUT_VIDEO:-${BASE_DIR}/assets/visual_loop.mp4}"
STREAM_INPUT_AUDIO="${STREAM_INPUT_AUDIO:-http://127.0.0.1:8000/radio.wav}"
STREAM_OUTPUT_MODE="${STREAM_OUTPUT_MODE:-youtube}"
STREAM_OUTPUT_FILE="${STREAM_OUTPUT_FILE:-${BASE_DIR}/state/test_stream.flv}"
YOUTUBE_RTMPS_BASE="${YOUTUBE_RTMPS_BASE:-rtmps://a.rtmps.youtube.com/live2}"
STREAM_DURATION="${STREAM_DURATION-0}"  # 0 = infinite, >0 = limit in seconds

# Validate STREAM_DURATION (fail-closed, must be non-negative integer)
if [[ ! "${STREAM_DURATION}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: STREAM_DURATION must be a non-negative integer." >&2
    exit 1
fi

echo "============================================================"
echo " AstraZit Radio - FFmpeg Streaming Engine (RADIO-003)"
echo "============================================================"
echo "Video Loop:   ${STREAM_INPUT_VIDEO}"
echo "Audio Source: ${STREAM_INPUT_AUDIO}"
echo "Output Mode:  ${STREAM_OUTPUT_MODE}"

# 1. Validate Visual Input
if [[ ! -f "${STREAM_INPUT_VIDEO}" ]]; then
    echo "ERROR: Video loop asset not found: ${STREAM_INPUT_VIDEO}" >&2
    echo "Generate with: bash $(dirname "$0")/../../scripts/linux/generate_visual_loop.sh" >&2
    exit 1
fi

# 2. Output Destination Resolution
EXTRA_ARGS=()
OUTPUT_NETWORK_ARGS=()
if [[ "${STREAM_DURATION}" -gt 0 ]]; then
    EXTRA_ARGS+=("-t" "${STREAM_DURATION}")
fi

if [[ "${STREAM_OUTPUT_MODE}" == "file" ]]; then
    mkdir -p "$(dirname "${STREAM_OUTPUT_FILE}")"
    TARGET_URL="${STREAM_OUTPUT_FILE}"
    echo "Target File:  ${TARGET_URL}"
elif [[ "${STREAM_OUTPUT_MODE}" == "youtube" ]]; then
    if [[ "${YOUTUBE_RTMPS_BASE}" != rtmps://* ]]; then
        echo "ERROR: YOUTUBE_RTMPS_BASE must use secure rtmps:// transport." >&2
        exit 1
    fi
    STREAM_KEY="${STREAM_KEY:-}"
    if [[ -z "${STREAM_KEY//[[:space:]]/}" ]]; then
        echo "ERROR: STREAM_KEY is not defined or is whitespace-only in environment." >&2
        echo "Supply a valid non-empty STREAM_KEY via runtime environment or systemd EnvironmentFile." >&2
        exit 1
    fi
    TARGET_URL="${YOUTUBE_RTMPS_BASE}/${STREAM_KEY}"
    # Network I/O timeout: 15 seconds (in microseconds) for RTMPS network writes
    OUTPUT_NETWORK_ARGS+=(
        "-rw_timeout"
        "15000000"
    )
    echo "Target:       YouTube Live (RTMPS secure ingest)"
else
    echo "ERROR: Unknown STREAM_OUTPUT_MODE: ${STREAM_OUTPUT_MODE} (expected 'youtube' or 'file')" >&2
    exit 1
fi

echo "============================================================"
echo "Starting FFmpeg multiplexing and encoding pipeline..."
echo "============================================================"

# Execute FFmpeg Pipeline:
# - Video: 1280x720 30fps, libx264 veryfast, stillimage tune, 2500k CBR, 2s keyframe (g=60)
# - Rate Control: 2500 Kbps enforced CBR video with x264 HRD filler (nal-hrd=cbr:force-cfr=1).
#   x264 HRD filler is required because static/low-motion graphics otherwise collapse to ~100 Kbps wire bitrate.
# - Audio: AAC stereo 44.1kHz, 128kbps from Liquidsoap Harbor
# - Expected aggregate ingest bitrate: ~2.6 Mbps (2500k video + 128k audio)
# - Resilient reconnect on audio HTTP input
FFMPEG_CMD=(
    ffmpeg
    -hide_banner
    -loglevel warning
    -re
    -stream_loop -1
    -i "${STREAM_INPUT_VIDEO}"
    -reconnect 1
    -reconnect_at_eof 1
    -reconnect_streamed 1
    -reconnect_delay_max 2
    -i "${STREAM_INPUT_AUDIO}"
    -map 0:v:0
    -map 1:a:0
    -c:v libx264
    -preset veryfast
    -tune stillimage
    -b:v 2500k
    -minrate 2500k
    -maxrate 2500k
    -bufsize 5000k
    -x264-params "nal-hrd=cbr:force-cfr=1"
    -pix_fmt yuv420p
    -r 30
    -g 60
    -keyint_min 60
    -sc_threshold 0
    -c:a aac
    -b:a 128k
    -ar 44100
    -ac 2
    -progress pipe:1
    "${EXTRA_ARGS[@]}"
    "${OUTPUT_NETWORK_ARGS[@]}"
    -f flv
    "${TARGET_URL}"
)

# Watchdog Supervisor Script Path
WATCHDOG_SCRIPT="${BASE_DIR}/app/stream_watchdog.py"
if [[ ! -f "${WATCHDOG_SCRIPT}" ]]; then
    # Fallback to relative repository location if running in developer tree
    WATCHDOG_SCRIPT="$(dirname "$0")/stream_watchdog.py"
fi

# Resolve valid Python interpreter for watchdog supervisor
PYTHON_BIN=""
for cand in python3 python; do
    if command -v "${cand}" >/dev/null 2>&1; then
        if "${cand}" -c "import sys" >/dev/null 2>&1; then
            PYTHON_BIN="${cand}"
            break
        fi
    fi
done


if [[ "${STREAM_OUTPUT_MODE}" == "youtube" ]]; then
    # In YouTube/RTMPS mode, raw FFmpeg diagnostics on stderr could leak the stream key
    # if connection initialization fails. The stream_watchdog supervisor redirects
    # child stderr to /dev/null and reads machine-readable progress from pipe:1,
    # detecting progress stalls and initiating bounded termination recovery.
    if [[ -n "${PYTHON_BIN}" && -f "${WATCHDOG_SCRIPT}" ]]; then
        set +e
        "${PYTHON_BIN}" "${WATCHDOG_SCRIPT}" "${FFMPEG_CMD[@]}"
        SUPERVISOR_STATUS=$?
        set -e
        if [[ "${SUPERVISOR_STATUS}" -ne 0 ]]; then
            echo "ERROR: FFmpeg publisher exited with status ${SUPERVISOR_STATUS}." >&2
            exit "${SUPERVISOR_STATUS}"
        fi
    else
        # GK-P2: Fail-closed requirement in YouTube mode.
        # If Python or stream_watchdog.py is unavailable, DO NOT fall back to unsupervised FFmpeg.
        # Exit non-zero with a sanitized diagnostic to avoid repeating the RADIO-006 silent hang defect.
        echo "ERROR: Supervised YouTube publishing requires Python and ${WATCHDOG_SCRIPT}." >&2
        echo "ERROR: Watchdog supervisor is unavailable. Failing closed to prevent unsupervised publishing hang." >&2
        exit 1
    fi
else
    # In local file mode, no secrets exist; retain standard diagnostics for inspection.
    exec "${FFMPEG_CMD[@]}"
fi
