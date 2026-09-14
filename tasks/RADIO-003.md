# Task RADIO-003: YouTube Video Stream MVP

## Summary
Establish and validate the video streaming pipeline for **AstraZit Radio** from the Linux VPS host to YouTube Live. Multiplex continuous Liquidsoap audio playout with a branded 1280x720 30fps visual loop using FFmpeg, encode to YouTube Live's exact CBR broadcast specifications (H.264 @ ~4 Mbps, 2s GOP, AAC stereo 44.1 kHz @ 128 kbps), and stream securely over RTMPS without committing stream keys to Git.

## Metadata
- **Ticket ID**: `RADIO-003`
- **Status**: `COMPLETE — READY FOR HUMAN APPROVAL & COMMIT (T3 PASS)`
- **Assignee**: `Antigravity Agent`
- **Component**: `apps/radio`, `scripts/linux`, `docs/architecture`
- **Parent Ticket / Milestone**: `Phase 0 / Application #1 (Radio Foundation)`
- **Target Completion**: `2026-09-14`

---

## Deliverables

1. **Liquidsoap Harbor Audio Output Sink (`apps/radio/station.liq`)**:
   - Added `RADIO_OUTPUT_MODE=harbor` serving uncompressed PCM/WAV on `http://127.0.0.1:8000/radio.wav`.
   - Preserved backwards compatibility with `dummy` and `file` output modes.
   - Retained zero dead-air emergency fallback and structured JSONL logging.
   - Maintained strict Linux LF line endings.

2. **Systemd Drop-in Integration (`apps/radio/systemd/astrazit-radio.service.d/20-harbor.conf`)**:
   - Base `astrazit-radio.service` preserves default `dummy` mode from RADIO-002.
   - Drop-in unit overrides production service environment to `RADIO_OUTPUT_MODE=harbor` on `127.0.0.1:8000`.

3. **FFmpeg Streaming Supervisor Script (`apps/radio/stream.sh`)**:
   - Encodes 1280x720 30 fps video at 2500 kbps CBR with 2.0s GOP (`-g 60 -keyint_min 60 -sc_threshold 0`) and x264 HRD filler (`nal-hrd=cbr:force-cfr=1`) to prevent static visual bitrate collapse.
   - Encodes AAC stereo audio at 44.1 kHz, 128 kbps.
   - Loops visual background continuously without boundary restarts (`-stream_loop -1 -re`).
   - Resilient audio reconnect flags (`-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 2`).
   - Disables inherited shell tracing with `set +x`.
   - Validates that `STREAM_KEY` is present and non-whitespace; fails closed before launch if empty.
   - Never automatically sources production `stream.env`; requires caller-supplied environment.
   - In YouTube mode, suppresses raw FFmpeg stderr to prevent stream key leakage in connection diagnostics; captures exit status and emits sanitized error message.

4. **Systemd Streaming Service (`apps/radio/systemd/astrazit-stream.service`)**:
   - Unprivileged execution as `astrazit:astrazit` in `/opt/astrazit-radio`.
   - Dependency chaining (`After=network.target network-online.target astrazit-radio.service`, `Wants=network-online.target astrazit-radio.service`).
   - Standard cgroup termination lifecycle (KillMode defaults to control-group; `KillMode=process` removed).
   - Sandbox hardening (`ProtectSystem=full`, `ProtectHome=true`, `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectProc=invisible`, `ProcSubset=pid`).
   - Runtime secret isolation (`EnvironmentFile=-/opt/astrazit-radio/config/stream.env`, mode `0600`).
   - Auto-restart supervisor (`Restart=always`, `RestartSec=5s`).

5. **Visual Loop Generator (`scripts/linux/generate_visual_loop.sh`)**:
   - Deterministically generates 1280x720 30fps H.264 MP4 loop asset using FFmpeg `lavfi`.
   - Validates dimensions, framerate, and codec with `ffprobe`.

6. **Automated YouTube Stream Verification Protocol (`scripts/linux/verify_youtube_stream.sh`)**:
   - 10-step Stage-A automated validation suite testing toolchains, loop asset conformance, harbor audio output, local multiplexing, boundary frame continuity, reconnect resilience, and secret sanitization.
   - Strictly enforces that optional live broadcast requires both `RUN_LIVE_TEST=1` and `STREAM_KEY` in environment.
   - Reports host-side `/proc` isolation status without modifying host.

7. **Architecture Documentation & Scoped Exclusions**:
   - `docs/architecture/YOUTUBE_VIDEO_STREAM.md` documenting architecture, trust model, and encoding profiles.
   - Scoped `.gitignore` rules for `/apps/radio/assets/generated/`, `/apps/radio/stream.env`, `/apps/radio/runtime/`, and `.local/radio/`.
   - `scripts/linux/setup_radio_node.sh` updated with `hidepid=2` host prerequisite check, drop-in deployment, and explicit operator activation model (installs the publisher unit but never automatically enables or starts it).

8. **Automated Unit & Invariant Tests (`tests/test_radio_youtube_stream.py`)**:
   - Focused RADIO-003 test suite passing cleanly, verifying service units, drop-in compatibility, FFmpeg flags, secret-safe stderr suppression, Stage-A config isolation, explicit activation model, and zero repository stream keys.

---

## Acceptance Status & Boundary Analysis

### Stage-A Automated Verification
- [x] Local/VPS FFmpeg output file validates with ffprobe (H.264 1280x720 @ 30 fps, AAC 44.1 kHz stereo @ 128 kbps) *(verified on VPS in fresh corrected Stage-A retest)*.
- [x] Video plays continuously across visual loop boundaries without interruption (frame continuity verified: 750 frames) *(verified on VPS in fresh corrected Stage-A retest)*.
- [x] Audio from Liquidsoap is present, decoded, and non-silent via Harbor HTTP loopback *(verified on VPS in fresh corrected Stage-A retest)*.
- [x] Basic audio/video presence confirmed in multiplexed stream *(verified on VPS in fresh corrected Stage-A retest)*.
- [x] Transient Harbor audio disconnect/reconnect behavior validated with FFmpeg `-reconnect` flags *(verified on VPS in fresh corrected Stage-A retest)*.
- [x] Secret sanitization: Zero stream keys in repository, shell history, logs, or task docs (`test_zero_stream_keys_in_repo`) *(automated repository test verified)*.
- [x] Stage-A verifier isolation: `stream.sh` never automatically sources production `stream.env` *(automated unit test verified)*.
- [x] FFmpeg secret safety: Raw stderr suppressed in YouTube mode to prevent RTMPS key leakage *(automated unit test verified)*.
- [x] Systemd lifecycle: `astrazit-stream.service` does not use `KillMode=process`, ensuring cgroup termination of wrapper and child processes *(verified on VPS in fresh corrected Stage-A retest)*.
- [x] Activation safety: Node setup script installs unit but never automatically enables `astrazit-stream.service` regardless of `STREAM_KEY` value *(automated unit test verified)*.
- [x] Full regression test suite remains green *(local test suite verified)*.

### Known Remaining External Gates (Stage-B & Production Deployment)
- [x] **Host-side /proc isolation**: Verified and persisted with `hidepid=2` (`hidepid=invisible`) in `/etc/fstab` on Ubuntu 24.04.5 VPS.
- [x] **Stage-A VPS Retest**: Fully executed and passed on Ubuntu 24.04.5 on the byte-identical pre-correction version.
- [x] **Focused Activation-Only Host Validation**: Verified on Ubuntu 24.04.5 LTS using isolated behavioral harness and static analysis (zero auto-enablement across all 8 configurations).
- [x] **YouTube Live Private Ingest (Stage B2 initial test)**: Executed live unlisted broadcast for >18 minutes on Ubuntu 24.04.5 VPS. Audio/video presence, Liquidsoap handoff, and systemd stability passed with zero restarts. Bitrate compliance issue identified (~220–256 Kbps vs 2500 Kbps recommended due to static visual entropy collapse without HRD filler).
- [x] **YouTube Live CBR Compliance Validation (Stage B2 retest)**: Validated on Ubuntu 24.04.5 VPS during controlled live ingest (BITRATE-004). Video picture and audio verified, connection health excellent, ingest bitrate stabilized at ~2.4–2.7 Mbps, previous low-bitrate warning CLEARED, NRestarts=0, and clean cgroup termination confirmed. Bitrate defect RESOLVED.
- [ ] **Long-duration A/V sync**: Measuring drift during extended 30–60 minute live broadcast.
- [ ] **Production systemd lifecycle**: Testing live service start/restart/crash recovery under systemd on the VPS.
