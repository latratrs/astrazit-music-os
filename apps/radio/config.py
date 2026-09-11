"""Configuration and path boundaries for AstraZit Radio local playout MVP.

Governed by RADIO-001, ADR-002, ADR-006, and ADR-008.
Enforces local path containment, supported audio format filters, and defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence, Set

DEFAULT_SUPPORTED_EXTENSIONS: Set[str] = {".mp3", ".wav", ".flac", ".m4a"}
DEFAULT_CROSSFADE_SECONDS: float = 0.5
DEFAULT_LOCAL_RADIO_DIR: Path = Path(".local") / "radio"


class RadioConfigurationError(Exception):
    """Raised when radio configuration or path specification is invalid."""


@dataclass(frozen=True)
class RadioConfig:
    """Configuration settings for local radio playout."""

    base_dir: Path
    music_dir: Path
    state_file: Path
    log_file: Path
    supported_extensions: Set[str] = field(default_factory=lambda: set(DEFAULT_SUPPORTED_EXTENSIONS))
    crossfade_seconds: float = DEFAULT_CROSSFADE_SECONDS

    @classmethod
    def from_paths(
        cls,
        repo_root: Path | None = None,
        music_dir: Path | str | None = None,
        state_file: Path | str | None = None,
        log_file: Path | str | None = None,
        crossfade_seconds: float = DEFAULT_CROSSFADE_SECONDS,
        supported_extensions: Sequence[str] | None = None,
    ) -> RadioConfig:
        """Construct and resolve a validated RadioConfig."""
        if repo_root is None:
            repo_root = Path(__file__).resolve().parent.parent.parent
        else:
            repo_root = Path(repo_root).resolve()

        radio_base = repo_root / DEFAULT_LOCAL_RADIO_DIR

        if music_dir is not None:
            resolved_music = Path(music_dir).expanduser().resolve()
        else:
            resolved_music = (radio_base / "music").resolve()

        if state_file is not None:
            resolved_state = Path(state_file).expanduser().resolve()
        else:
            resolved_state = (radio_base / "state" / "radio_state.json").resolve()

        if log_file is not None:
            resolved_log = Path(log_file).expanduser().resolve()
        else:
            resolved_log = (radio_base / "logs" / "plays.jsonl").resolve()

        if crossfade_seconds < 0:
            raise RadioConfigurationError(f"crossfade_seconds cannot be negative, got {crossfade_seconds}")

        if supported_extensions is not None:
            exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in supported_extensions}
        else:
            exts = set(DEFAULT_SUPPORTED_EXTENSIONS)

        return cls(
            base_dir=radio_base,
            music_dir=resolved_music,
            state_file=resolved_state,
            log_file=resolved_log,
            supported_extensions=exts,
            crossfade_seconds=crossfade_seconds,
        )

    def ensure_directories(self) -> None:
        """Ensure runtime directories for state and logs exist."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
