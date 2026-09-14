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
- **Stream Stability**: FFmpeg pipelines must use input reconnect flags (`-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 2`) when consuming live audio from Liquidsoap Harbor to survive transient outages.
- **Resource Discipline**: Video encoding must remain lightweight (`-preset veryfast -tune stillimage`) to prevent CPU starvation on 2-core streaming hosts.
- **Strict Format Alignment**: Output formats must adhere strictly to YouTube Live requirements: 1280x720, 30 fps, H.264 High Profile, ~4 Mbps CBR (`-b:v 4000k -minrate 4000k -maxrate 4000k -bufsize 8000k`), 2s GOP (`-g 60 -keyint_min 60 -sc_threshold 0`), AAC stereo 44.1 kHz @ 128 kbps.

## 4. Production Encoding Profile (RADIO-003)
```bash
ffmpeg -re \
  -stream_loop -1 -i /opt/astrazit-radio/assets/visual_loop.mp4 \
  -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 2 \
  -i http://127.0.0.1:8000/radio.wav \
  -map 0:v:0 -map 1:a:0 \
  -c:v libx264 -preset veryfast -tune stillimage \
  -b:v 4000k -minrate 4000k -maxrate 4000k -bufsize 8000k -pix_fmt yuv420p \
  -r 30 -g 60 -keyint_min 60 -sc_threshold 0 \
  -c:a aac -b:a 128k -ar 44100 -ac 2 \
  -f flv rtmps://a.rtmps.youtube.com/live2/$STREAM_KEY
```

## 5. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [DECISIONS.md - ADR-008](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md)
- [YouTube Video Stream Architecture](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/YOUTUBE_VIDEO_STREAM.md)
- [FFmpeg Streaming Supervisor](file:///c:/AI-PROJECTS/astrazit-music-os/apps/radio/stream.sh)
- [Visual Loop Asset Generator](file:///c:/AI-PROJECTS/astrazit-music-os/scripts/linux/generate_visual_loop.sh)
