"""Runtime state and play history logging for AstraZit Radio.

Governed by RADIO-001, ADR-002, and ADR-006.
Writes:
- .local/radio/logs/plays.jsonl (append-only machine readable play log)
- .local/radio/state/radio_state.json (atomic snapshot of radio status)
Does NOT log secrets.
Does NOT write catalog records.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def iso_utc_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PlayLogEntry:
    """A single append-only play event record."""

    timestamp: str
    event: str  # e.g. "TRACK_START", "TRANSITION", "TRACK_END"
    track_name: str
    track_path: str
    sequence_number: int
    duration_seconds: Optional[float] = None
    transition_seconds: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "sequence_number": self.sequence_number,
            "track_name": self.track_name,
            "track_path": self.track_path,
            "duration_seconds": self.duration_seconds,
            "transition_seconds": self.transition_seconds,
        }


@dataclass
class RadioRuntimeState:
    """Snapshot of current radio playback engine state."""

    status: str  # "STOPPED", "PLAYING", "TRANSITIONING"
    current_track: Optional[str]
    current_track_path: Optional[str]
    previous_track: Optional[str]
    sequence_count: int
    last_transition_time: Optional[str]
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def initial(cls) -> RadioRuntimeState:
        return cls(
            status="STOPPED",
            current_track=None,
            current_track_path=None,
            previous_track=None,
            sequence_count=0,
            last_transition_time=None,
            updated_at=iso_utc_now(),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RadioRuntimeState:
        return cls(
            status=str(data.get("status", "STOPPED")),
            current_track=data.get("current_track"),
            current_track_path=data.get("current_track_path"),
            previous_track=data.get("previous_track"),
            sequence_count=int(data.get("sequence_count", 0)),
            last_transition_time=data.get("last_transition_time"),
            updated_at=str(data.get("updated_at", iso_utc_now())),
        )


class RadioStateManager:
    """Manages atomic state updates and append-oriented play log writes."""

    def __init__(self, state_file: Path, log_file: Path) -> None:
        self.state_file = state_file.resolve()
        self.log_file = log_file.resolve()
        self._ensure_paths()

    def _ensure_paths(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def load_state(self) -> RadioRuntimeState:
        """Load current state from disk or return initial state if file does not exist."""
        if not self.state_file.exists():
            return RadioRuntimeState.initial()
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RadioRuntimeState.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return RadioRuntimeState.initial()

    def save_state(self, state: RadioRuntimeState) -> None:
        """Atomically persist runtime state using tempfile + os.replace."""
        state_data = state.to_dict()
        state_dir = self.state_file.parent
        self._ensure_paths()

        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix="radio_state_",
            suffix=".tmp",
            dir=str(state_dir),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_file)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    def append_play_log(self, entry: PlayLogEntry) -> None:
        """Append an entry to plays.jsonl with sync."""
        self._ensure_paths()
        line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def read_play_logs(self) -> List[Dict[str, Any]]:
        """Read all play log entries from plays.jsonl."""
        if not self.log_file.exists():
            return []
        entries: List[Dict[str, Any]] = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries
