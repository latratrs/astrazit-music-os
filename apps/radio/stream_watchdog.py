#!/usr/bin/env python3
"""FFmpeg Stream Publisher Progress Watchdog & Hang Recovery Wrapper.

Governed by RADIO-006A, ADR-002, ADR-006, ADR-008.

Failure Contract:
- Process liveness != stream progress.
- Monitors machine-readable FFmpeg progress via pipe (out_time_us monotonic advancement).
- If progress does not advance within the watchdog threshold (default: 30s),
  the supervisor initiates child termination: SIGTERM -> bounded wait -> SIGKILL -> reap child.
- Exits non-zero on progress stall so systemd Restart=always can recycle the service.
- Handles clean shutdown signals (SIGTERM, SIGINT) from systemd: terminates and reaps child before exiting.
- Secret safety: Never logs stream keys, full RTMPS URLs, complete argv, or environment variables.
- Accepted trust boundary: Root and the same user (astrazit) can inspect process argv/memory in /proc.
  The watchdog supervisor does not remove this existing MVP limitation, nor does ProtectProc/hidepid protect
  against root or the running service account itself.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import IO, List, Optional


DEFAULT_STALL_THRESHOLD_SEC = 30.0
DEFAULT_GRACE_PERIOD_SEC = 5.0
POLL_INTERVAL_SEC = 0.5

# Patterns to identify potential secret tokens in strings for safe logging
SECRET_KEY_PATTERN = re.compile(r"\b[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}(?:-[a-z0-9]{4})?\b")
RTMPS_URL_PATTERN = re.compile(r"rtmps://[^\s\"\']+", re.IGNORECASE)


def sanitize_log_message(msg: str) -> str:
    """Sanitize strings so no secrets or RTMPS destinations appear in log output."""
    if not msg:
        return ""
    sanitized = RTMPS_URL_PATTERN.sub("rtmps://[REDACTED_TARGET]", msg)
    sanitized = SECRET_KEY_PATTERN.sub("[REDACTED_KEY]", sanitized)
    return sanitized


def log_event(event: str, level: str = "INFO") -> None:
    """Emit a strictly sanitized operational log event to stderr."""
    clean_event = sanitize_log_message(event)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    sys.stderr.write(f"[{timestamp}] [WATCHDOG] [{level}] {clean_event}\n")
    sys.stderr.flush()


class ProgressParser:
    """Parses machine-readable key=value lines from FFmpeg -progress output."""

    def __init__(self) -> None:
        self.last_out_time_us: Optional[int] = None
        self.last_advance_time: float = time.monotonic()
        self.has_received_progress: bool = False
        self.is_ended: bool = False

    def process_line(self, line: str, now: Optional[float] = None) -> bool:
        """Process a single line of progress output.

        Returns True if progress advanced, False otherwise.
        """
        if now is None:
            now = time.monotonic()

        line = line.strip()
        if not line or "=" not in line:
            return False

        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()

        if key == "progress":
            self.has_received_progress = True
            if val == "end":
                self.is_ended = True
            return False

        if key == "out_time_us":
            self.has_received_progress = True
            try:
                time_us = int(val)
            except ValueError:
                # Malformed integer value: do not crash supervisor
                return False

            if self.last_out_time_us is None:
                # First progress value received
                self.last_out_time_us = time_us
                self.last_advance_time = now
                return True
            elif time_us > self.last_out_time_us:
                # Progress monotonically advanced
                self.last_out_time_us = time_us
                self.last_advance_time = now
                return True
            else:
                # Value unchanged or decreased (e.g. repeated identical progress)
                # Does NOT reset last_advance_time
                return False

        return False

    def time_since_advance(self, now: Optional[float] = None) -> float:
        """Seconds elapsed since the last monotonic progress advancement."""
        if now is None:
            now = time.monotonic()
        return now - self.last_advance_time


class ProcessLifecycleSupervisor:
    """Manages child process lifecycle, signal forwarding, and termination escalation."""

    def __init__(
        self,
        cmd: List[str],
        stall_threshold_sec: float = DEFAULT_STALL_THRESHOLD_SEC,
        grace_period_sec: float = DEFAULT_GRACE_PERIOD_SEC,
    ) -> None:
        self.cmd = cmd
        self.stall_threshold_sec = stall_threshold_sec
        self.grace_period_sec = grace_period_sec
        self.child: Optional[subprocess.Popen] = None
        self.shutdown_requested = False
        self.shutdown_signal: Optional[int] = None
        self.parser = ProgressParser()

    def handle_signal(self, signum: int, frame: object) -> None:
        """Signal handler for wrapper termination by systemd."""
        self.shutdown_requested = True
        self.shutdown_signal = signum
        log_event(f"Termination signal {signum} received by watchdog wrapper; stopping child", level="WARN")

    def register_signal_handlers(self) -> None:
        """Register signal handlers for SIGTERM and SIGINT."""
        try:
            signal.signal(signal.SIGTERM, self.handle_signal)
        except (ValueError, AttributeError):
            pass
        try:
            signal.signal(signal.SIGINT, self.handle_signal)
        except (ValueError, AttributeError):
            pass

    def terminate_and_reap_child(self, child: subprocess.Popen, reason: str) -> int:
        """Perform bounded escalation to terminate and reap child process:

        SIGTERM -> bounded wait -> SIGKILL -> reap (wait).
        Returns the child final exit code.
        """
        log_event(f"Termination sequence initiated for child PID {child.pid} (reason: {reason})", level="WARN")

        # Step 1: Request graceful termination
        try:
            child.terminate()
        except ProcessLookupError:
            pass
        except OSError as e:
            log_event(f"Error sending SIGTERM to PID {child.pid}: {e}", level="ERROR")

        # Step 2: Bounded wait
        wait_start = time.monotonic()
        while time.monotonic() - wait_start < self.grace_period_sec:
            ret = child.poll()
            if ret is not None:
                log_event(f"Child PID {child.pid} exited gracefully with code {ret}", level="INFO")
                return ret
            time.sleep(0.1)

        # Step 3: Escalate to SIGKILL if child is still running
        log_event(f"Child PID {child.pid} did not exit within {self.grace_period_sec}s grace period; sending SIGKILL", level="WARN")
        try:
            child.kill()
        except ProcessLookupError:
            pass
        except OSError as e:
            log_event(f"Error sending SIGKILL to PID {child.pid}: {e}", level="ERROR")

        # Step 4: Final reap
        try:
            ret = child.wait(timeout=5.0)
            log_event(f"Child PID {child.pid} killed and reaped with code {ret}", level="INFO")
            return ret
        except (subprocess.TimeoutExpired, OSError) as e:
            log_event(f"Critical: Failed to reap child PID {child.pid}: {e}", level="ERROR")
            return -1

    def run(self) -> int:
        """Run the supervisor loop.

        Returns exit code for wrapper:
        - 0: child exited normally with 0
        - non-zero: child exited non-zero or was killed due to stall (exit 124)
        """
        self.register_signal_handlers()
        log_event("Publisher progress watchdog started", level="INFO")

        actual_cmd = list(self.cmd)
        # On Windows, if actual_cmd[0] is an extensionless shell script with a shebang,
        # dispatch it via bash so local mock test scripts can execute cleanly.
        if os.name == "nt" and actual_cmd:
            cmd0 = actual_cmd[0]
            exe = None
            if os.path.isfile(cmd0):
                exe = cmd0
            else:
                for p in os.environ.get("PATH", "").split(os.pathsep):
                    cand = os.path.join(p, cmd0)
                    if os.path.isfile(cand):
                        exe = cand
                        break
            if exe and os.path.isfile(exe):
                try:
                    with open(exe, "rb") as probe_f:
                        lead = probe_f.readline(64)
                    if lead.startswith(b"#!"):
                        bash_bin = shutil.which("bash") or "C:\\Program Files\\Git\\bin\\bash.exe"
                        if os.path.isfile(bash_bin):
                            actual_cmd = [bash_bin, exe] + actual_cmd[1:]
                except Exception:
                    pass


        try:
            self.child = subprocess.Popen(
                actual_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            log_event(f"Failed to spawn publisher child: {e}", level="ERROR")
            if self.child is not None and getattr(self.child, "pid", None) is not None:
                try:
                    self.child.wait(timeout=1.0)
                except Exception:
                    pass
            return 1

        log_event(f"Publisher child process spawned (PID: {self.child.pid})", level="INFO")

        line_queue: queue.Queue[Optional[str]] = queue.Queue()

        def reader_thread(stream: IO[str]) -> None:
            try:
                for line in iter(stream.readline, ""):
                    line_queue.put(line)
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
                line_queue.put(None)

        assert self.child.stdout is not None
        child_stdout = self.child.stdout
        t = threading.Thread(target=reader_thread, args=(child_stdout,), daemon=True)
        t.start()

        def cleanup_reader() -> None:
            """Ensure child stdout pipe is closed and reader thread is joined with finite timeout."""
            try:
                child_stdout.close()
            except Exception:
                pass
            t.join(timeout=1.0)

        exit_code = 0
        is_stalled = False
        last_log_time = time.monotonic()

        while True:
            now = time.monotonic()

            if self.shutdown_requested:
                log_event("Watchdog stopping due to wrapper shutdown request", level="INFO")
                self.terminate_and_reap_child(self.child, reason="systemd service shutdown")
                cleanup_reader()
                return 0

            # Drain available progress lines
            while True:
                try:
                    line = line_queue.get_nowait()
                except queue.Empty:
                    break

                if line is None:
                    break

                advanced = self.parser.process_line(line, now=now)
                if advanced:
                    if now - last_log_time >= 60.0:
                        log_event(f"Progress healthy (out_time_us={self.parser.last_out_time_us})", level="INFO")
                        last_log_time = now

            # DS-P0 CHILD EXIT PRECEDENCE:
            # Check whether child has exited before evaluating progress stall timeout.
            # If child has exited, reap it and return its actual exit code.
            # Do NOT synthesize 124 timeout merely because progress=end was absent.
            child_ret = self.child.poll()
            if child_ret is not None:
                log_event(f"Publisher child exited with status {child_ret}", level="INFO")
                cleanup_reader()
                return child_ret

            time_since_advance = self.parser.time_since_advance(now=now)
            if time_since_advance >= self.stall_threshold_sec:
                # Double-check process exit immediately at stall deadline before declaring stall
                child_ret_recheck = self.child.poll()
                if child_ret_recheck is not None:
                    log_event(f"Publisher child exited with status {child_ret_recheck} at stall threshold", level="INFO")
                    cleanup_reader()
                    return child_ret_recheck

                log_event(
                    f"Publisher stalled! No progress advancement for {time_since_advance:.1f}s "
                    f"(threshold: {self.stall_threshold_sec:.1f}s, last out_time_us: {self.parser.last_out_time_us})",
                    level="ERROR",
                )
                is_stalled = True
                break

            time.sleep(POLL_INTERVAL_SEC)

        if is_stalled and self.child is not None:
            self.terminate_and_reap_child(self.child, reason="progress stall watchdog timeout")
            cleanup_reader()
            log_event("Watchdog exiting with status 124 for systemd recovery", level="WARN")
            return 124

        cleanup_reader()
        return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="AstraZit Radio FFmpeg Publisher Progress Watchdog")
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.environ.get("STREAM_WATCHDOG_TIMEOUT_SEC", DEFAULT_STALL_THRESHOLD_SEC)),
        help=f"Stall detection threshold in seconds (default: {DEFAULT_STALL_THRESHOLD_SEC}s)",
    )
    parser.add_argument(
        "--grace-period",
        type=float,
        default=float(os.environ.get("STREAM_WATCHDOG_GRACE_SEC", DEFAULT_GRACE_PERIOD_SEC)),
        help=f"Grace period in seconds between SIGTERM and SIGKILL (default: {DEFAULT_GRACE_PERIOD_SEC}s)",
    )
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command line of the child publisher (e.g. ffmpeg ...)",
    )

    args = parser.parse_args()

    if args.threshold <= 0:
        sys.stderr.write("ERROR: Watchdog threshold must be positive.\n")
        return 1

    child_cmd = args.cmd
    if child_cmd and child_cmd[0] == "--":
        child_cmd = child_cmd[1:]

    if not child_cmd:
        sys.stderr.write("ERROR: No child command specified to supervise.\n")
        return 1

    supervisor = ProcessLifecycleSupervisor(
        cmd=child_cmd,
        stall_threshold_sec=args.threshold,
        grace_period_sec=args.grace_period,
    )
    return supervisor.run()


if __name__ == "__main__":
    sys.exit(main())
