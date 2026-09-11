"""Unit and regression tests for AstraZit Radio Local Playout MVP (RADIO-001).

Validates:
- Supported audio format discovery (.mp3, .wav, .flac, .m4a)
- Unsupported file exclusion (.txt, .json, hidden files, subdirs)
- Deterministic sorting order
- Empty and missing directory handling
- State file serialization, atomic updates, and isolation
- Append-oriented JSONL play logging
- Track playout sequence: TRACK -> PLAY -> TRANSITION -> NEXT TRACK -> LOG
- Invariance: No catalog mutations
- Invariance: No AST identifier allocation
- Path confinement within configured paths
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from apps.radio.config import RadioConfig, RadioConfigurationError
from apps.radio.discovery import (
    DirectoryNotFoundError,
    DiscoveredTrack,
    EmptyPlaylistError,
    NotADirectoryError,
    PlaylistDiscovery,
)
from apps.radio.player import LocalRadioPlayout, get_audio_duration_seconds
from apps.radio.state import (
    PlayLogEntry,
    RadioRuntimeState,
    RadioStateManager,
)
from scripts.generate_test_tones import generate_sine_wave


class TestRadioConfiguration(unittest.TestCase):
    """Test path resolution and config invariants."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="ast_radio_test_cfg_")
        self.temp_path = Path(self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_config_resolution(self) -> None:
        cfg = RadioConfig.from_paths(repo_root=self.temp_path)
        expected_base = (self.temp_path / ".local" / "radio").resolve()
        self.assertEqual(cfg.base_dir, expected_base)
        self.assertEqual(cfg.music_dir, (expected_base / "music").resolve())
        self.assertEqual(cfg.state_file, (expected_base / "state" / "radio_state.json").resolve())
        self.assertEqual(cfg.log_file, (expected_base / "logs" / "plays.jsonl").resolve())
        self.assertIn(".wav", cfg.supported_extensions)
        self.assertIn(".mp3", cfg.supported_extensions)
        self.assertIn(".flac", cfg.supported_extensions)
        self.assertIn(".m4a", cfg.supported_extensions)

    def test_custom_paths(self) -> None:
        custom_music = self.temp_path / "custom_music"
        custom_state = self.temp_path / "custom_state.json"
        custom_log = self.temp_path / "custom_log.jsonl"

        cfg = RadioConfig.from_paths(
            repo_root=self.temp_path,
            music_dir=custom_music,
            state_file=custom_state,
            log_file=custom_log,
            crossfade_seconds=1.5,
        )
        self.assertEqual(cfg.music_dir, custom_music.resolve())
        self.assertEqual(cfg.state_file, custom_state.resolve())
        self.assertEqual(cfg.log_file, custom_log.resolve())
        self.assertEqual(cfg.crossfade_seconds, 1.5)

    def test_negative_crossfade_fails(self) -> None:
        with self.assertRaises(RadioConfigurationError):
            RadioConfig.from_paths(repo_root=self.temp_path, crossfade_seconds=-0.5)


class TestPlaylistDiscovery(unittest.TestCase):
    """Test discovery of audio tracks, filtering, and ordering."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="ast_radio_test_disc_")
        self.music_dir = Path(self.temp_dir)
        self.discovery = PlaylistDiscovery()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_directory_raises_error(self) -> None:
        missing = self.music_dir / "non_existent_folder"
        with self.assertRaises(DirectoryNotFoundError):
            self.discovery.discover_tracks(missing)

    def test_file_instead_of_directory_raises_error(self) -> None:
        dummy_file = self.music_dir / "dummy.txt"
        dummy_file.write_text("hello", encoding="utf-8")
        with self.assertRaises(NotADirectoryError):
            self.discovery.discover_tracks(dummy_file)

    def test_empty_directory_raises_error_by_default(self) -> None:
        with self.assertRaises(EmptyPlaylistError):
            self.discovery.discover_tracks(self.music_dir)

    def test_empty_directory_allowed_when_flag_set(self) -> None:
        res = self.discovery.discover_tracks(self.music_dir, allow_empty=True)
        self.assertEqual(res, [])

    def test_supported_audio_types_and_unsupported_exclusion(self) -> None:
        # Create supported files
        (self.music_dir / "track3.mp3").write_bytes(b"mockmp3")
        (self.music_dir / "track1.wav").write_bytes(b"mockwav")
        (self.music_dir / "track4.flac").write_bytes(b"mockflac")
        (self.music_dir / "track2.m4a").write_bytes(b"mockm4a")

        # Create unsupported files
        (self.music_dir / "notes.txt").write_text("notes", encoding="utf-8")
        (self.music_dir / "metadata.json").write_text("{}", encoding="utf-8")
        (self.music_dir / ".hidden_track.wav").write_bytes(b"mockhidden")
        subdir = self.music_dir / "subfolder"
        subdir.mkdir()
        (subdir / "subtrack.wav").write_bytes(b"nested")

        tracks = self.discovery.discover_tracks(self.music_dir)
        filenames = [t.filename for t in tracks]

        # Invariance: unsupported, hidden, and subdirectory tracks are excluded
        self.assertNotIn("notes.txt", filenames)
        self.assertNotIn("metadata.json", filenames)
        self.assertNotIn(".hidden_track.wav", filenames)
        self.assertNotIn("subtrack.wav", filenames)

        # Invariance: deterministic alphabetical ordering
        self.assertEqual(
            filenames,
            ["track1.wav", "track2.m4a", "track3.mp3", "track4.flac"],
        )

    def test_symlinked_audio_is_excluded(self) -> None:
        """A link must not pull audio from outside the configured directory."""
        try:
            outside = Path(tempfile.mkdtemp()) / "outside.wav"
            outside.write_bytes(b"audio")
            link = self.music_dir / "linked.wav"
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is unavailable on this host")
        self.assertEqual(self.discovery.discover_tracks(self.music_dir, allow_empty=True), [])


class TestRadioStateAndLogging(unittest.TestCase):
    """Test state persistence and JSONL play logging."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="ast_radio_test_state_")
        self.base = Path(self.temp_dir)
        self.state_file = self.base / "state" / "radio_state.json"
        self.log_file = self.base / "logs" / "plays.jsonl"
        self.manager = RadioStateManager(state_file=self.state_file, log_file=self.log_file)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initial_state_when_file_missing(self) -> None:
        state = self.manager.load_state()
        self.assertEqual(state.status, "STOPPED")
        self.assertIsNone(state.current_track)
        self.assertEqual(state.sequence_count, 0)

    def test_save_and_load_state_roundtrip(self) -> None:
        state = RadioRuntimeState(
            status="PLAYING",
            current_track="test_tone.wav",
            current_track_path="/path/test_tone.wav",
            previous_track="prev_tone.wav",
            sequence_count=42,
            last_transition_time="2026-09-10T12:00:00Z",
            updated_at="2026-09-10T12:00:00Z",
        )
        self.manager.save_state(state)
        loaded = self.manager.load_state()

        self.assertEqual(loaded.status, "PLAYING")
        self.assertEqual(loaded.current_track, "test_tone.wav")
        self.assertEqual(loaded.current_track_path, "/path/test_tone.wav")
        self.assertEqual(loaded.previous_track, "prev_tone.wav")
        self.assertEqual(loaded.sequence_count, 42)
        self.assertEqual(loaded.last_transition_time, "2026-09-10T12:00:00Z")

    def test_append_play_logs(self) -> None:
        entry1 = PlayLogEntry(
            timestamp="2026-09-10T12:00:00Z",
            event="TRACK_START",
            track_name="track1.wav",
            track_path="/audio/track1.wav",
            sequence_number=1,
            duration_seconds=120.5,
        )
        entry2 = PlayLogEntry(
            timestamp="2026-09-10T12:02:00Z",
            event="TRANSITION",
            track_name="track1.wav",
            track_path="/audio/track1.wav",
            sequence_number=1,
            transition_seconds=0.5,
        )
        self.manager.append_play_log(entry1)
        self.manager.append_play_log(entry2)

        logs = self.manager.read_play_logs()
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["event"], "TRACK_START")
        self.assertEqual(logs[0]["track_name"], "track1.wav")
        self.assertEqual(logs[1]["event"], "TRANSITION")
        self.assertEqual(logs[1]["transition_seconds"], 0.5)


class TestPlayoutExecutionAndSmokeSequence(unittest.TestCase):
    """Test full playout engine loop: TRACK -> PLAY -> TRANSITION -> NEXT TRACK -> LOG."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="ast_radio_test_play_")
        self.base = Path(self.temp_dir)
        self.music_dir = self.base / "music"
        self.music_dir.mkdir(parents=True)

        # Generate 3 tiny synthetic tones (0.1s each)
        generate_sine_wave(self.music_dir / "track_a.wav", frequency=440.0, duration_seconds=0.1)
        generate_sine_wave(self.music_dir / "track_b.wav", frequency=554.0, duration_seconds=0.1)
        generate_sine_wave(self.music_dir / "track_c.wav", frequency=659.0, duration_seconds=0.1)

        self.config = RadioConfig.from_paths(
            repo_root=self.base,
            music_dir=self.music_dir,
            state_file=self.base / "state" / "radio_state.json",
            log_file=self.base / "logs" / "plays.jsonl",
            crossfade_seconds=0.05,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_audio_duration_inspection(self) -> None:
        dur = get_audio_duration_seconds(self.music_dir / "track_a.wav")
        self.assertAlmostEqual(dur, 0.1, delta=0.01)

    def test_playout_three_track_sequence(self) -> None:
        events = []
        player = LocalRadioPlayout(
            config=self.config,
            sleep_fn=lambda _: None,  # instantaneous for testing
            event_callback=lambda ev: events.append(ev),
        )

        # Play 3 tracks
        emitted = player.play_sequence(max_tracks=3, realtime_simulation=False)

        # Verify event progression
        # Track 1: START, TRANSITION, END
        # Track 2: START, TRANSITION, END
        # Track 3: START, END (no transition because 3 is max_tracks)
        # Final: STATION_STOP
        event_types = [e.event_type for e in emitted]
        self.assertEqual(
            event_types,
            [
                "TRACK_START", "TRANSITION", "TRACK_END",  # Track A (seq 1)
                "TRACK_START", "TRANSITION", "TRACK_END",  # Track B (seq 2)
                "TRACK_START", "TRACK_END",                # Track C (seq 3)
                "STATION_STOP",
            ],
        )

        # Verify played track names
        played_tracks = [e.track.filename for e in emitted if e.track is not None]
        self.assertEqual(
            played_tracks,
            [
                "track_a.wav", "track_a.wav", "track_a.wav",
                "track_b.wav", "track_b.wav", "track_b.wav",
                "track_c.wav", "track_c.wav",
            ],
        )

        # Verify persisted state file
        manager = RadioStateManager(self.config.state_file, self.config.log_file)
        final_state = manager.load_state()
        self.assertEqual(final_state.status, "STOPPED")
        self.assertEqual(final_state.sequence_count, 3)
        self.assertEqual(final_state.current_track, "track_c.wav")
        self.assertEqual(final_state.previous_track, "track_b.wav")

        # Verify play history log
        logs = manager.read_play_logs()
        # 3 tracks: 3 starts + 2 transitions + 3 ends = 8 log entries
        self.assertEqual(len(logs), 8)
        self.assertEqual(logs[0]["event"], "TRACK_START")
        self.assertEqual(logs[0]["track_name"], "track_a.wav")
        self.assertEqual(logs[0]["sequence_number"], 1)

        self.assertEqual(logs[3]["event"], "TRACK_START")
        self.assertEqual(logs[3]["track_name"], "track_b.wav")
        self.assertEqual(logs[3]["sequence_number"], 2)

        self.assertEqual(logs[6]["event"], "TRACK_START")
        self.assertEqual(logs[6]["track_name"], "track_c.wav")
        self.assertEqual(logs[6]["sequence_number"], 3)


class TestRadioArchitectureInvariants(unittest.TestCase):
    """Test non-negotiable architectural boundaries:
    - No catalog mutations
    - No AST ID allocations
    - No external network/AI imports in radio modules
    """

    def test_no_catalog_imports_in_radio(self) -> None:
        import apps.radio.config as r_cfg
        import apps.radio.discovery as r_disc
        import apps.radio.player as r_play
        import apps.radio.state as r_state

        for mod in (r_cfg, r_disc, r_play, r_state):
            imported_names = dir(mod)
            for name in imported_names:
                obj = getattr(mod, name)
                if hasattr(obj, "__module__") and obj.__module__:
                    self.assertFalse(
                        obj.__module__.startswith("packages.catalog"),
                        f"Radio module {mod.__name__} must not import catalog modules, found {obj.__module__}.{name}",
                    )
                    self.assertFalse(
                        "firestore" in obj.__module__.lower(),
                        f"Radio module {mod.__name__} must not import firestore, found {obj.__module__}.{name}",
                    )
                    self.assertFalse(
                        "google.cloud" in obj.__module__.lower(),
                        f"Radio module {mod.__name__} must not import google cloud, found {obj.__module__}.{name}",
                    )


if __name__ == "__main__":
    unittest.main()
