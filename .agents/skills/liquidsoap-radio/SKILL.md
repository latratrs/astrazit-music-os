---
name: liquidsoap-radio
description: Guides configuration, scripting, rotation logic, and telnet control for the Liquidsoap audio streaming engine.
---

# Liquidsoap Radio Skill

## 1. Purpose
This skill covers the configuration, scripting (`.liq`), queue management, failover handling, and stream scheduling for AstraZit Radio using the Liquidsoap audio engine.

## 2. Activation Context
Activate this skill when:
- Authoring, debugging, or optimizing Liquidsoap script files (`apps/radio/`).
- Implementing crossfading, volume normalization (replaygain), and metadata injection.
- Configuring playlist rotations, jingles/station IDs, and dynamic fallback sources.
- Configuring Linux systemd service daemons for headless 24/7 radio playout.
- Executing decoded audio verification or troubleshooting playout logs.
- Interacting with Liquidsoap telnet/socket interfaces for runtime management.

## 3. Constraints
- **Zero AI in Song-Change Hot Path (ADR-006)**: No external LLM or network-dependent API calls may be executed inside live track-transition or queue-selection callbacks.
- **LF Line Endings**: All `.liq` files must strictly use Linux LF line endings.
- **Failover Guarantee**: The Liquidsoap configuration must always have a reliable, local fallback source (e.g., local emergency ambient loop or sine generator) to prevent dead air.
- **No Production Impact from Windows (ADR-008)**: Production 24/7 radio executes on a dedicated Linux VPS (`/opt/astrazit-radio`) under systemd, not on Windows.
- **Unprivileged Daemon**: The Linux playout daemon must execute under the dedicated system user `astrazit`, never as root.
- **Zero Secrets in Playout Engine**: No YouTube stream keys, cloud credentials, or private API keys belong in Liquidsoap scripts or systemd unit definitions.

## 4. Production Linux Runtime Layout
The standard Linux VPS layout established in RADIO-002:
```
/opt/astrazit-radio/
├── app/
│   └── station.liq             # Playout script
├── music/                      # Track audio library (*.wav, *.mp3, *.flac, *.m4a)
├── state/
│   ├── radio_state.json        # Atomic playback state
│   └── test_playout.wav        # Decoded PCM audio sink (for verification)
├── logs/
│   └── plays.jsonl             # Append-only JSONL play history
└── config/                     # Environment configuration overrides
```

## 5. Systemd Management Commands
- Start: `sudo systemctl start astrazit-radio`
- Stop: `sudo systemctl stop astrazit-radio`
- Restart: `sudo systemctl restart astrazit-radio`
- Status: `sudo systemctl status astrazit-radio`
- Logs: `sudo journalctl -u astrazit-radio -f`
- Plays: `tail -f /opt/astrazit-radio/logs/plays.jsonl`

## 6. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [DECISIONS.md - ADR-002, ADR-006, ADR-008](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md)
- [Liquidsoap Station Script](file:///c:/AI-PROJECTS/astrazit-music-os/apps/radio/station.liq) (Established in RADIO-001, updated in RADIO-002)
- [Systemd Playout Service](file:///c:/AI-PROJECTS/astrazit-music-os/apps/radio/systemd/astrazit-radio.service) (Established in RADIO-002)
- [Linux Radio Runtime Architecture](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/LINUX_RADIO_RUNTIME.md) (Established in RADIO-002)
- [Local Radio Playout Architecture](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/LOCAL_RADIO_PLAYOUT.md) (Established in RADIO-001)
- [Linux Provisioning Script](file:///c:/AI-PROJECTS/astrazit-music-os/scripts/linux/setup_radio_node.sh) (Established in RADIO-002)
- [Audible Playout Verification Script](file:///c:/AI-PROJECTS/astrazit-music-os/scripts/linux/verify_audible_playout.sh) (Established in RADIO-002)
- TODO: Fallback Audio Asset Guide (to be established)
