"""Playlist discovery layer for AstraZit Radio local playout MVP.

Governed by RADIO-001, ADR-002, ADR-006, and ADR-008.
Discovers local audio tracks deterministically from an explicitly configured folder.
Does NOT allocate AST identifiers.
Does NOT mutate catalog records.
Does NOT infer or clear rights state.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Set

from apps.radio.config import DEFAULT_SUPPORTED_EXTENSIONS


class DiscoveryError(Exception):
    """Base exception for playlist discovery errors."""


class DirectoryNotFoundError(DiscoveryError):
    """Raised when the specified audio folder does not exist."""


class NotADirectoryError(DiscoveryError):
    """Raised when the specified audio path is not a directory."""


class EmptyPlaylistError(DiscoveryError):
    """Raised when no supported audio files are found in the audio directory."""


@dataclass(frozen=True)
class DiscoveredTrack:
    """Represents a discovered local audio track candidate."""

    file_path: Path
    filename: str
    extension: str
    size_bytes: int

    @property
    def title_guess(self) -> str:
        """Derive a friendly display title from the stem without asserting catalog truth."""
        return self.file_path.stem


class PlaylistDiscovery:
    """Discovers audio files from a local filesystem directory."""

    def __init__(self, supported_extensions: Set[str] | Sequence[str] | None = None) -> None:
        if supported_extensions is None:
            self.supported_extensions = set(DEFAULT_SUPPORTED_EXTENSIONS)
        else:
            self.supported_extensions = {
                ext.lower() if ext.startswith(".") else f".{ext.lower()}"
                for ext in supported_extensions
            }

    def discover_tracks(
        self,
        music_dir: Path | str,
        allow_empty: bool = False,
    ) -> List[DiscoveredTrack]:
        """Scan music_dir for supported audio tracks.

        - Rejects missing paths or non-directories.
        - Non-recursive: strictly inspects the immediate folder to avoid unbounded traversal.
        - Ignores unsupported files, hidden files, and subdirectories.
        - Deterministic ordering: sorted by lowercase filename, tie-broken by raw filename.
        """
        dir_path = Path(music_dir).expanduser().resolve()

        if not dir_path.exists():
            raise DirectoryNotFoundError(f"Music directory does not exist: {dir_path}")

        if not dir_path.is_dir():
            raise NotADirectoryError(f"Music path is not a directory: {dir_path}")

        discovered: List[DiscoveredTrack] = []

        try:
            entries = list(dir_path.iterdir())
        except OSError as exc:
            raise DiscoveryError(f"Cannot read music directory {dir_path}: {exc}") from exc

        # Deterministic sorting
        for entry in sorted(entries, key=lambda p: (p.name.lower(), p.name)):
            # Never follow a link to audio outside the explicitly configured
            # directory.  Only regular files directly owned by music_dir are
            # eligible for discovery.
            if entry.is_symlink():
                continue
            if not entry.is_file():
                continue
            if entry.name.startswith("."):
                continue

            ext = entry.suffix.lower()
            if ext in self.supported_extensions:
                try:
                    stat = entry.stat()
                    discovered.append(
                        DiscoveredTrack(
                            file_path=entry.resolve(),
                            filename=entry.name,
                            extension=ext,
                            size_bytes=stat.st_size,
                        )
                    )
                except OSError:
                    continue

        if not discovered and not allow_empty:
            raise EmptyPlaylistError(
                f"No supported audio tracks ({', '.join(sorted(self.supported_extensions))}) "
                f"found in {dir_path}"
            )

        return discovered
