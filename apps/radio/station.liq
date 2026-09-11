# AstraZit Radio - Production Liquidsoap Station Playout Template
# Governed by RADIO-001, ADR-002, ADR-006, and ADR-008.
#
# Production Runtime: Linux / Dedicated VPS
# Enforces:
# - Zero AI calls in track transition hot path
# - Deterministic local rotation from music directory
# - Fallback emergency tone to prevent dead air
# - Conservative crossfade transition
# - Machine-readable play logging

# Settings
settings.server.telnet := false
settings.log.level := 3

# Directory Configuration
music_dir = environment.get(default="/var/astrazit/radio/music", "RADIO_MUSIC_DIR")
log_file = environment.get(default="/var/astrazit/radio/logs/plays.jsonl", "RADIO_LOG_FILE")

# Emergency Fallback Tone (440Hz sine wave)
fallback_source = sine(440.0)

# Local Audio Playlist Discovery
# Discovers .mp3, .wav, .flac, .m4a
playlist_source = playlist(
  reload_mode="watch",
  mime_types=[
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/mp4"
  ],
  music_dir
)

# Crossfade Configuration (conservative 2.0s transition)
radio = crossfade(duration=2.0, playlist_source)

# Fallback Safety (Zero Dead Air)
station = fallback(track_sensitive=false, [radio, fallback_source])

# Track Transition Logger (JSONL append)
def log_track(m) =
  title = m["title"]
  artist = m["artist"]
  filename = m["filename"]
  log_entry = '{"timestamp":"' ^ string_of(time()) ^ '","event":"TRACK_START","track_name":"' ^ filename ^ '"}\n'
  file.write(data=log_entry, append=true, log_file)
end

station.on_track(log_track)

# Output: Local Test Audio or Icecast / Pipe
# For headless VPS / testing: output.dummy
output.dummy(station)