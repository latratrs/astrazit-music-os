"""CLI interface for AstraZit Radio local playout MVP.

Governed by RADIO-001.
Provides:
    play [--music-dir PATH] [--max-tracks N] [--crossfade S] [--realtime]
    status [--state-file PATH]
    history [--log-file PATH] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from apps.radio.config import RadioConfig
from apps.radio.player import LocalRadioPlayout, PlayoutEvent
from apps.radio.state import RadioStateManager


def print_event(ev: PlayoutEvent) -> None:
    if ev.event_type == "TRACK_START" and ev.track:
        print(f"[{ev.timestamp}] PLAY (seq #{ev.sequence_number}): {ev.track.filename} ({ev.duration_seconds}s)")
    elif ev.event_type == "TRANSITION" and ev.track:
        print(f"[{ev.timestamp}] TRANSITION (crossfade {ev.transition_seconds}s)")
    elif ev.event_type == "TRACK_END" and ev.track:
        print(f"[{ev.timestamp}] END: {ev.track.filename}")
    elif ev.event_type == "STATION_STOP":
        print(f"[{ev.timestamp}] STOPPED: Playout completed (last seq #{ev.sequence_number}).")


def cmd_play(args: argparse.Namespace) -> int:
    try:
        config = RadioConfig.from_paths(
            music_dir=args.music_dir,
            state_file=args.state_file,
            log_file=args.log_file,
            crossfade_seconds=args.crossfade,
        )
        config.ensure_directories()
    except Exception as exc:
        print(f"ERROR: Configuration failure: {exc}", file=sys.stderr)
        return 1

    player = LocalRadioPlayout(
        config=config,
        event_callback=print_event,
    )

    print(f"Starting AstraZit Radio Local Playout MVP...")
    print(f"  Music directory: {config.music_dir}")
    print(f"  State file:      {config.state_file}")
    print(f"  Play log file:   {config.log_file}")
    print(f"  Crossfade:       {config.crossfade_seconds}s")
    if args.max_tracks:
        print(f"  Max tracks:      {args.max_tracks}")
    print("------------------------------------------------------------")

    try:
        player.play_sequence(
            max_tracks=args.max_tracks,
            realtime_simulation=args.realtime,
        )
        print("------------------------------------------------------------")
        print("Playout finished successfully.")
        return 0
    except KeyboardInterrupt:
        print("\nOperator interrupted playback.", file=sys.stderr)
        player.request_stop()
        return 0
    except Exception as exc:
        print(f"ERROR during playout: {exc}", file=sys.stderr)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    config = RadioConfig.from_paths(
        music_dir=args.music_dir,
        state_file=args.state_file,
        log_file=args.log_file,
    )
    manager = RadioStateManager(state_file=config.state_file, log_file=config.log_file)
    state = manager.load_state()

    print("============================================================")
    print("ASTRAZIT RADIO -- RUNTIME STATE")
    print("============================================================")
    print(f"Status:               {state.status}")
    print(f"Sequence Count:       {state.sequence_count}")
    print(f"Current Track:        {state.current_track or 'None'}")
    print(f"Current Track Path:   {state.current_track_path or 'None'}")
    print(f"Previous Track:       {state.previous_track or 'None'}")
    print(f"Last Transition Time: {state.last_transition_time or 'None'}")
    print(f"Last Updated:         {state.updated_at}")
    print("============================================================")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    config = RadioConfig.from_paths(
        music_dir=args.music_dir,
        state_file=args.state_file,
        log_file=args.log_file,
    )
    manager = RadioStateManager(state_file=config.state_file, log_file=config.log_file)
    logs = manager.read_play_logs()

    limit = args.limit or len(logs)
    selected = logs[-limit:]

    print("============================================================")
    print(f"ASTRAZIT RADIO -- PLAY HISTORY (Latest {len(selected)} events)")
    print("============================================================")
    if not selected:
        print("No play events recorded.")
    else:
        for item in selected:
            seq = item.get("sequence_number", "-")
            evt = item.get("event", "UNKNOWN")
            trk = item.get("track_name", "UNKNOWN")
            ts = item.get("timestamp", "")
            dur = item.get("duration_seconds")
            dur_str = f" ({dur}s)" if dur is not None else ""
            print(f"[{ts}] [#{seq}] {evt:<12} {trk}{dur_str}")
    print("============================================================")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apps.radio",
        description="AstraZit Radio Local Playout MVP",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # play
    p_play = subparsers.add_parser("play", help="Start local radio playout")
    p_play.add_argument("--music-dir", type=str, default=None, help="Path to music folder")
    p_play.add_argument("--state-file", type=str, default=None, help="Custom state file path")
    p_play.add_argument("--log-file", type=str, default=None, help="Custom log file path")
    p_play.add_argument("--max-tracks", type=int, default=None, help="Halt after N tracks")
    p_play.add_argument("--crossfade", type=float, default=0.5, help="Crossfade duration in seconds")
    p_play.add_argument("--realtime", action="store_true", help="Sleep in real-time between tracks")
    p_play.set_defaults(func=cmd_play)

    # status
    p_status = subparsers.add_parser("status", help="Show current radio state")
    p_status.add_argument("--music-dir", type=str, default=None)
    p_status.add_argument("--state-file", type=str, default=None)
    p_status.add_argument("--log-file", type=str, default=None)
    p_status.set_defaults(func=cmd_status)

    # history
    p_history = subparsers.add_parser("history", help="Show play history log")
    p_history.add_argument("--music-dir", type=str, default=None)
    p_history.add_argument("--state-file", type=str, default=None)
    p_history.add_argument("--log-file", type=str, default=None)
    p_history.add_argument("--limit", type=int, default=20, help="Number of records to show")
    p_history.set_defaults(func=cmd_history)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
