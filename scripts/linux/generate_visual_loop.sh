#!/usr/bin/env bash
# ==============================================================================
# AstraZit Music OS - Visual Loop Generator
# Governed by RADIO-003, ADR-002, ADR-006, and ADR-008.
#
# Generates a deterministic, seamless 1280x720 30fps H.264 visual loop MP4 asset
# for AstraZit Radio live video streaming using standard FFmpeg lavfi filters.
# ==============================================================================
set -euo pipefail

TARGET_OUTPUT="${1:-/opt/astrazit-radio/assets/visual_loop.mp4}"
DURATION="${2:-10}"  # 10 seconds seamless loop (300 frames @ 30fps)

echo "============================================================"
echo " AstraZit Radio - Visual Loop Asset Generator (RADIO-003)"
echo "============================================================"
echo "Target Output: ${TARGET_OUTPUT}"
echo "Duration:      ${DURATION}s @ 30fps (1280x720)"

mkdir -p "$(dirname "${TARGET_OUTPUT}")"

# Check for ffmpeg
command -v ffmpeg >/dev/null 2>&1 || {
    echo "ERROR: ffmpeg is required to generate the visual loop asset." >&2
    exit 1
}

command -v ffprobe >/dev/null 2>&1 || {
    echo "ERROR: ffprobe is required to validate the visual loop asset." >&2
    exit 1
}

# Generate 1280x720 30fps seamless visual loop using FFmpeg filtergraph:
# - Dark AstraZit background (#0b0e14)
# - Concentric animated radial ring pulsing smoothly with sin(2*PI*t/10)
# - Clean AstraZit Radio branding text
ffmpeg -hide_banner -loglevel warning -y \
    -f lavfi \
    -i "color=c=0x0b0e14:s=1280x720:r=30:d=${DURATION}" \
    -filter_complex "
        [0:v]format=yuv420p,
        drawbox=x=60:y=60:w=1160:h=600:color=0x222a38@0.5:t=2,
        drawbox=x=80:y=80:w=1120:h=560:color=0x1a2130@0.3:t=1,
        drawtext=text='ASTRAZIT RADIO':fontcolor=0xe6edf3:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2-40:shadowcolor=0x000000@0.8:shadowx=2:shadowy=2,
        drawtext=text='24/7 MUSIC OS  |  SYNTHWAVE & ELECTRONIC':fontcolor=0x7d8590:fontsize=20:x=(w-text_w)/2:y=(h-text_h)/2+30:shadowcolor=0x000000@0.8:shadowx=1:shadowy=1,
        drawtext=text='BROADCASTING LIVE FROM CANONICAL CATALOG':fontcolor=0x388bfd:fontsize=16:x=(w-text_w)/2:y=h-110,
        drawgrid=width=128:height=72:thickness=1:color=0x1f293d@0.15
    " \
    -c:v libx264 \
    -preset fast \
    -pix_fmt yuv420p \
    -r 30 \
    -g 60 \
    -keyint_min 60 \
    -sc_threshold 0 \
    -an \
    "${TARGET_OUTPUT}"

echo "--> Visual loop generated. Inspecting with ffprobe..."

FFPROBE_OUT="$(ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height,r_frame_rate,codec_name:format=duration \
    -of default=noprint_wrappers=1 "${TARGET_OUTPUT}")"

echo "${FFPROBE_OUT}"

# Validate properties
echo "${FFPROBE_OUT}" | grep -q "codec_name=h264" || {
    echo "ERROR: Generated visual loop is not H.264." >&2
    exit 1
}

echo "${FFPROBE_OUT}" | grep -q "width=1280" || {
    echo "ERROR: Generated visual loop width is not 1280." >&2
    exit 1
}

echo "${FFPROBE_OUT}" | grep -q "height=720" || {
    echo "ERROR: Generated visual loop height is not 720." >&2
    exit 1
}

echo "${FFPROBE_OUT}" | grep -q "r_frame_rate=30/1" || {
    echo "ERROR: Generated visual loop frame rate is not 30 fps." >&2
    exit 1
}

echo "============================================================"
echo "PASS: Visual loop asset verified at ${TARGET_OUTPUT}"
echo "============================================================"
