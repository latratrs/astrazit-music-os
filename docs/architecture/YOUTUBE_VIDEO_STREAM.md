# YouTube Video Stream Architecture

Governed by **RADIO-003**, **ADR-002**, **ADR-006**, and **ADR-008**.

---

## 1. Purpose & Production Host Boundary

This document defines the canonical architecture, audio/video multiplexing pipeline, encoding parameters, systemd service configuration, and verification protocol for the **AstraZit Radio YouTube Video Streaming Runtime**.

- **Production Target (ADR-008)**: 24/7 video streaming executes on the dedicated Linux VPS host (`/opt/astrazit-radio/`) under systemd supervision. The Windows development PC is strictly an authoring, testing, and control environment; it does not host the broadcast.
- **Continuous Visual Playout**: A seamless, branded 1280x720 30 fps motion video loop (`visual_loop.mp4`) runs continuously without boundary disruption using FFmpeg `-stream_loop -1`.
- **Live Radio Audio Handoff**: Decoupled local loopback via Liquidsoap Harbor HTTP streaming (`http://127.0.0.1:8000/radio.wav`), allowing independent process restarts and zero dead-air fallback.
- **Strict Ingest Alignment**: Stream parameters strictly comply with YouTube Live ingest requirements (H.264 CBR @ ~4 Mbps, 2.0s keyframe interval, AAC stereo 44.1 kHz @ 128 kbps).
- **Zero Secrets in Repository (GATE-09)**: The YouTube stream key is supplied strictly at runtime via environment variables or an uncommitted permissions-restricted file (`/opt/astrazit-radio/config/stream.env`, mode `0600`).
- **Private/Unlisted Gating (GATE-02)**: MVP testing is confined to unlisted or private YouTube Live events. No public broadcast launch occurs in this ticket.
- **Process-Inspection Security Model**:
  - `ProtectProc=invisible` and `ProcSubset=pid` in `astrazit-stream.service` are defense-in-depth for the service's own process view. They do NOT prevent unrelated host users from inspecting the service process through the host `/proc`.
  - The production VPS must have an effective host-side `/proc` restriction such as `hidepid=2` (or `hidepid=invisible`) before the YouTube publisher service is installed and enabled.
  - **Trust Boundaries**:
    - **TRUSTED**: `root`, dedicated `astrazit` service account, FFmpeg process running as `astrazit`.
    - **NOT TRUSTED**: Unrelated local Linux users, repository readers, ordinary unprivileged log readers.
    - **Accepted Limitation**: Root and `astrazit` (same-user) process inspection may see argv/memory containing the destination URL or key.

---

## 2. Architecture & Pipeline Topology

```
+-----------------------------------------------------------------------------------------+
|                                    LINUX VPS NODE                                       |
|                                                                                         |
|  +--------------------------------+                                                     |
|  |       Liquidsoap Playout       |                                                     |
|  |     (astrazit-radio.service)   |                                                     |
|  |   + 20-harbor.conf drop-in     |                                                     |
|  |                                |                                                     |
|  |  - Playlist rotation           |                                                     |
|  |  - 2.0s crossfades             |                                                     |
|  |  - 440Hz emergency fallback    |                                                     |
|  |  - plays.jsonl audit logs      |                                                     |
|  +---------------+----------------+                                                     |
|                  |                                                                      |
|                  | Local Loopback PCM / WAV Stream                                      |
|                  v http://127.0.0.1:8000/radio.wav                                      |
|  +--------------------------------+       +------------------------------------------+  |
|  |        FFmpeg Encoder          | <==== | /opt/astrazit-radio/assets/              |  |
|  |     (astrazit-stream.service)  |       | visual_loop.mp4 (1280x720 @ 30fps)       |  |
|  |                                |       +------------------------------------------+  |
|  |  - Video: H.264 4Mbps CBR      |                                                     |
|  |  - GOP: 60 frames (2.0s)       |       +------------------------------------------+  |
|  |  - Audio: AAC 128k @ 44.1kHz   | <.... | /opt/astrazit-radio/config/stream.env    |  |
|  |  - FLV container over RTMPS    |       | (STREAM_KEY, mode 0600, untracked)       |  |
|  +---------------+----------------+       +------------------------------------------+  |
|                  |                                                                      |
+------------------+----------------------------------------------------------------------+
                   |
                   | RTMPS Ingest (Port 443)
                   v
     +-----------------------------------------+
     | YouTube Live (Private / Unlisted Event) |
     | rtmps://a.rtmps.youtube.com/live2/      |
     +-----------------------------------------+
```

---

## 3. Encoding & Multiplexing Specifications

The streaming pipeline executes via `apps/radio/stream.sh` using the following exact parameters:

| Component | Target Baseline | FFmpeg Argument | Rationale |
| :--- | :--- | :--- | :--- |
| **Video Resolution** | 1280x720 (720p HD) | `1280x720` | YouTube Live standard 720p 16:9 canvas |
| **Framerate** | 30.00 fps constant | `-r 30` | Smooth motion with lightweight VPS CPU load |
| **Video Codec** | H.264 / AVC (High Profile) | `-c:v libx264 -pix_fmt yuv420p` | Universal YouTube Live ingest compatibility |
| **Video Bitrate** | 2500 kbps constant (~2.5 Mbps) | `-b:v 2500k -minrate 2500k -maxrate 2500k -bufsize 5000k -x264-params "nal-hrd=cbr:force-cfr=1"` | CBR enforcement with HRD filler to prevent static visual bitrate collapse |
| **Keyframe Interval**| Exactly 2.0 seconds (60 frames) | `-g 60 -keyint_min 60 -sc_threshold 0` | YouTube Live requirement for chunk alignment |
| **Audio Codec** | AAC-LC | `-c:a aac` | Clean audio encoding for broadcast |
| **Audio Bitrate** | 128 kbps CBR | `-b:a 128k` | CD-quality speech and synthwave delivery |
| **Sample Rate** | 44.1 kHz (44,100 Hz) | `-ar 44100` | Aligns directly with Liquidsoap master audio |
| **Channels** | Stereo (2.0) | `-ac 2` | Full stereo field preservation |
| **Container Format** | FLV over TLS | `-f flv` | Required for RTMP/RTMPS broadcast ingest |
| **Visual Looping** | Infinite seamless loop | `-stream_loop -1 -re -i ...` | Paced looping without file restarts |
| **Audio Reconnect** | 2-second max retry | `-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 2` | Survives Liquidsoap service restarts |

---

## 4. Runtime Directory Layout & Scoped Exclusions

Assets and configuration on the Linux VPS reside under `/opt/astrazit-radio/`:

```
/opt/astrazit-radio/
├── app/
│   ├── station.liq             # Playout script (with harbor audio sink)
│   └── stream.sh               # FFmpeg multiplexer & RTMPS streaming supervisor
├── assets/
│   └── visual_loop.mp4         # 1280x720 30fps seamless motion loop (YUV420p)
├── music/                      # Canonical audio library (*.wav, *.mp3, *.flac)
├── state/
│   ├── radio_state.json        # Atomic playback state snapshot
│   └── test_stream.flv         # Local test output capture (for verification)
├── logs/
│   └── plays.jsonl             # Append-only structured play history
└── config/
    └── stream.env              # Runtime secret configuration (mode 0600)
```

### Git Scoped Exclusions
Rather than broad repository-wide glob exclusions, the repository maintains narrowly scoped exclusions in `.gitignore`:
- `/apps/radio/assets/generated/`
- `/apps/radio/stream.env`
- `/apps/radio/runtime/`
- `.local/radio/`

---

## 5. Systemd Service Hierarchy & Drop-in Integration

### Playout Daemon (`astrazit-radio.service`)
- Base unit defined at `apps/radio/systemd/astrazit-radio.service` preserves the headless `dummy` output mode established in RADIO-002:
  `Environment="... RADIO_OUTPUT_MODE=dummy"`
- Production streaming override is deployed via drop-in:
  `apps/radio/systemd/astrazit-radio.service.d/20-harbor.conf`:
  ```ini
  [Service]
  # RADIO-003: Override production playout to Harbor HTTP loopback for FFmpeg video streaming
  Environment="RADIO_OUTPUT_MODE=harbor" "RADIO_HARBOR_PORT=8000" "RADIO_HARBOR_MOUNT=radio.wav"
  ```
  This cleanly decouples the base radio capability from the streaming layer without code duplication.

### Streaming Daemon (`astrazit-stream.service`)
- Registered at `/etc/systemd/system/astrazit-stream.service`.
- Relationship to playout daemon:
  ```ini
  [Unit]
  Description=AstraZit Music OS Radio YouTube Video Stream Supervisor
  StartLimitIntervalSec=300
  StartLimitBurst=5
  After=network.target network-online.target astrazit-radio.service
  Wants=network-online.target astrazit-radio.service
  Documentation=https://github.com/astrazit/astrazit-music-os

  [Service]
  Type=simple
  User=astrazit
  Group=astrazit
  WorkingDirectory=/opt/astrazit-radio
  Environment="STREAM_INPUT_VIDEO=/opt/astrazit-radio/assets/visual_loop.mp4" "STREAM_INPUT_AUDIO=http://127.0.0.1:8000/radio.wav" "STREAM_OUTPUT_MODE=youtube"
  EnvironmentFile=-/opt/astrazit-radio/config/stream.env
  ExecStart=/usr/bin/bash /opt/astrazit-radio/app/stream.sh
  Restart=always
  RestartSec=5s
  StandardOutput=journal
  StandardError=journal

  # Security Hardening (service internal isolation)
  NoNewPrivileges=true
  ProtectSystem=full
  ProtectHome=true
  PrivateTmp=true
  ProtectProc=invisible
  ProcSubset=pid
  RestrictSUIDSGID=true
  LockPersonality=true
  RestrictNamespaces=true

  [Install]
  WantedBy=multi-user.target
  ```

---

## 6. Secret Isolation & Security Posture

1. **Zero Keys in Git**: No production stream key is stored in the repository.
2. **Restricted File Mode**: The configuration file `/opt/astrazit-radio/config/stream.env` is a restricted runtime secret file created with mode `0600` and owned by `astrazit:astrazit`. Setup provisions this file only if it does not already exist, and never overwrites an existing configuration.
3. **No Automatic Sourcing**: `stream.sh` does NOT automatically source `stream.env`. In production, systemd loads the environment via `EnvironmentFile=-/opt/astrazit-radio/config/stream.env`. In manual/verification execution, environment variables must be passed explicitly, ensuring Stage-A local testing cannot be overridden into YouTube mode.
4. **Explicit Operator Activation**: The node setup script installs the publisher unit but never automatically enables or starts `astrazit-stream.service`. Activation is an explicit operator action after reviewing configuration and installing a valid stream key.
5. **FFmpeg Secret-Safe Error Handling**: In YouTube mode, raw FFmpeg stderr is suppressed from the journal and console to prevent `Failed to open rtmps://.../<key>` diagnostics from leaking credentials. FFmpeg's exit status is captured and reported via sanitized message `ERROR: FFmpeg publisher exited with status <n>.` File mode retains standard diagnostics.
6. **Shell Tracing Safeguard**: `set +x` is enforced before secret/config handling in all shell scripts.
7. **Host Process Isolation Prerequisite**: Node provisioning inspects `/proc` mount options for `hidepid=2` or `hidepid=invisible`. Setup fails closed before installing the stream service if host-side protection is missing.

---

## 7. Service Management Commands

```bash
# Start Playout and Streaming Daemons
sudo systemctl start astrazit-radio
sudo systemctl start astrazit-stream

# Inspect Status
sudo systemctl status astrazit-radio
sudo systemctl status astrazit-stream

# Live Supervisor Logs
sudo journalctl -u astrazit-stream -f

# Restart Daemons
sudo systemctl restart astrazit-stream
sudo systemctl restart astrazit-radio

# Stop Streaming
sudo systemctl stop astrazit-stream
```

---

## 8. Verification & Acceptance Protocol

To execute the automated Stage-A verification test on the Linux VPS:

```bash
sudo bash scripts/linux/verify_youtube_stream.sh
```

### Scope of Verification:
- **AUTOMATED (Stage-A Offline Protocol)**:
  - Toolchain presence (`ffmpeg`, `ffprobe`, `liquidsoap`).
  - Visual loop asset generation and conformance (1280x720, 30fps, H.264).
  - Liquidsoap Harbor HTTP audio streaming (`127.0.0.1:8000/radio.wav`).
  - Local FFmpeg multiplexing and ffprobe stream verification.
  - Video frame continuity across visual loop boundaries.
  - Non-silent audio and basic audio/video presence.
  - Resilient reconnect during transient Liquidsoap outage.
  - Secret sanitization audit across disposable workspaces.
  - Static systemd unit inspection and host `/proc` isolation prerequisite detection.

- **NOT YET AUTOMATED / DEFERRED (Stage-B & Beyond)**:
  - Measured long-duration A/V drift analysis.
  - Production 24h / 72h continuous broadcast soak.
  - Actual YouTube private/unlisted live ingest (requires `RUN_LIVE_TEST=1` and `STREAM_KEY`).
  - Production systemd lifecycle testing on the live host.

---

## 9. RADIO-004 Pre-24/7 Operational Hardening Decisions

### A. Radio Dependency
- Retain `Wants=network-online.target astrazit-radio.service` and `After=network.target network-online.target astrazit-radio.service`.
- `Requires=` and `BindsTo=` were intentionally rejected: brief Harbor or playout interruptions should not automatically tear down the publisher and drop the YouTube live session.
- Persistent startup or runtime failures are bounded by systemd start-rate limiting (`StartLimitIntervalSec=300`, `StartLimitBurst=5`), ensuring the unit eventually enters a failed state rather than restarting indefinitely.

### B. Harbor Binding
- The authoritative loopback control for Harbor is:
  ```ocaml
  settings.harbor.bind_addrs := ["127.0.0.1"]
  ```
- Playout daemon verification previously proved loopback-only binding; no unsupported per-output bind arguments (`host=`) are added to `output.harbor(...)`.

### C. RTMPS Timeout
- Status: **VERIFIED AND IMPLEMENTED**
- FFmpeg 6.1.1 target binary on the Linux VPS exposes `rw_timeout` (`Timeout for IO operations (in microseconds)`).
- A loopback-only RTMPS parsing test against a closed local port accepted `-rw_timeout 15000000` (15 seconds) and proceeded to network connection initialization without option errors.
- Negative control test verified that unsupported options are correctly rejected.
- The 15-second network timeout (`-rw_timeout 15000000`) is applied strictly to YouTube RTMPS output mode; local file mode remains unaffected.
- Zero external RTMP/RTMPS connections were made during capability validation.
