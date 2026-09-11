"""Local radio playout engine for AstraZit Radio MVP.

Governed by RADIO-001, ADR-002, and ADR-006.
Orchestrates:
    TRACK -> PLAY -> TRANSITION -> NEXT TRACK -> LOG
Provides a deterministic local playout loop, transition logic,
event dispatching, and atomic state updates.
"""
from __future__ import annotations

import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from apps.radio.config import RadioConfig
from apps.radio.discovery import DiscoveredTrack, PlaylistDiscovery
from apps.radio.state import (
    PlayLogEntry,
    RadioRuntimeState,
    RadioStateManager,
    iso_utc_now,
)


def get_audio_duration_seconds(track_path: Path) -> float:
    """Attempt to read duration from standard wav header, or default to a safe value."""
    if track_path.suffix.lower() == ".wav":
        try:
            with wave.open(str(track_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return frames / float(rate)
        except Exception:
            pass
    return 3.0  # fallback duration for testing/unparsed formats


@dataclass
class PlayoutEvent:
    """Broadcast event received by subscribers or tests."""

    event_type: str  # "TRACK_START", "TRANSITION", "TRACK_END", "STATION_STOP"
    track: Optional[DiscoveredTrack]
    sequence_number: int
    timestamp: str
    duration_seconds: Optional[float] = None
    transition_seconds: Optional[float] = None


class LocalRadioPlayout:
    """Executes the local radio playout state machine."""

    def __init__(
        self,
        config: RadioConfig,
        sleep_fn: Optional[Callable[[float], None]] = None,
        event_callback: Optional[Callable[[PlayoutEvent], None]] = None,
    ) -> None:
        self.config = config
        self.sleep_fn = sleep_fn if sleep_fn is not None else time.sleep
        self.event_callback = event_callback
        self.discovery = PlaylistDiscovery(supported_extensions=config.supported_extensions)
        self.state_manager = RadioStateManager(
            state_file=config.state_file,
            log_file=config.log_file,
        )
        self._stop_requested = False

    def request_stop(self) -> None:
        """Signal the playout engine to stop after current step."""
        self._stop_requested = True

    def _emit(self, event: PlayoutEvent) -> None:
        if self.event_callback:
            self.event_callback(event)

    def play_sequence(
        self,
        max_tracks: Optional[int] = None,
        realtime_simulation: bool = False,
    ) -> List[PlayoutEvent]:
        """Execute playback loop over discovered playlist.

        If max_tracks is specified, halts cleanly after playing max_tracks.
        If realtime_simulation is True, sleeps for track duration and crossfade.
        Otherwise, executes instantaneous state machine steps (ideal for tests).
        """
        tracks = self.discovery.discover_tracks(self.config.music_dir)
        events_emitted: List[PlayoutEvent] = []

        current_state = self.state_manager.load_state()
        sequence_num = current_state.sequence_count

        track_index = 0
        tracks_played = 0

        while not self._stop_requested:
            if max_tracks is not None and tracks_played >= max_tracks:
                break

            current_track = tracks[track_index % len(tracks)]
            track_index += 1
            sequence_num += 1
            tracks_played += 1

            duration = get_audio_duration_seconds(current_track.file_path)
            now = iso_utc_now()

            # 1. TRACK START
            current_state = RadioRuntimeState(
                status="PLAYING",
                current_track=current_track.filename,
                current_track_path=str(current_track.file_path),
                previous_track=current_state.current_track,
                sequence_count=sequence_num,
                last_transition_time=current_state.last_transition_time,
                updated_at=now,
            )
            self.state_manager.save_state(current_state)

            start_entry = PlayLogEntry(
                timestamp=now,
                event="TRACK_START",
                track_name=current_track.filename,
                track_path=str(current_track.file_path),
                sequence_number=sequence_num,
                duration_seconds=round(duration, 3),
            )
            self.state_manager.append_play_log(start_entry)

            ev_start = PlayoutEvent(
                event_type="TRACK_START",
                track=current_track,
                sequence_number=sequence_num,
                timestamp=now,
                duration_seconds=round(duration, 3),
            )
            events_emitted.append(ev_start)
            self._emit(ev_start)

            # Simulate playback duration
            if realtime_simulation and duration > 0:
                self.sleep_fn(duration)

            if self._stop_requested:
                break

            # 2. TRANSITION (if there is a next track)
            has_next = (max_tracks is None) or (tracks_played < max_tracks)
            if has_next:
                trans_now = iso_utc_now()
                current_state = RadioRuntimeState(
                    status="TRANSITIONING",
                    current_track=current_track.filename,
                    current_track_path=str(current_track.file_path),
                    previous_track=current_state.previous_track,
                    sequence_count=sequence_num,
                    last_transition_time=trans_now,
                    updated_at=trans_now,
                )
                self.state_manager.save_state(current_state)

                trans_entry = PlayLogEntry(
                    timestamp=trans_now,
                    event="TRANSITION",
                    track_name=current_track.filename,
                    track_path=str(current_track.file_path),
                    sequence_number=sequence_num,
                    transition_seconds=self.config.crossfade_seconds,
                )
                self.state_manager.append_play_log(trans_entry)

                ev_trans = PlayoutEvent(
                    event_type="TRANSITION",
                    track=current_track,
                    sequence_number=sequence_num,
                    timestamp=trans_now,
                    transition_seconds=self.config.crossfade_seconds,
                )
                events_emitted.append(ev_trans)
                self._emit(ev_trans)

                if realtime_simulation and self.config.crossfade_seconds > 0:
                    self.sleep_fn(self.config.crossfade_seconds)

            # 3. TRACK END
            end_now = iso_utc_now()
            end_entry = PlayLogEntry(
                timestamp=end_now,
                event="TRACK_END",
                track_name=current_track.filename,
                track_path=str(current_track.file_path),
                sequence_number=sequence_num,
                duration_seconds=round(duration, 3),
            )
            self.state_manager.append_play_log(end_entry)

            ev_end = PlayoutEvent(
                event_type="TRACK_END",
                track=current_track,
                sequence_number=sequence_num,
                timestamp=end_now,
                duration_seconds=round(duration, 3),
            )
            events_emitted.append(ev_end)
            self._emit(ev_end)

        # Final state update: STOPPED
        final_now = iso_utc_now()
        stopped_state = RadioRuntimeState(
            status="STOPPED",
            current_track=current_state.current_track,
            current_track_path=current_state.current_track_path,
            previous_track=current_state.previous_track,
            sequence_count=sequence_num,
            last_transition_time=current_state.last_transition_time,
            updated_at=final_now,
        )
        self.state_manager.save_state(stopped_state)

        ev_stop = PlayoutEvent(
            event_type="STATION_STOP",
            track=None,
            sequence_number=sequence_num,
            timestamp=final_now,
        )
        events_emitted.append(ev_stop)
        self._emit(ev_stop)

        return events_emitted
