---
name: radio-qa
description: Defines quality assurance, audio stream verification, stream monitoring, silence detection, and broadcast validation tests.
---

# Radio QA Skill

## 1. Purpose
This skill defines quality assurance standards, validation scripts, stream monitoring methodologies, and testing procedures for AstraZit Radio and catalog audio feeds.

## 2. Activation Context
Activate this skill when:
- Designing test suites or synthetic listeners for the radio stream (`tests/`).
- Verifying audio stream health (silence detection, clipping, bitrate drops, clipping distortion).
- Validating metadata synchronization between Icecast/Liquidsoap and video stream overlays.
- Executing stress tests or failover simulations (e.g., primary source disconnect, fallback switch).

## 3. Constraints
- **Automated Verification**: Broadcast health checks must be non-intrusive and run without disrupting ongoing production broadcasts.
- **Silence Thresholds**: Measurement units, amplitude thresholds, and alarm durations must be defined and validated in a future RADIO ticket; no numeric thresholds are approved by this foundation.
- **Metadata Latency**: Overlay synchronization tolerances and their measurement method must be defined and validated in a future RADIO ticket; no numeric tolerance is approved by this foundation.

## 4. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [DECISIONS.md - ADR-002 & ADR-006](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md)
- TODO: Synthetic Listener Test Harness (`tests/radio/` - to be established)
- TODO: Audio Quality & Loudness Compliance Standards (EBU R128 / LUFS targets - to be established)
