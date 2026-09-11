#!/usr/bin/env bash
# ==============================================================================
# AstraZit Music OS - Linux VPS Radio Node Setup
# Governed by RADIO-002, ADR-002, ADR-006, and ADR-008.
# Target: Ubuntu 22.04 / 24.04 LTS or Debian 12 (bookworm)
# ==============================================================================
set -euo pipefail

echo "============================================================"
echo " AstraZit Radio Node Provisioning (RADIO-002)"
echo "============================================================"

# 1. Privilege Check
if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: This script must be run as root or with sudo." >&2
    exit 1
fi

# 2. OS Environment Detection
if [[ -f /etc/os-release ]]; then
    # shellcheck source=/dev/null
    source /etc/os-release
    echo "Detected OS: ${NAME:-Linux} ${VERSION:-unknown}"
else
    echo "WARNING: /etc/os-release not found. Proceeding with standard Debian/Ubuntu assumptions."
fi

# 3. Package Installation (Liquidsoap, FFmpeg, ffprobe, python3)
echo "--> Updating package lists and installing core dependencies..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    liquidsoap \
    ffmpeg \
    python3 \
    curl \
    rsync \
    ca-certificates

# 4. Service User Creation
echo "--> Ensuring dedicated service user 'astrazit' exists..."
if ! id -u astrazit >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --shell /usr/sbin/nologin astrazit
    echo "    Created system user 'astrazit'."
else
    echo "    System user 'astrazit' already exists."
fi

# 5. Directory Layout Provisioning
BASE_DIR="/opt/astrazit-radio"
echo "--> Provisioning runtime directory tree under ${BASE_DIR}..."
mkdir -p "${BASE_DIR}/app"
mkdir -p "${BASE_DIR}/music"
mkdir -p "${BASE_DIR}/state"
mkdir -p "${BASE_DIR}/logs"
mkdir -p "${BASE_DIR}/config"

# 6. Install Station Script
SCRIPT_SRC="$(dirname "$0")/../../apps/radio/station.liq"
if [[ -f "${SCRIPT_SRC}" ]]; then
    echo "--> Installing station.liq from repo..."
    cp "${SCRIPT_SRC}" "${BASE_DIR}/app/station.liq"
elif [[ -f "./apps/radio/station.liq" ]]; then
    echo "--> Installing station.liq from ./apps/radio/..."
    cp "./apps/radio/station.liq" "${BASE_DIR}/app/station.liq"
else
    echo "WARNING: station.liq not found in relative repo path. Ensure it is placed in ${BASE_DIR}/app/station.liq manually."
fi

# 7. Apply Safe Permissions (restricted non-root ownership)
echo "--> Setting permissions (0750) and ownership (astrazit:astrazit)..."
chown -R astrazit:astrazit "${BASE_DIR}"
chmod 750 "${BASE_DIR}"
chmod 750 "${BASE_DIR}/app" "${BASE_DIR}/music" "${BASE_DIR}/state" "${BASE_DIR}/logs" "${BASE_DIR}/config"

# 8. Install Systemd Service Unit
SERVICE_SRC="$(dirname "$0")/../../apps/radio/systemd/astrazit-radio.service"
SERVICE_DEST="/etc/systemd/system/astrazit-radio.service"
if [[ -f "${SERVICE_SRC}" ]]; then
    echo "--> Installing systemd service unit to ${SERVICE_DEST}..."
    cp "${SERVICE_SRC}" "${SERVICE_DEST}"
elif [[ -f "./apps/radio/systemd/astrazit-radio.service" ]]; then
    echo "--> Installing systemd service unit from ./apps/radio/systemd/..."
    cp "./apps/radio/systemd/astrazit-radio.service" "${SERVICE_DEST}"
else
    echo "WARNING: astrazit-radio.service not found in relative repo path. Copying default unit..."
fi

chmod 644 "${SERVICE_DEST}"
systemctl daemon-reload
systemctl enable astrazit-radio.service
echo "--> Systemd daemon reloaded."

# 9. Verify Tooling
echo "============================================================"
echo " Tool Validation"
echo "============================================================"
echo "Liquidsoap: $(liquidsoap --version 2>&1 | head -n 1)"
echo "FFmpeg:     $(ffmpeg -version 2>&1 | head -n 1)"
echo "ffprobe:    $(ffprobe -version 2>&1 | head -n 1)"
echo "Kernel:     $(uname -a)"
echo "============================================================"
echo "SUCCESS: AstraZit Radio Linux VPS node configured."
echo "Playout directory: ${BASE_DIR}"
echo "Run verification:  bash $(dirname "$0")/verify_audible_playout.sh"
echo "============================================================"
