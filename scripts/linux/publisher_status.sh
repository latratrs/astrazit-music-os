#!/usr/bin/env bash
# ==============================================================================
# AstraZit Radio - Secret-Safe Publisher Operational Status Check
# Governed by RADIO-004, ADR-002, ADR-006, and ADR-008.
#
# Secret-Safe Invariants:
# - ZERO inspection of process argv or command lines
# - ZERO dumps of environment variables
# - ZERO exposure of stream secrets or full RTMPS URLs
# - Inspects service state via systemctl is-active / is-enabled / show properties
# - Inspects local Harbor health via loopback HTTP probe
# ==============================================================================
set -euo pipefail
set +x

STREAM_SERVICE="astrazit-stream.service"
RADIO_SERVICE="astrazit-radio.service"
HARBOR_URL="http://127.0.0.1:8000/radio.wav"

echo "============================================================"
echo " AstraZit Radio Publisher Operational Status (RADIO-004)"
echo "============================================================"

# 1. Radio Playout Service State
RADIO_ACTIVE="$(systemctl is-active "${RADIO_SERVICE}" 2>/dev/null || true)"
RADIO_ENABLED="$(systemctl is-enabled "${RADIO_SERVICE}" 2>/dev/null || true)"
printf "%-26s: %s (enabled: %s)\n" "Radio Service" "${RADIO_ACTIVE:-unknown}" "${RADIO_ENABLED:-unknown}"

# 2. Local Harbor Audio Health Check
HARBOR_CODE="$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 --max-time 3 "${HARBOR_URL}" 2>/dev/null || true)"
if [[ "${HARBOR_CODE}" == "200" ]]; then
    printf "%-26s: PASS (HTTP %s on 127.0.0.1:8000)\n" "Harbor Audio Sink" "${HARBOR_CODE}"
else
    printf "%-26s: FAIL (HTTP %s on 127.0.0.1:8000)\n" "Harbor Audio Sink" "${HARBOR_CODE:-unreachable}"
fi

# 3. Stream Publisher Service State
STREAM_ACTIVE="$(systemctl is-active "${STREAM_SERVICE}" 2>/dev/null || true)"
STREAM_ENABLED="$(systemctl is-enabled "${STREAM_SERVICE}" 2>/dev/null || true)"
printf "%-26s: %s (enabled: %s)\n" "Publisher Service" "${STREAM_ACTIVE:-unknown}" "${STREAM_ENABLED:-unknown}"

# 4. Service Properties (MainPID, NRestarts, ActiveEnterTimestamp)
SHOW_OUT="$(systemctl show "${STREAM_SERVICE}" -p MainPID -p NRestarts -p ActiveEnterTimestamp -p SubState 2>/dev/null || true)"
MAIN_PID="$(echo "${SHOW_OUT}" | awk -F= '$1=="MainPID"{print $2}')"
N_RESTARTS="$(echo "${SHOW_OUT}" | awk -F= '$1=="NRestarts"{print $2}')"
SUB_STATE="$(echo "${SHOW_OUT}" | awk -F= '$1=="SubState"{print $2}')"

printf "%-26s: %s (SubState: %s)\n" "Publisher Main PID" "${MAIN_PID:-0}" "${SUB_STATE:-unknown}"
printf "%-26s: %s\n" "Publisher Restarts" "${N_RESTARTS:-0}"

# 5. Secret-Safe Process Hierarchy Check
# If MainPID > 0 and active, verify if child process exists via parent PID relationship only (no arguments inspection)
if [[ -n "${MAIN_PID}" && "${MAIN_PID}" =~ ^[0-9]+$ && "${MAIN_PID}" -gt 0 ]]; then
    CHILD_PIDS="$(pgrep -P "${MAIN_PID}" 2>/dev/null || true)"
    if [[ -n "${CHILD_PIDS}" ]]; then
        CHILD_COUNT="$(echo "${CHILD_PIDS}" | wc -w)"
        printf "%-26s: PASS (%d child process(es) active under PID %s)\n" "Child Process Tree" "${CHILD_COUNT}" "${MAIN_PID}"
    else
        printf "%-26s: NONE (no child processes under PID %s)\n" "Child Process Tree" "${MAIN_PID}"
    fi
else
    printf "%-26s: INACTIVE (publisher not running)\n" "Child Process Tree"
fi

# 6. Overall Failed Units Check (Systemd scope)
FAILED_UNITS="$(systemctl --failed --no-legend 2>/dev/null || true)"
if echo "${FAILED_UNITS}" | grep -q "${STREAM_SERVICE}"; then
    printf "%-26s: ALERT (%s is in failed state)\n" "Systemd Unit Health" "${STREAM_SERVICE}"
elif [[ -z "${FAILED_UNITS}" ]]; then
    printf "%-26s: PASS (zero failed units)\n" "Systemd Unit Health"
else
    FAILED_COUNT="$(echo "${FAILED_UNITS}" | wc -l)"
    printf "%-26s: WARN (%d failed unit(s) present, publisher not failed)\n" "Systemd Unit Health" "${FAILED_COUNT}"
fi

# 7. Last Sanitized Failure Message (Known wrapper error strings only, zero raw log dumps)
if [[ "${STREAM_ACTIVE}" != "active" ]]; then
    # Look strictly for known sanitized wrapper error signatures from journal
    LAST_SAN_ERR="$(journalctl -u "${STREAM_SERVICE}" -n 20 --no-pager 2>/dev/null | grep -E "ERROR: (FFmpeg publisher exited with status|secret is not defined|STREAM_DURATION must be|Video loop asset not found)" | tail -n 1 || true)"
    if [[ -n "${LAST_SAN_ERR}" ]]; then
        printf "%-26s: %s\n" "Last Sanitized Error" "${LAST_SAN_ERR}"
    fi
fi

echo "============================================================"