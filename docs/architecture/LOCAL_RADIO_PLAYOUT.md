# Local AstraZit Radio Playout MVP Architecture

Governed by **RADIO-001**, **ADR-002**, **ADR-006**, and **ADR-008**.

---

## 1. Purpose & Non-Production Status

This document describes the design, execution, and state contracts for the **Local AstraZit Radio Playout MVP** (`apps/radio/`).

- **Non-Production Status**: This implementation is strictly a local development and verification tool. It is designed to validate the foundational playout flow:
  $$\text{TRACK} \longrightarrow \text{PLAY} \longrightarrow \text{TRANSITION} \longrightarrow \text{NEXT TRACK} \longrightarrow \text{LOG}$$
- **Relationship to Music OS**: Governed by ADR-002, AstraZit Radio is an application consumer of the catalog, not an authority. It never mutates canonical catalog files, never generates or allocates AST identifiers, and never clears or changes rights state.
- **Production Host Target**: Governed by ADR-008, the 24/7 production broadcast station will execute on a dedicated Linux VPS with Liquidsoap and systemd daemons, not on the Windows development workstation.

---

## 2. Environment Discovery & Architecture

### Environment Discovery
During initialization of RADIO-001, tool discovery on the local Windows host detected:
- **Operating System**: Windows (PowerShell)
- **Liquidsoap**: Not installed / not available in PATH
- **FFmpeg / ffprobe**: Not installed / not available in PATH
- **WSL**: Windows Subsystem for Linux is not installed on this host
- **Python**: Python 3.14.3 active in `.venv`

In accordance with agent charter guidelines, no uncontrolled global host installations were executed.

### Dual-Architecture Implementation
To bridge local Windows development and the target Linux VPS runtime without architectural compromise:
1. **Local Python Playout Engine (`apps/radio/`)**:
   - Written using Python standard library.
   - Provides deterministic track discovery from any local folder.
   - Implements the control-plane state machine: `TRACK_START`, `TRANSITION` (crossfade timing simulation), `TRACK_END`, and atomic state persistence. It does not decode or emit audible audio on Windows.
   - Writes append-only machine-readable play logs (`plays.jsonl`).
   - Generates harmless synthetic PCM WAV test tones via `scripts/generate_test_tones.py` for verification without requiring external or copyrighted audio.
2. **Canonical Linux VPS Script (`apps/radio/station.liq`)**:
   - Liquidsoap station script formatted strictly with Linux LF line endings.
   - Reads from dynamic playlist directory with mime-type filters.
   - Implements conservative 2.0s crossfade.
   - Configures zero-dead-air emergency sine tone fallback.
   - Implements on-track metadata callbacks appending to `plays.jsonl`.
   - Directs output to `output.dummy` for headless test runs.

---

## 3. Directory & Runtime Contract

All local runtime artifacts and disposable test audio are placed in an ignored directory under `.local/radio/`:

```
.local/radio/
├── music/               <-- Operator-supplied audio tracks or synthetic test tones (*.wav, *.mp3, *.flac, *.m4a)
├── state/
│   └── radio_state.json <-- Atomic JSON snapshot of current playback state
└── logs/
    └── plays.jsonl      <-- Append-only JSONL play history
```

> [!IMPORTANT]
> The `.local/radio/` directory is explicitly excluded by `.gitignore`. No private, copyrighted audio files or runtime state snapshots are ever tracked in version control.

---

## 4. Supported Audio Formats

The local discovery layer (`apps.radio.discovery.PlaylistDiscovery`) explicitly supports:
- `.mp3`
- `.wav`
- `.flac`
- `.m4a`

All unsupported extensions (e.g. `.txt`, `.json`, `.exe`), hidden files (e.g. `.track.wav`), and subdirectories are automatically and safely ignored.

---

## 5. How to Supply Test Audio

Operators can supply their own audio files or generate synthetic test tones using the included generator:

```powershell
# Generate 3 harmless synthetic sine tones (440Hz, 554Hz, 659Hz)
.\.venv\Scripts\python scripts/generate_test_tones.py --output-dir .local/radio/music
```

Alternatively, copy any local test audio files directly into `.local/radio/music/`.

---

## 6. Execution & Control Commands

### Local Playout
```powershell
# Run 3 tracks with 0.5s crossfade and instant simulation (fast smoke test)
.\.venv\Scripts\python -m apps.radio.cli play --music-dir .local/radio/music --max-tracks 3

# Run the timing simulation with real-time track-duration delays (no audio output)
.\.venv\Scripts\python -m apps.radio.cli play --music-dir .local/radio/music --realtime

# Point to an arbitrary external music directory
.\.venv\Scripts\python -m apps.radio.cli play --music-dir "D:\Audio\TestMix"
```

### Stopping Playout
- In real-time simulation mode, send `Ctrl+C` (`SIGINT`) to stop the CLI. The
  control-plane simulation does not guarantee final `TRACK_END` or
  `STATION_STOP` events for an interrupted in-flight sleep; inspect the state
  and append-only log after interruption.

### Inspecting Runtime State
```powershell
.\.venv\Scripts\python -m apps.radio.cli status
```

### Viewing Play History
```powershell
.\.venv\Scripts\python -m apps.radio.cli history --limit 10
```

---

## 7. Machine-Readable State & Log Formats

### State Snapshot (`.local/radio/state/radio_state.json`)
Atomically updated via `os.replace` to prevent partial reads:
```json
{
  "status": "STOPPED",
  "current_track": "track_c_synth_659hz.wav",
  "current_track_path": "C:\\AI-PROJECTS\\astrazit-music-os\\.local\\radio\\music\\track_c_synth_659hz.wav",
  "previous_track": "track_b_synth_554hz.wav",
  "sequence_count": 3,
  "last_transition_time": "2026-09-10T09:57:03.861163+00:00",
  "updated_at": "2026-09-10T09:57:04.212746+00:00"
}
```

### Play Log (`.local/radio/logs/plays.jsonl`)
Append-only log recording event progression:
```json
{"timestamp": "2026-09-10T09:57:03.446979+00:00", "event": "TRACK_START", "sequence_number": 1, "track_name": "track_a_synth_440hz.wav", "track_path": "...", "duration_seconds": 1.0, "transition_seconds": null}
{"timestamp": "2026-09-10T09:57:03.546047+00:00", "event": "TRANSITION", "sequence_number": 1, "track_name": "track_a_synth_440hz.wav", "track_path": "...", "duration_seconds": null, "transition_seconds": 0.5}
{"timestamp": "2026-09-10T09:57:03.668978+00:00", "event": "TRACK_END", "sequence_number": 1, "track_name": "track_a_synth_440hz.wav", "track_path": "...", "duration_seconds": 1.0, "transition_seconds": null}
```

---

## 8. Known Limitations & Next Steps

- **No Public Streaming / RTMP**: RADIO-001 does not include YouTube Live ingestion, stream keys, or FFmpeg video multiplexing.
- **No Rights Enforcement in Playout Yet**: Local playout plays operator-supplied files without validating catalog broadcast eligibility. Connecting playout to the canonical catalog is scheduled for future RADIO tickets.
- **Next Ticket (RADIO-002)**: Establish the Linux VPS runtime configuration, systemd service descriptors, Icecast/dummy outputs, and containerized/VPS Liquidsoap verification.
