---
name: ffmpeg-streaming
description: Governs FFmpeg audio/video multiplexing, transcoding pipelines, stream overlay rendering, and encoding parameters.
---

# FFmpeg Streaming Skill

## 1. Purpose
This skill provides standards, encoding recipes, filter graph configurations, and reliability practices for FFmpeg audio/video encoding and multiplexing in the AstraZit broadcast architecture.

## 2. Activation Context
Activate this skill when:
- Designing or debugging FFmpeg pipeline commands for live streaming.
- Combining live audio streams from Liquidsoap/Icecast with static or looped background visuals.
- Configuring video overlays (track title, artist, upcoming queue, waveform visuals).
- Tuning audio codecs (AAC, Opus), video codecs (H.264), keyframe intervals, and bitrates.

## 3. Constraints
- **Stream Stability**: Future FFmpeg pipelines must define and test recovery behavior for their selected inputs, outputs, and FFmpeg version. No universal reconnect flag set is established by this foundation; encoding and recovery profiles remain deferred to RADIO tickets.
- **Resource Discipline**: Video encoding must remain lightweight (e.g., `-preset veryfast` or `-tune stillimage`) to prevent CPU starvation on streaming hosts.
- **Strict Format Alignment**: Output formats must adhere strictly to ingest requirements of target distribution platforms (e.g., YouTube Live 1080p/720p H.264 + AAC).

## 4. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [DECISIONS.md - ADR-008](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md)
- TODO: FFmpeg Broadcast Encoding Profiles (`docs/radio/encoding.md` - to be established)
- TODO: Visual Multiplex Pipeline Scripts (to be established)
