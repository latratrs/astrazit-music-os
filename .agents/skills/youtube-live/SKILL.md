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
- **Zero Real Stream Keys in Git (GATE-09)**: Stream keys must never be committed to Git or logs. They must be injected via runtime environment variables or permissions-restricted configuration files (`/opt/astrazit-radio/config/stream.env`, mode `0600`).
- **Human Gatekeeping (GATE-02)**: Public stream launches and announcements require human gatekeeping. MVP streaming is strictly private or unlisted.
- **RTMPS Secure Ingest**: Streaming must target secure RTMPS (`rtmps://a.rtmps.youtube.com/live2`) over TLS (port 443).

## 4. Production Architecture & Runbooks (RADIO-003)
- Ingest URL: `rtmps://a.rtmps.youtube.com/live2`
- Stream Key: Loaded at runtime via `$STREAM_KEY`
- Video: H.264 1280x720 30 fps @ 4000 kbps CBR, 2s keyframe interval (g=60)
- Audio: AAC stereo 44.1 kHz @ 128 kbps
- Service Supervisor: `astrazit-stream.service`

## 5. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [AGENTS.md - Gates & Security](file:///c:/AI-PROJECTS/astrazit-music-os/AGENTS.md)
- [YouTube Video Stream Architecture](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/YOUTUBE_VIDEO_STREAM.md)
- [Task RADIO-003](file:///c:/AI-PROJECTS/astrazit-music-os/tasks/RADIO-003.md)
- [YouTube Verification Protocol](file:///c:/AI-PROJECTS/astrazit-music-os/scripts/linux/verify_youtube_stream.sh)
