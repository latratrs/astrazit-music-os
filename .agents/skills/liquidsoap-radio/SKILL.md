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
- Interacting with Liquidsoap telnet/socket interfaces for runtime management.

## 3. Constraints
- **Zero AI in Song-Change Hot Path (ADR-006)**: No external LLM or network-dependent API calls may be executed inside live track-transition or queue-selection callbacks.
- **LF Line Endings**: All `.liq` files must strictly use Linux LF line endings.
- **Failover Guarantee**: The Liquidsoap configuration must always have a reliable, local fallback source (e.g., local emergency ambient loop) to prevent dead air.
- **No Production Impact from Windows**: Production runs on Linux; local Windows testing must not assume Linux daemon behaviors.

## 4. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [DECISIONS.md - ADR-002, ADR-006, ADR-008](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md)
- TODO: Liquidsoap Station Script (`apps/radio/station.liq` - to be established in RADIO tickets)
- TODO: Fallback Audio Asset Guide (to be established)
