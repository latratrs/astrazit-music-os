---
name: youtube-live
description: Manages YouTube Live streaming configuration, RTMP ingest, stream health monitoring, broadcast metadata, and API interactions.
---

# YouTube Live Skill

## 1. Purpose
This skill governs the integration with YouTube Live streaming services, including RTMP endpoint configuration, stream health monitoring, live broadcast metadata, chat bot interactions, and broadcast event handling.

## 2. Activation Context
Activate this skill when:
- Setting up or troubleshooting YouTube RTMP/RTMPS broadcast ingest.
- Managing YouTube Live API tokens, broadcast lifecycles, and stream statuses.
- Updating live stream titles, descriptions, tags, and category metadata from Music OS.
- Designing chat interactions or "now playing" comment/chat automations.

## 3. Constraints
- **Zero Real Stream Keys in Git**: Stream keys must never be committed to Git. They must be injected via environment variables or secret managers.
- **Human Gatekeeping (GATE-02 & GATE-09)**: Modifying live public stream settings or publishing public announcements requires human confirmation.
- **Quota Management**: YouTube Data API v3 quotas must be respected with aggressive caching for track info and status checks.

## 4. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [AGENTS.md - Gates & Security](file:///c:/AI-PROJECTS/astrazit-music-os/AGENTS.md)
- TODO: YouTube Live Ingest & Metadata Specifications (`docs/radio/youtube-live.md` - to be established)
- TODO: Broadcast Health Monitor Runbook (to be established)
