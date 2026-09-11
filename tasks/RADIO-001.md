# Task RADIO-001: Local AstraZit Radio Playout MVP

## Summary
Establish the smallest reliable local development playout MVP for **AstraZit Radio**, proving the end-to-end operational cycle:
$$\text{TRACK} \longrightarrow \text{PLAY} \longrightarrow \text{TRANSITION} \longrightarrow \text{NEXT TRACK} \longrightarrow \text{LOG}$$
without Google Cloud, without YouTube, without external LLM/API calls, and without mutating canonical Music OS catalog state.

## Metadata
- **Ticket ID**: `RADIO-001`
- **Status**: `COMPLETED`
- **Assignee**: `Antigravity Agent`
- **Component**: `apps/radio`
- **Parent Ticket / Milestone**: `Phase 0 / Application #1 (Radio Foundation)`
- **Target Completion**: `2026-09-10`

---

## Deliverables

1. **Playout Runtime Core (`apps/radio/`)**:
   - `apps/radio/config.py`: Configuration and path boundaries (`.local/radio/music`, `state`, `logs`), supported extension filtering (`.mp3`, `.wav`, `.flac`, `.m4a`), safe directory containment.
   - `apps/radio/discovery.py`: Deterministic discovery of supported audio formats, exclusion of unsupported/hidden files, deterministic alphabetical sorting.
   - `apps/radio/state.py`: Machine-readable append-only JSONL play history logging (`plays.jsonl`) and atomic runtime state snapshots (`radio_state.json`).
   - `apps/radio/player.py`: Playout loop orchestrating track start, transition, track end, and state transitions.
   - `apps/radio/cli.py`: Command-line interface with `play`, `status`, and `history` subcommands.
   - `apps/radio/station.liq`: Canonical Liquidsoap station script template with Linux LF line endings and emergency fallback tone.

2. **Synthetic Audio Utility (`scripts/generate_test_tones.py`)**:
   - Standard library utility generating harmless synthetic WAV sine tones (440Hz, 554Hz, 659Hz) for deterministic smoke testing without private or copyrighted audio.

3. **Documentation & Skill Updates**:
   - `docs/architecture/LOCAL_RADIO_PLAYOUT.md`: Full architecture, directory layout, commands, and limitations documentation.
   - `.agents/skills/liquidsoap-radio/SKILL.md`: Updated authoritative references to `apps/radio/station.liq`.

4. **Test Suite (`tests/test_radio_local_playout.py`)**:
   - 14 automated unit and integration tests covering path discovery, file exclusion, deterministic ordering, state persistence, play history logging, sequence simulation, and architectural invariants.

---

## Acceptance Criteria
- [x] Pre-flight Git checks passed (branch `feat/RADIO-001-local-playout-mvp`, base `dac2be2`, clean working tree).
- [x] Environment discovery documented (Windows development workstation, no native Liquidsoap/FFmpeg, Linux VPS intended production).
- [x] Local runtime directory contract defined under `.local/radio/` and ignored by `.gitignore`.
- [x] Zero catalog mutations, zero AST ID allocations, zero rights clearance claims.
- [x] Supported audio extensions explicit: `.mp3`, `.wav`, `.flac`, `.m4a`.
- [x] Append-oriented machine-readable play evidence written to `plays.jsonl`.
- [x] Atomic runtime state persistence written to `radio_state.json`.
- [x] 14 unit and integration tests pass cleanly.
- [x] Full existing regression suite (147 tests) passes with 0 failures.
- [x] `git diff --check` and `git diff dac2be2 -- packages/schemas` completely clean.
- [x] Manual acceptance 3-track control-plane simulation executed and verified (native audio playback was unavailable on the Windows host).
