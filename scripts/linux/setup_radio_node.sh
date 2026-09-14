#!/usr/bin/env bash
# ==============================================================================
# AstraZit Music OS - Linux VPS Radio Node Setup
# Governed by RADIO-002, RADIO-003, ADR-002, ADR-006, and ADR-008.
# Target: Ubuntu 22.04 / 24.04 LTS or Debian 12 (bookworm)
# ==============================================================================
set -euo pipefail
set +x

echo "============================================================"
echo " AstraZit Radio Node Provisioning (RADIO-002 / RADIO-003)"
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
mkdir -p "${BASE_DIR}/assets"
mkdir -p "${BASE_DIR}/state"
mkdir -p "${BASE_DIR}/logs"
mkdir -p "${BASE_DIR}/config"

# 6. Install Station & Stream Scripts
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

STREAM_SRC="$(dirname "$0")/../../apps/radio/stream.sh"
if [[ -f "${STREAM_SRC}" ]]; then
    echo "--> Installing stream.sh from repo..."
    cp "${STREAM_SRC}" "${BASE_DIR}/app/stream.sh"
    chmod 750 "${BASE_DIR}/app/stream.sh"
elif [[ -f "./apps/radio/stream.sh" ]]; then
    echo "--> Installing stream.sh from ./apps/radio/..."
    cp "./apps/radio/stream.sh" "${BASE_DIR}/app/stream.sh"
    chmod 750 "${BASE_DIR}/app/stream.sh"
fi

# 7. Generate Visual Loop Asset if missing
if [[ ! -f "${BASE_DIR}/assets/visual_loop.mp4" ]]; then
    echo "--> Generating visual loop asset under ${BASE_DIR}/assets/visual_loop.mp4..."
    GEN_LOOP_SRC="$(dirname "$0")/generate_visual_loop.sh"
    if [[ -f "${GEN_LOOP_SRC}" ]]; then
        bash "${GEN_LOOP_SRC}" "${BASE_DIR}/assets/visual_loop.mp4" 10
    fi
fi

# 8. Template stream.env if missing (mode 0600, secrets isolation, never overwrite existing)
if [[ ! -f "${BASE_DIR}/config/stream.env" ]]; then
    echo "--> Creating stream.env template (mode 0600)..."
    cat > "${BASE_DIR}/config/stream.env" <<'EOF'
# AstraZit Radio YouTube Stream Configuration (RADIO-003)
# Permissions must remain 0600. NEVER commit this file to version control.
STREAM_KEY=
STREAM_OUTPUT_MODE=youtube
EOF
    chmod 600 "${BASE_DIR}/config/stream.env"
fi

# 9. Apply Safe Permissions (restricted non-root ownership)
echo "--> Setting permissions (0750) and ownership (astrazit:astrazit)..."
chown -R astrazit:astrazit "${BASE_DIR}"
chmod 750 "${BASE_DIR}"
chmod 750 "${BASE_DIR}/app" "${BASE_DIR}/music" "${BASE_DIR}/assets" "${BASE_DIR}/state" "${BASE_DIR}/logs" "${BASE_DIR}/config"
chmod 600 "${BASE_DIR}/config/stream.env" 2>/dev/null || true

# 10. Check Host-Side Process Isolation Prerequisite for Stream Publisher
check_host_proc_isolation() {
    local proc_opts
    if command -v findmnt >/dev/null 2>&1; then
        proc_opts="$(findmnt -n -o OPTIONS /proc 2>/dev/null || true)"
    else
        proc_opts="$(awk '$2 == "/proc" { print $4 }' /proc/mounts 2>/dev/null || true)"
    fi
    if echo "${proc_opts}" | grep -qE '\bhidepid=(2|invisible)\b'; then
        return 0
    fi
    return 1
}

echo "--> Checking host /proc process isolation prerequisite..."
if ! check_host_proc_isolation; then
    echo "ERROR: Production host prerequisite failed: /proc is not mounted with hidepid=2 or hidepid=invisible." >&2
    echo "Security requirement: Unrelated local host users must not be able to inspect process arguments in /proc." >&2
    echo "Action required on host: Mount /proc with hidepid=2 (e.g. in /etc/fstab: proc /proc proc defaults,hidepid=2 0 0)." >&2
    echo "Failing closed: astrazit-stream.service will NOT be installed or enabled until host protection is active." >&2
    exit 1
fi

# 11. Install Systemd Service Units (Playout & Streaming) and Harbor Drop-in
RADIO_DROPIN_SRC="$(dirname "$0")/../../apps/radio/systemd/astrazit-radio.service.d/20-harbor.conf"
RADIO_DROPIN_DEST_DIR="/etc/systemd/system/astrazit-radio.service.d"
if [[ -f "${RADIO_DROPIN_SRC}" ]]; then
    echo "--> Installing astrazit-radio.service harbor drop-in..."
    mkdir -p "${RADIO_DROPIN_DEST_DIR}"
    cp "${RADIO_DROPIN_SRC}" "${RADIO_DROPIN_DEST_DIR}/20-harbor.conf"
    chmod 644 "${RADIO_DROPIN_DEST_DIR}/20-harbor.conf"
elif [[ -f "./apps/radio/systemd/astrazit-radio.service.d/20-harbor.conf" ]]; then
    echo "--> Installing astrazit-radio.service harbor drop-in from ./apps/radio/..."
    mkdir -p "${RADIO_DROPIN_DEST_DIR}"
    cp "./apps/radio/systemd/astrazit-radio.service.d/20-harbor.conf" "${RADIO_DROPIN_DEST_DIR}/20-harbor.conf"
    chmod 644 "${RADIO_DROPIN_DEST_DIR}/20-harbor.conf"
fi

for svc_unit in "astrazit-radio.service" "astrazit-stream.service"; do
    SVC_SRC="$(dirname "$0")/../../apps/radio/systemd/${svc_unit}"
    SVC_DEST="/etc/systemd/system/${svc_unit}"
    if [[ -f "${SVC_SRC}" ]]; then
        echo "--> Installing systemd service unit ${svc_unit}..."
        cp "${SVC_SRC}" "${SVC_DEST}"
        chmod 644 "${SVC_DEST}"
    elif [[ -f "./apps/radio/systemd/${svc_unit}" ]]; then
        echo "--> Installing systemd service unit from ./apps/radio/systemd/${svc_unit}..."
        cp "./apps/radio/systemd/${svc_unit}" "${SVC_DEST}"
        chmod 644 "${SVC_DEST}"
    fi
done

systemctl daemon-reload
systemctl enable astrazit-radio.service
echo "--> Playout service (astrazit-radio.service) enabled."

# If playout service is already active, restart it so updated station/drop-in config takes effect
if systemctl is-active --quiet astrazit-radio.service; then
    echo "--> Playout service is active; restarting astrazit-radio to apply updated configuration..."
    systemctl restart astrazit-radio.service
fi

# astrazit-stream.service must NOT be enabled or started automatically by setup.
# Publisher activation is an explicit operator action after verifying configuration and installing a valid STREAM_KEY.
STREAM_ENV_FILE="${BASE_DIR}/config/stream.env"
echo "--> NOTE: astrazit-stream.service installed but NOT enabled."
echo "    Configure ${STREAM_ENV_FILE} securely (mode 0600)."
echo "    Validate configuration and explicitly enable/start the service only during an authorized live activation step:"
echo "    sudo systemctl enable --now astrazit-stream.service"

# 12. Verify Tooling
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
echo "Run verification:  bash $(dirname "$0")/verify_youtube_stream.sh"
echo "============================================================"
