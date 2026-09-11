# Linux VPS Radio Playout Runtime Architecture

Governed by **RADIO-002**, **ADR-002**, **ADR-006**, and **ADR-008**.

---

## 1. Purpose & Production Host Boundary

This document defines the canonical architecture, filesystem layout, service configuration, and verification protocol for the **AstraZit Radio Linux VPS Playout Runtime**.

The Linux runtime has been validated on the provisioned Ubuntu 24.04.5 VPS.
Liquidsoap 2.2.4, FFmpeg/ffprobe 6.1.1, decoded PCM audio output, deterministic
A -> B -> C synthetic-track sequencing, crossfades, structured runtime logging,
systemd restart behavior, deliberate crash recovery, and clean service shutdown
were verified during RADIO-002 acceptance testing.

- **Production Target (ADR-008)**: Live, 24/7 radio playout executes on a dedicated Linux VPS (Virtual Private Server). The local Windows development workstation is strictly an authoring, testing, and control environment; it does not host the live broadcast.
- **Audible Playout Engine**: Audio scheduling, playlist rotation, crossfading, fallback recovery, and decoding are powered by **Liquidsoap** and validated with **FFmpeg / ffprobe**.
- **Zero AI in Song-Change Hot Path (ADR-006)**: Track selection, rotation, and transitions are strictly local, deterministic, and offline-capable. No LLM, Gemini API, or external network call may be placed in the transition callback path.
- **Autonomous Recovery (ADR-008)**: Playout is managed as a hardened systemd daemon with automatic restart on crash or failure (`Restart=always`, `RestartSec=5s`).
- **Scope Restriction**: RADIO-002 establishes the headless audio decoding and playout engine on Linux. It does not configure YouTube Live, does not use stream keys, does not stream over RTMPS, and does not render video (video multiplexing is deferred to RADIO-003).

---

## 2. Target Platform & Toolchain

The production runtime is designed for modern, stable, distro-friendly Linux environments without requiring heavy container engines or orchestration.

| Component | Target Baseline | Notes |
| :--- | :--- | :--- |
| **Operating System** | Ubuntu 22.04 / 24.04 LTS or Debian 12 (*bookworm*) | Standard minimal server installation |
| **Audio Engine** | Liquidsoap 2.1.x / 2.2.x / 2.3.x | Installed via apt or official OPAM/Debian packages |
| **Media Toolkit** | FFmpeg & ffprobe 4.4+ / 5.x / 6.x / 7.x | Provides audio format decoding and stream analysis |
| **Process Supervisor** | systemd | Native init daemon and process supervisor |
| **Runtime Language** | Python 3.10+ | Standard library utilities (tone generation, verification) |
| **Remote Access** | OpenSSH | Key-based authentication only; no passwords |

---

## 3. Runtime Directory Layout

All application code, audio assets, state snapshots, and playout logs reside under `/opt/astrazit-radio/`:

```
/opt/astrazit-radio/
├── app/
│   └── station.liq             # Canonical Liquidsoap playout script
├── music/                      # Track audio repository (*.mp3, *.wav, *.flac, *.m4a)
├── state/
│   ├── radio_state.json        # Atomic playback state snapshot
│   └── test_playout.wav        # Decoded PCM audio capture (test verification sink)
├── logs/
│   └── plays.jsonl             # Append-only machine-readable play history
└── config/                     # Environment configuration overrides (optional)
```

### Security & Permission Standards
- **Dedicated User**: Owned by system user `astrazit:astrazit`.
- **Restricted Access**: Directory permissions set to `0750` (`rwxr-x---`). No world-readable or broad `777` permissions.
- **Secrets Absence**: No API keys, cloud credentials, or stream tokens exist on this host or in this path.

---

## 4. Systemd Service Definition

The playout daemon is registered as `/etc/systemd/system/astrazit-radio.service`:

```ini
[Unit]
Description=AstraZit Music OS Radio Playout Daemon
After=network.target sound.target
Documentation=https://github.com/astrazit/astrazit-music-os

[Service]
Type=simple
User=astrazit
Group=astrazit
WorkingDirectory=/opt/astrazit-radio
Environment="RADIO_MUSIC_DIR=/opt/astrazit-radio/music" "RADIO_LOG_FILE=/opt/astrazit-radio/logs/plays.jsonl" "RADIO_STATE_FILE=/opt/astrazit-radio/state/radio_state.json" "RADIO_OUTPUT_MODE=dummy"
ExecStart=/usr/bin/liquidsoap /opt/astrazit-radio/app/station.liq
Restart=always
RestartSec=5s
KillMode=process
StandardOutput=journal
StandardError=journal

# Security Hardening
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

---

## 5. Installation & Provisioning

### Automated Setup
A turnkey provisioning script is provided in `scripts/linux/setup_radio_node.sh`:

```bash
# On the Linux VPS as root:
sudo bash scripts/linux/setup_radio_node.sh
```

### Manual Step-by-Step Setup
If deploying manually on Debian or Ubuntu:

```bash
# 1. Update and install packages
sudo apt-get update
sudo apt-get install -y liquidsoap ffmpeg python3 rsync curl

# 2. Create unprivileged system user
sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin astrazit

# 3. Create directory tree
sudo mkdir -p /opt/astrazit-radio/{app,music,state,logs,config}

# 4. Copy station script and set permissions
sudo cp apps/radio/station.liq /opt/astrazit-radio/app/station.liq
sudo chown -R astrazit:astrazit /opt/astrazit-radio
sudo chmod 750 /opt/astrazit-radio
sudo chmod 750 /opt/astrazit-radio/*

# 5. Install systemd service
sudo cp apps/radio/systemd/astrazit-radio.service /etc/systemd/system/astrazit-radio.service
sudo chmod 644 /etc/systemd/system/astrazit-radio.service
sudo systemctl daemon-reload
sudo systemctl enable astrazit-radio.service
```

---

## 6. Remote Deployment & Synchronization

From the development workstation, code and assets can be synchronized securely via `rsync`:

```bash
# Sync station script to Linux VPS
rsync -avz -e ssh apps/radio/station.liq deploy-user@vps-ip:/opt/astrazit-radio/app/

# Sync audio tracks (or synthetic test tones) to music repository
rsync -avz -e ssh /path/to/tracks/ deploy-user@vps-ip:/opt/astrazit-radio/music/

# Restart daemon to pick up configuration changes
ssh deploy-user@vps-ip "sudo systemctl restart astrazit-radio"
```

---

## 7. Service Management & Monitoring

### Standard Service Controls
```bash
# Start playout daemon
sudo systemctl start astrazit-radio

# Check daemon status and active PID
sudo systemctl status astrazit-radio

# Restart daemon
sudo systemctl restart astrazit-radio

# Stop daemon
sudo systemctl stop astrazit-radio
```

### Log Inspection
```bash
# View live supervisor logs via journalctl
sudo journalctl -u astrazit-radio -f

# View append-only JSONL play history
tail -f /opt/astrazit-radio/logs/plays.jsonl
```

Sample `plays.jsonl` output:
```json
{"timestamp":"1773187200.12","event":"STATION_START"}
{"timestamp":"1773187200.15","event":"TRACK_START","track_name":"/opt/astrazit-radio/music/track_a_synth_440hz.wav"}
{"timestamp":"1773187204.05","event":"TRACK_START","track_name":"/opt/astrazit-radio/music/track_b_synth_554hz.wav"}
{"timestamp":"1773187208.00","event":"TRACK_START","track_name":"/opt/astrazit-radio/music/track_c_synth_659hz.wav"}
{"timestamp":"1773187212.00","event":"STATION_STOP"}
```

---

## 8. Verification Protocol: Actual Decoded Audio Playout

To verify that the Linux runtime decodes real audio rather than running a timing simulation, execute the automated verification script:

```bash
sudo bash scripts/linux/verify_audible_playout.sh
```

### Verification Flow
1. **Toolchain Inspection**: Verifies `liquidsoap`, `ffmpeg`, `ffprobe`, kernel version, and OS release.
2. **Tone Generation**: Generates 3 synthetic WAV tones (Track A 440Hz, Track B 554.37Hz, Track C 659.25Hz).
3. **Syntax Validation**: Executes `liquidsoap --check /opt/astrazit-radio/app/station.liq`.
4. **Decoded Playout Execution**: Runs Liquidsoap with `RADIO_OUTPUT_MODE=file` targeting `/opt/astrazit-radio/state/audible_playout_test.wav`.
5. **ffprobe Audio Stream Analysis**: Inspects the generated file to confirm real PCM 16-bit stereo decoding at 44.1 kHz, non-zero audio frame decode, and expected multi-track playout duration.
6. **Log Event Verification**: Checks `plays.jsonl` for `STATION_START` and consecutive `TRACK_START` events.
7. **Crash Recovery Test**: Starts service under systemd, sends `kill -9` to the MainPID, and validates that systemd revives the process within 5 seconds with a new PID.

---

## 9. Security & Access Posture

- **No Inbound Web Ports**: The VPS has zero HTTP/HTTPS listening ports. Only OpenSSH on port 22 (or a custom SSH port) is open.
- **Unprivileged Daemon**: The Liquidsoap process runs strictly as `astrazit`, preventing filesystem escalation.
- **Hardened Systemd Directives**:
  - `NoNewPrivileges=true`: Disallows setuid elevation.
  - `ProtectSystem=full`: Mounts `/usr`, `/boot`, and `/etc` read-only for the process.
  - `ProtectHome=true`: Completely isolates `/home` and `/root`.
  - `PrivateTmp=true`: Isolates `/tmp` inside a private filesystem namespace.
- **Zero Secrets**: No YouTube keys or cloud credentials reside on this machine.

---

## 10. Known Limitations & Next Steps

- **Audio-Only Playout**: RADIO-002 establishes reliable headless audio decoding and transitions. It does not yet generate a video canvas or broadcast stream.
- **Next Ticket (`RADIO-003`)**: Implement FFmpeg visual background generation, real-time audio-video multiplexing, and RTMP/HLS encoding pipeline.
