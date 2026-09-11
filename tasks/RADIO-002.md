# Task RADIO-002: Linux VPS Audible Playout Runtime

## Summary
Establish the production Linux VPS audible playout runtime assets for **AstraZit Radio**, enabling deterministic audio decoding, transitions, and autonomous systemd recovery using Liquidsoap and FFmpeg/ffprobe without Google Cloud, without YouTube, and without external LLM calls.

## Metadata
- **Ticket ID**: `RADIO-002`
- **Status**: `COMPLETE — LINUX VALIDATED`
- **Assignee**: `Antigravity Agent`
- **Component**: `apps/radio`, `scripts/linux`, `docs/architecture`
- **Parent Ticket / Milestone**: `Phase 0 / Application #1 (Radio Foundation)`
- **Target Completion**: `2026-09-10`

---

## Deliverables

1. **Systemd Daemon Configuration (`apps/radio/systemd/astrazit-radio.service`)**:
   - Production systemd unit executing as unprivileged user `astrazit`.
   - Explicit WorkingDirectory `/opt/astrazit-radio`.
   - Process supervisor restart policy (`Restart=always`, `RestartSec=5s`).
   - Sandbox hardening (`ProtectSystem=full`, `ProtectHome=true`, `NoNewPrivileges=true`, `PrivateTmp=true`).
   - Standardized output to journald.
   - Zero secrets, zero stream keys, zero cloud credentials.

2. **Liquidsoap Playout Configuration (`apps/radio/station.liq`)**:
   - Updated directory conventions targeting standard `/opt/astrazit-radio/` layout.
   - Added dual-mode output sink selection (`RADIO_OUTPUT_MODE=dummy` for headless daemon; `RADIO_OUTPUT_MODE=file` for verifiable PCM WAV decoding).
   - Added station lifecycle events (`STATION_START`, `STATION_STOP`) to `plays.jsonl`.
   - Maintained zero-dead-air 440Hz emergency sine tone fallback.
   - Preserved strict Linux LF line endings.

3. **Linux Node Provisioning Script (`scripts/linux/setup_radio_node.sh`)**:
   - Automated provisioning script for Ubuntu 22.04/24.04 LTS and Debian 12.
   - Installs Liquidsoap, FFmpeg, ffprobe, python3, and utilities via apt.
   - Provisions `/opt/astrazit-radio/{app,music,state,logs,config}` tree with `0750` permissions.
   - Configures dedicated unprivileged service user `astrazit`.
   - Deploys and enables systemd service daemon.

4. **Audible Playout Verification Protocol (`scripts/linux/verify_audible_playout.sh`)**:
   - Automated verification test suite.
   - Validates toolchain versions (`liquidsoap`, `ffmpeg`, `ffprobe`, `uname`, `os-release`).
   - Generates 3-tone synthetic audio test sequence (440Hz, 554.37Hz, 659.25Hz).
   - Executes Liquidsoap in decoded PCM WAV capture mode.
   - Verifies decoded audio properties and duration with `ffprobe`.
   - Verifies JSONL runtime logs.
   - Validates systemd lifecycle (`start`, `status`, `restart`, deliberate `kill -9` crash recovery, and `stop`).

5. **Architecture Documentation & Skill Updates**:
   - `docs/architecture/LINUX_RADIO_RUNTIME.md`: Full architecture, directory layout, systemd service, commands, and security posture.
   - `.agents/skills/liquidsoap-radio/SKILL.md`: Updated with Linux VPS runtime paths, systemd commands, and verification protocols.

6. **Automated Unit & Invariant Tests (`tests/test_radio_linux_runtime.py`)**:
   - Unit tests validating systemd unit configuration, hardening flags, and forbidden token boundaries.
   - Script integrity tests verifying LF line endings, POSIX shell syntax, and safe directory permissions.

---

## Acceptance Criteria
- [x] Pre-flight Git checks passed (branch `feat/RADIO-002-linux-audible-playout`, base `0743f37`, clean working tree).
- [x] Linux runtime validated on the provisioned Ubuntu 24.04.5 VPS using the dedicated `astrazit` service account, Liquidsoap 2.2.4, FFmpeg 6.1.1, ffprobe, and systemd.
- [x] Canonical Linux runtime directory layout defined under `/opt/astrazit-radio/`.
- [x] Dedicated unprivileged system user `astrazit` configured.
- [x] Systemd service unit `astrazit-radio.service` created with `Restart=always`, `RestartSec=5s`, and filesystem isolation.
- [x] `station.liq` updated with `/opt/astrazit-radio` paths, dual output sink selection (dummy and decoded file sink), and lifecycle logging.
- [x] Synthetic tone verification protocol defined (Track A 440Hz -> Track B 554.37Hz -> Track C 659.25Hz).
- [x] Real decoded audio playout verified on Ubuntu 24.04.5 with Liquidsoap 2.2.4 and FFmpeg/ffprobe 6.1.1; PCM stereo 44.1 kHz non-silent output confirmed.
- [x] systemd start, normal restart, deliberate process failure, automatic recovery, new PID, and clean stop verified on the Linux VPS.
- [x] Zero YouTube, zero RTMPS, zero stream keys, zero cloud billing.
- [x] Automated asset test suite passes cleanly (`test_radio_linux_runtime.py` and full regression suite).
- [x] Schema diff against base `0743f37` is clean (0 changes to `packages/schemas`).
- [x] `git diff --check` is clean.
