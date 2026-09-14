# AstraZit Radio - Production Liquidsoap Station Playout Template
# Governed by RADIO-001, RADIO-002, ADR-002, ADR-006, and ADR-008.
#
# Production Runtime: Linux / Dedicated VPS (/opt/astrazit-radio)
# Enforces:
# - Zero AI calls in track transition hot path
# - Deterministic local rotation from music directory
# - Fallback emergency tone to prevent dead air
# - Conservative crossfade transition
# - Machine-readable play logging (STATION_START, TRACK_START, STATION_STOP)
# - Verifiable audio decoding sinks (output.dummy or output.file %wav)

# Settings
settings.server.telnet := false
settings.log.level := 3
# Harbor is an internal FFmpeg handoff; never expose it beyond loopback.
settings.harbor.bind_addrs := ["127.0.0.1"]

# Directory & Log Configuration
music_dir = environment.get(default="/opt/astrazit-radio/music", "RADIO_MUSIC_DIR")
log_file = environment.get(default="/opt/astrazit-radio/logs/plays.jsonl", "RADIO_LOG_FILE")
output_mode = environment.get(default="dummy", "RADIO_OUTPUT_MODE")
output_file = environment.get(default="/opt/astrazit-radio/state/test_playout.wav", "RADIO_OUTPUT_FILE")
harbor_port = int_of_string(environment.get(default="8000", "RADIO_HARBOR_PORT"))
harbor_mount = environment.get(default="radio.wav", "RADIO_HARBOR_MOUNT")

# Station Lifecycle Logging: Start Event
file.write(data='{"timestamp":"' ^ string_of(time()) ^ '","event":"STATION_START"}\n', append=true, log_file)

# Station Lifecycle Logging: Stop Event on Process Termination
on_shutdown(fun () -> file.write(data='{"timestamp":"' ^ string_of(time()) ^ '","event":"STATION_STOP"}\n', append=true, log_file))

# Emergency Fallback Tone (440Hz sine wave)
fallback_source = sine(440.0)

# Local Audio Playlist Discovery
# Discovers .mp3, .wav, .flac, .m4a
playlist_source = playlist(
  reload_mode="watch",
  mode="normal",
  music_dir
)

# Crossfade Configuration (conservative 2.0s transition)
radio = crossfade(duration=2.0, playlist_source)

# Fallback Safety (Zero Dead Air)
station = fallback(track_sensitive=false, [radio, fallback_source])

# Track Transition Logger (JSONL append)
def log_track(m) =
  filename = m["filename"]
  log_entry = '{"timestamp":"' ^ string_of(time()) ^ '","event":"TRACK_START","track_name":"' ^ filename ^ '"}\n'
  file.write(data=log_entry, append=true, log_file)
end

playlist_source.on_track(log_track)

# Output Sink Selection
# - "dummy": Default headless playout (real-time decoding without physical audio device)
# - "file": Decoded audio PCM WAV sink for verification and acceptance testing
# - "harbor": Local HTTP streaming sink (uncompressed WAV on 127.0.0.1:8000) for FFmpeg video multiplexer
if output_mode == "file" then
  output.file(%wav, output_file, station)
elsif output_mode == "harbor" then
  output.harbor(%wav, port=harbor_port, mount=harbor_mount, station)
else
  output.dummy(station)
end
