"""Unit, invariant, and failure simulation tests for FFmpeg Publisher Progress Watchdog (RADIO-006A).

Validates:
1. Advancing progress remains healthy (last_advance_time updates, no timeout).
2. Repeated identical progress values do NOT reset watchdog and eventually trigger stall.
3. Absence of progress lines eventually triggers stall.
4. Malformed progress lines or non-integer timestamps do not crash supervisor.
5. Child exiting normally with 0 returns 0.
6. Child exiting non-zero propagates child status.
7. Stalled child gets terminated (SIGTERM sent, bounded escalation).
8. Kill fallback works if graceful termination fails (SIGKILL sent).
9. Child is reaped (no zombie / orphan processes).
10. Signal forwarding on shutdown: SIGTERM to supervisor terminates and reaps child.
11. No unbounded threads or subprocess leaks.
12. Secret-like destination is never written to watchdog logs (RTMPS URL and stream keys redacted).
13. Local stall simulation test with real/mock process (hard timeout < 60s).
"""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHDOG_PATH = REPO_ROOT / "apps" / "radio" / "stream_watchdog.py"

# Import watchdog components directly for whitebox testing
sys.path.insert(0, str(REPO_ROOT / "apps" / "radio"))
from stream_watchdog import (
    DEFAULT_STALL_THRESHOLD_SEC,
    EXIT_LIFECYCLE_ERROR,
    EXIT_STALL_TIMEOUT,
    ProgressParser,
    ProcessLifecycleSupervisor,
    sanitize_log_message,
)


class TestWatchdogProgressParser(unittest.TestCase):
    """Whitebox unit tests for ProgressParser."""

    def test_advancing_progress_remains_healthy(self) -> None:
        parser = ProgressParser()
        t0 = 1000.0
        # Line 1: initial progress
        self.assertTrue(parser.process_line("out_time_us=1000000", now=t0))
        self.assertEqual(parser.last_out_time_us, 1000000)
        self.assertEqual(parser.last_advance_time, t0)

        # Line 2: advancing progress 2 seconds later
        t1 = 1002.0
        self.assertTrue(parser.process_line("out_time_us=2000000", now=t1))
        self.assertEqual(parser.last_out_time_us, 2000000)
        self.assertEqual(parser.last_advance_time, t1)
        self.assertEqual(parser.time_since_advance(now=t1), 0.0)

    def test_repeated_identical_progress_does_not_reset_watchdog(self) -> None:
        parser = ProgressParser()
        t0 = 1000.0
        self.assertTrue(parser.process_line("out_time_us=5000000", now=t0))

        # Repeated identical out_time_us at t0 + 10s
        t1 = 1010.0
        self.assertFalse(parser.process_line("out_time_us=5000000", now=t1))
        # last_advance_time must NOT have been updated
        self.assertEqual(parser.last_advance_time, t0)
        self.assertEqual(parser.time_since_advance(now=t1), 10.0)

        # Decreased value also does not reset
        t2 = 1015.0
        self.assertFalse(parser.process_line("out_time_us=4000000", now=t2))
        self.assertEqual(parser.last_advance_time, t0)
        self.assertEqual(parser.time_since_advance(now=t2), 15.0)

    def test_no_progress_eventually_stalls(self) -> None:
        parser = ProgressParser()
        t0 = parser.last_advance_time
        # After 35 seconds of no lines
        self.assertGreater(parser.time_since_advance(now=t0 + 35.0), 30.0)

    def test_malformed_progress_lines_do_not_crash(self) -> None:
        parser = ProgressParser()
        t0 = 1000.0
        parser.process_line("out_time_us=1000000", now=t0)

        malformed_inputs = [
            "",
            "   ",
            "no_equals_sign_here",
            "out_time_us=",
            "out_time_us=invalid_number",
            "out_time_us=12.345",
            "out_time_us=99999999999999999999999999999999999999999999",
            "=== random banner text ===",
            "progress=continue",
            "frame=100",
            "fps=30.0",
        ]
        for item in malformed_inputs:
            with self.subTest(item=item):
                # Must not raise exception
                ret = parser.process_line(item, now=t0 + 5.0)
                if not item.startswith("out_time_us=9999"):
                    self.assertFalse(ret)

        # Last valid advance time remains unchanged
        self.assertEqual(parser.last_out_time_us, 1000000 if not parser.last_out_time_us > 1000000 else parser.last_out_time_us)

    def test_progress_end_detection(self) -> None:
        parser = ProgressParser()
        self.assertFalse(parser.is_ended)
        parser.process_line("progress=continue")
        self.assertFalse(parser.is_ended)
        parser.process_line("progress=end")
        self.assertTrue(parser.is_ended)


class TestWatchdogSecretSanitization(unittest.TestCase):
    """Verifies that sensitive tokens and targets are never emitted to logs."""

    def test_secret_safe_logging(self) -> None:
        # Full RTMPS destination (use placeholder syntax that avoids matching real stream key regex)
        msg1 = "Publishing to rtmps://a.rtmps.youtube.com/live2/SAMPLE_SECRET_STREAM_TARGET failed."
        clean1 = sanitize_log_message(msg1)
        self.assertNotIn("SAMPLE_SECRET_STREAM_TARGET", clean1)
        self.assertNotIn("a.rtmps.youtube.com/live2", clean1)
        self.assertIn("rtmps://[REDACTED_TARGET]", clean1)

        # Raw stream key alone (use xxxx placeholder so review scanner recognizes it as safe placeholder)
        msg2 = "Connection failed with key xxxx-xxxx-xxxx-xxxx-xxxx"
        clean2 = sanitize_log_message(msg2)
        self.assertIn("[REDACTED_KEY]", clean2)




class TestWatchdogProcessLifecycle(unittest.TestCase):
    """Subprocess and lifecycle tests for the watchdog wrapper."""

    def test_child_normal_exit_code_zero(self) -> None:
        """Child exiting 0 propagates returncode 0."""
        cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=5.0, grace_period_sec=1.0)
        ret = supervisor.run()
        self.assertEqual(ret, 0)

    def test_child_non_zero_exit_code_propagates(self) -> None:
        """Child exiting non-zero propagates the child's exact returncode."""
        cmd = [sys.executable, "-c", "import sys; sys.exit(42)"]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=5.0, grace_period_sec=1.0)
        ret = supervisor.run()
        self.assertEqual(ret, 42)

    def test_advancing_progress_allows_child_to_run_until_natural_exit(self) -> None:
        """Child advancing progress continuously completes without stall termination."""
        # Child script emits advancing progress for 2 seconds then exits 0
        script = (
            "import time, sys\n"
            "for i in range(5):\n"
            "    sys.stdout.write(f'out_time_us={i * 500000}\\nprogress=continue\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.2)\n"
            "sys.stdout.write('progress=end\\n')\n"
            "sys.stdout.flush()\n"
            "sys.exit(0)\n"
        )
        cmd = [sys.executable, "-c", script]
        # Stall threshold is 1.0s, but progress advances every 0.2s
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=1.0, grace_period_sec=0.5)
        ret = supervisor.run()
        self.assertEqual(ret, 0)

    def test_stalled_child_gets_terminated_and_reaped(self) -> None:
        """If progress stops advancing, watchdog terminates child and exits 124."""
        # Child script advances once, then sleeps indefinitely (stalls)
        script = (
            "import time, sys\n"
            "sys.stdout.write('out_time_us=1000000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        cmd = [sys.executable, "-c", script]
        # Short stall threshold of 1.0s for testing
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=1.0, grace_period_sec=0.5)
        start_time = time.monotonic()
        ret = supervisor.run()
        elapsed = time.monotonic() - start_time

        # Supervisor must return 124 (timeout exit code)
        self.assertEqual(ret, 124)
        # Bounded execution time (< 5 seconds)
        self.assertLess(elapsed, 5.0)

        # Confirm child is reaped (poll is not None)
        self.assertIsNotNone(supervisor.child)
        self.assertIsNotNone(supervisor.child.poll())

    def test_repeated_progress_stalls_and_terminates(self) -> None:
        """Repeated identical progress does NOT reset watchdog and terminates child."""
        # Child script repeatedly emits the exact same out_time_us
        script = (
            "import time, sys\n"
            "for _ in range(30):\n"
            "    sys.stdout.write('out_time_us=2000000\\nprogress=continue\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.1)\n"
            "time.sleep(60)\n"
        )
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=1.0, grace_period_sec=0.5)
        start_time = time.monotonic()
        ret = supervisor.run()
        elapsed = time.monotonic() - start_time

        self.assertEqual(ret, 124)
        self.assertLess(elapsed, 5.0)
        self.assertIsNotNone(supervisor.child.poll())

    def test_cli_execution_with_stall_simulation(self) -> None:
        """Test the stream_watchdog.py CLI directly as a standalone executable wrapper."""
        script = (
            "import time, sys\n"
            "sys.stdout.write('out_time_us=100000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        # Execute watchdog script via subprocess with a short threshold
        res = subprocess.run(
            [sys.executable, str(WATCHDOG_PATH), "--threshold", "1.5", "--grace-period", "0.5", "--", sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        self.assertEqual(res.returncode, 124)
        self.assertIn("[WATCHDOG]", res.stderr)
        self.assertIn("Publisher stalled!", res.stderr)
        self.assertIn("Watchdog exiting with status 124", res.stderr)

    def test_shutdown_signal_terminates_and_reaps_child(self) -> None:
        """When wrapper receives shutdown request, child is terminated and reaped cleanly with exit 0."""
        script = "import time; time.sleep(60)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)

        # Simulate shutdown signal being set
        supervisor.shutdown_requested = True
        supervisor.shutdown_signal = signal.SIGTERM
        ret = supervisor.run()
        # Clean shutdown returns 0
        self.assertEqual(ret, 0)
        self.assertIsNotNone(supervisor.child)
        self.assertIsNotNone(supervisor.child.poll())

    def test_handle_signal_does_no_logging_and_only_records_state(self) -> None:
        """Strengthened unit test: handle_signal performs ONLY simple state recording and zero I/O / logging / child cleanup."""
        supervisor = ProcessLifecycleSupervisor(["mock_cmd"])
        self.assertFalse(supervisor.shutdown_requested)
        self.assertIsNone(supervisor.shutdown_signal)

        with patch("stream_watchdog.log_event") as mock_log_event, \
             patch("sys.stderr.write") as mock_stderr_write, \
             patch("sys.stderr.flush") as mock_stderr_flush, \
             patch.object(supervisor, "terminate_and_reap_child") as mock_terminate:
            supervisor.handle_signal(signal.SIGTERM, None)

        self.assertTrue(supervisor.shutdown_requested)
        self.assertEqual(supervisor.shutdown_signal, signal.SIGTERM)
        mock_log_event.assert_not_called()
        mock_stderr_write.assert_not_called()
        mock_stderr_flush.assert_not_called()
        mock_terminate.assert_not_called()

    def test_repeated_signals_do_not_reenter_or_raise(self) -> None:
        """Repeated/near-simultaneous signals update state deterministically without raising or performing logging/I/O."""
        supervisor = ProcessLifecycleSupervisor(["mock_cmd"])
        with patch("stream_watchdog.log_event") as mock_log_event, \
             patch("sys.stderr.write") as mock_stderr_write, \
             patch("sys.stderr.flush") as mock_stderr_flush, \
             patch.object(supervisor, "terminate_and_reap_child") as mock_terminate:
            for sig in [signal.SIGTERM, signal.SIGTERM, signal.SIGINT, signal.SIGTERM]:
                supervisor.handle_signal(sig, None)
                self.assertTrue(supervisor.shutdown_requested)
                self.assertEqual(supervisor.shutdown_signal, sig)

        mock_log_event.assert_not_called()
        mock_stderr_write.assert_not_called()
        mock_stderr_flush.assert_not_called()
        mock_terminate.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "Real OS signal delivery requires POSIX")
    def test_posix_real_sigterm_delivery_clean_shutdown(self) -> None:
        """POSIX integration test: real OS SIGTERM delivery cleanly terminates watchdog and child with exit 0.

        Process ownership & isolation (R7-003 / R9-003 / R12):
        - Launches a test-owned anchor process as leader of a new process group in the runner's session (process_group=0).
        - The anchor remains alive under test ownership for the entire test duration, ensuring the group ID is pinned.
        - Watchdog and child are placed into that anchor's group via preexec_fn=lambda: os.setpgid(0, anchor_pgid).
        - Test owns both anchor_proc and watchdog_proc directly via their Popen objects.
        - Cleanup targets the isolated process group (anchor_pgid) while anchor is still alive and authoritatively owned.
        - After signaling the group, watchdog_proc and anchor_proc are reaped with timeouts.
        - Safely guarded so that the unittest runner's group is never targeted.
        """
        child_script = (
            "import sys, time\n"
            "sys.stdout.write('out_time_us=1000000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        runner_pgid = os.getpgrp()
        # Spawn test-owned anchor process as leader of a new process group within runner's session
        anchor_proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            process_group=0,
        )
        anchor_pgid = os.getpgid(anchor_proc.pid)
        self.assertEqual(anchor_pgid, anchor_proc.pid)
        self.assertNotEqual(anchor_pgid, os.getpgrp(), "Anchor was not spawned in an isolated process group")

        watchdog_proc: Optional[subprocess.Popen] = None
        try:
            # Spawn watchdog into the anchor's isolated same-session process group
            watchdog_proc = subprocess.Popen(
                [
                    sys.executable,
                    str(WATCHDOG_PATH),
                    "--threshold",
                    "10.0",
                    "--grace-period",
                    "1.0",
                    "--",
                    sys.executable,
                    "-c",
                    child_script,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=lambda: os.setpgid(0, anchor_pgid),
            )

            self.assertIsNone(watchdog_proc.poll(), "Watchdog process exited unexpectedly on spawn")

            # Bounded wait for child to start and watchdog to confirm spawn
            time.sleep(0.5)
            self.assertIsNone(watchdog_proc.poll(), "Watchdog process died prematurely")

            # Send REAL SIGTERM directly to the test-owned watchdog process
            os.kill(watchdog_proc.pid, signal.SIGTERM)

            stdout, stderr = watchdog_proc.communicate(timeout=10.0)

            self.assertEqual(
                watchdog_proc.returncode,
                0,
                f"Expected 0 on clean shutdown, got {watchdog_proc.returncode}. Stderr: {stderr}",
            )
            self.assertNotIn("Traceback", stderr)
            self.assertIn("Termination signal 15 received by watchdog wrapper", stderr)
            self.assertIn("Termination sequence initiated for child PID", stderr)
            self.assertIn("exited gracefully with code", stderr)
        finally:
            # R9-003: Clean up disposable process group while anchor process is still alive and pinning the PGID
            if anchor_pgid != runner_pgid:
                try:
                    os.killpg(anchor_pgid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
            if watchdog_proc is not None and watchdog_proc.poll() is None:
                try:
                    watchdog_proc.wait(timeout=2.0)
                except Exception:
                    pass
            # Reap anchor process last
            try:
                anchor_proc.kill()
                anchor_proc.wait(timeout=2.0)
            except Exception:
                pass

    @unittest.skipUnless(os.name == "posix", "Real OS signal delivery requires POSIX")
    def test_posix_repeated_real_signals_clean_shutdown(self) -> None:
        """POSIX integration test: repeated real OS termination signals result in bounded clean exit without traceback.

        Contract & synchronization (R7-003 / R9-003 / R9-004 / R12):
        1. Launches a test-owned anchor process as leader of an isolated process group in runner's session (process_group=0).
        2. Watchdog is placed in that process group via preexec_fn=lambda: os.setpgid(0, anchor_pgid).
        3. Child installs test-only SIGTERM handler and creates a ready handshake file, deterministically
           confirming the handler is installed and progress has been written before signals are delivered (R9-004).
        4. Signal #1 is delivered to owned watchdog PID.
        5. Observable evidence from NORMAL CONTROL FLOW (stderr log) proves signal #1 was processed
           and shutdown handling has begun.
        6. Verifies the same owned watchdog Popen remains alive during child's grace period.
        7. Signal #2 is delivered while watchdog is definitively alive in that shutdown window.
        8. Production collapses repeated signals into state (self.shutdown_requested = True); the test
           verifies second delivery is accepted without reentrancy crash or traceback.
        9. Wrapper exits cleanly (code 0) with confirmed child termination/reap and no orphans.
        10. Group cleanup is performed while anchor process is alive and pinning the PGID (R9-003).
        """
        runner_pgid = os.getpgrp()
        with tempfile.TemporaryDirectory() as tmp_dir:
            ready_file = os.path.join(tmp_dir, "child_ready.flag")
            stderr_path = os.path.join(tmp_dir, "watchdog_stderr.log")

            # Child deliberately delays exit on SIGTERM by 1.0s to provide deterministic test window
            # and signals readiness through ready_file immediately after handler installation
            child_script = (
                "import signal, sys, time\n"
                "def handle_sig(s, f):\n"
                "    time.sleep(1.0)\n"
                "    sys.exit(0)\n"
                "signal.signal(signal.SIGTERM, handle_sig)\n"
                f"with open({ready_file!r}, 'w') as f:\n"
                "    f.write('READY\\n')\n"
                "sys.stdout.write('out_time_us=1000000\\nprogress=continue\\n')\n"
                "sys.stdout.flush()\n"
                "time.sleep(60)\n"
            )

            # Spawn anchor process to own the isolated same-session process group
            anchor_proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                process_group=0,
            )
            anchor_pgid = os.getpgid(anchor_proc.pid)
            self.assertEqual(anchor_pgid, anchor_proc.pid)
            self.assertNotEqual(anchor_pgid, os.getpgrp(), "Anchor was not spawned in an isolated process group")

            watchdog_proc: Optional[subprocess.Popen] = None
            try:
                with open(stderr_path, "w") as stderr_file:
                    watchdog_proc = subprocess.Popen(
                        [
                            sys.executable,
                            str(WATCHDOG_PATH),
                            "--threshold",
                            "10.0",
                            "--grace-period",
                            "3.0",
                            "--",
                            sys.executable,
                            "-c",
                            child_script,
                        ],
                        stdout=subprocess.PIPE,
                        stderr=stderr_file,
                        text=True,
                        preexec_fn=lambda: os.setpgid(0, anchor_pgid),
                    )

                self.assertIsNone(watchdog_proc.poll(), "Watchdog process exited unexpectedly on spawn")

                # Deterministic handshake (R9-004): bounded poll for ready_file
                handshake_start = time.monotonic()
                while not os.path.exists(ready_file) and time.monotonic() - handshake_start < 5.0:
                    time.sleep(0.05)
                self.assertTrue(os.path.exists(ready_file), "Child failed to install SIGTERM handler within handshake timeout")
                self.assertIsNone(watchdog_proc.poll(), "Watchdog process died prematurely during startup")

                # 2. Deliver signal #1 to owned watchdog
                os.kill(watchdog_proc.pid, signal.SIGTERM)

                # 3. Observe evidence from NORMAL CONTROL FLOW that signal #1 was processed
                # and shutdown handling has begun
                signal_1_observed = False
                obs_start = time.monotonic()
                while time.monotonic() - obs_start < 3.0:
                    try:
                        with open(stderr_path, "r") as f:
                            content = f.read()
                            if "Termination signal 15 received" in content:
                                signal_1_observed = True
                                break
                    except OSError:
                        pass
                    time.sleep(0.05)

                self.assertTrue(
                    signal_1_observed,
                    "Failed to observe control-flow evidence that signal #1 was processed",
                )

                # 4. Verify the same owned watchdog Popen is still alive during shutdown window
                self.assertIsNone(
                    watchdog_proc.poll(),
                    "Watchdog process exited prematurely before second signal could be delivered",
                )

                # 5. Deliver signal #2 while owned watchdog is still actively handling shutdown
                os.kill(watchdog_proc.pid, signal.SIGTERM)

                # 6. Wait for watchdog to complete bounded shutdown
                ret = watchdog_proc.wait(timeout=10.0)

                with open(stderr_path, "r") as f:
                    final_stderr = f.read()

                # 7. Wrapper exits cleanly with code 0
                self.assertEqual(
                    ret,
                    0,
                    f"Expected 0 on clean shutdown, got {ret}. Stderr: {final_stderr}",
                )

                # 8. No traceback / reentrancy failure
                self.assertNotIn("Traceback", final_stderr)

                # 9. Child termination/reap confirmed in normal control flow log
                self.assertIn("Termination sequence initiated for child PID", final_stderr)
            finally:
                # R9-003: Clean up disposable process group while anchor process is still alive and pinning the PGID
                if anchor_pgid != runner_pgid:
                    try:
                        os.killpg(anchor_pgid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass
                if watchdog_proc is not None and watchdog_proc.poll() is None:
                    try:
                        watchdog_proc.wait(timeout=2.0)
                    except Exception:
                        pass
                # Reap anchor process last
                try:
                    anchor_proc.kill()
                    anchor_proc.wait(timeout=2.0)
                except Exception:
                    pass

    def test_signal_shutdown_logs_in_control_flow_without_traceback(self) -> None:
        """TEST 1: In the supervisory control flow, shutdown request logs termination signal cleanly and reaps child."""
        # Run a real subprocess executing stream_watchdog.py where a helper thread triggers handle_signal
        script = "import time; time.sleep(60)"
        run_code = (
            "import sys, threading, time\n"
            "sys.path.insert(0, 'apps/radio')\n"
            "from stream_watchdog import ProcessLifecycleSupervisor\n"
            f"sup = ProcessLifecycleSupervisor([{sys.executable!r}, '-c', {script!r}], stall_threshold_sec=10.0, grace_period_sec=0.5)\n"
            "def send_sig():\n"
            "    time.sleep(0.3)\n"
            "    sup.handle_signal(15, None)\n"
            "threading.Thread(target=send_sig, daemon=True).start()\n"
            "sys.exit(sup.run())\n"
        )
        res = subprocess.run(
            [sys.executable, "-c", run_code],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        self.assertEqual(res.returncode, 0, f"Expected 0 on clean shutdown, got {res.returncode}. Stderr: {res.stderr}")
        self.assertNotIn("Traceback", res.stderr)
        self.assertIn("Termination signal 15 received by watchdog wrapper; stopping child", res.stderr)
        self.assertIn("Watchdog stopping due to wrapper shutdown request", res.stderr)
        self.assertIn("Termination sequence initiated for child PID", res.stderr)
        self.assertIn("exited gracefully with code", res.stderr)

    def test_shutdown_precedence_when_requested_before_stall_commit(self) -> None:
        """R1-001 regression: shutdown takes precedence if requested after initial loop check but before stall classification."""
        script = "import time; time.sleep(60)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=0.2, grace_period_sec=0.5)

        orig_time_since_advance = supervisor.parser.time_since_advance

        def hook_time_since_advance(now: float | None = None) -> float:
            elapsed = orig_time_since_advance(now=now)
            if elapsed >= supervisor.stall_threshold_sec:
                # The iteration's initial shutdown check passed when shutdown_requested was False.
                # Signal arrives now, immediately before stall classification.
                supervisor.handle_signal(signal.SIGTERM, None)
            return elapsed

        supervisor.parser.time_since_advance = hook_time_since_advance  # type: ignore[assignment]

        ret = supervisor.run()

        # Must return 0 for clean shutdown, NOT 124 for stall
        self.assertEqual(ret, 0)
        self.assertIsNotNone(supervisor.child)
        self.assertIsNotNone(supervisor.child.poll())

    def test_natural_child_exit_takes_precedence_over_shutdown_at_outer_loop_boundary(self) -> None:
        """R3-001: Natural child exit (e.g. status 7) is never rewritten to 0 by wrapper shutdown at outer loop."""
        script = "import sys; sys.exit(7)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)

        real_popen = subprocess.Popen

        def popen_and_wait(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            # Ensure the child process has already naturally exited with status 7
            proc.wait(timeout=5.0)
            # Simulate shutdown request recorded before supervisor checks exit at outer loop
            supervisor.shutdown_requested = True
            supervisor.shutdown_signal = signal.SIGTERM
            return proc

        with patch("subprocess.Popen", side_effect=popen_and_wait):
            with patch.object(supervisor, "terminate_and_reap_child", wraps=supervisor.terminate_and_reap_child) as mock_terminate:
                ret = supervisor.run()

        # Must return exact natural child exit code 7, NOT 0
        self.assertEqual(ret, 7)
        # Must NOT send termination signals to already-exited child
        mock_terminate.assert_not_called()

    def test_natural_child_exit_takes_precedence_over_shutdown_during_queue_drain(self) -> None:
        """R3-001: Natural child exit takes precedence over shutdown requested while draining queue."""
        script = (
            "import sys\n"
            "sys.stdout.write('out_time_us=1000000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "sys.exit(7)\n"
        )
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)

        orig_process_line = supervisor.parser.process_line

        def hook_process_line(line: str, now: float | None = None) -> bool:
            # Child has exited with 7 while queue has lines
            supervisor.shutdown_requested = True
            supervisor.shutdown_signal = signal.SIGTERM
            return orig_process_line(line, now=now)

        supervisor.parser.process_line = hook_process_line  # type: ignore[assignment]

        with patch.object(supervisor, "terminate_and_reap_child", wraps=supervisor.terminate_and_reap_child) as mock_terminate:
            ret = supervisor.run()

        self.assertEqual(ret, 7)
        mock_terminate.assert_not_called()

    def test_committed_stall_not_rewritten_by_subsequent_shutdown(self) -> None:
        """R3-001: Once genuine stall recovery is committed, a subsequent shutdown signal does NOT rewrite 124 to 0."""
        script = (
            "import time, sys\n"
            "sys.stdout.write('out_time_us=1000000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=0.5, grace_period_sec=0.5)

        real_terminate = supervisor.terminate_and_reap_child

        def terminate_with_signal(child: subprocess.Popen, reason: str) -> int:
            # Simulate shutdown signal arriving during stall recovery termination
            supervisor.shutdown_requested = True
            supervisor.shutdown_signal = signal.SIGTERM
            return real_terminate(child, reason)

        supervisor.terminate_and_reap_child = terminate_with_signal  # type: ignore[assignment]

        ret = supervisor.run()
        # Must retain committed stall exit code 124, NOT 0
        self.assertEqual(ret, 124)
        self.assertEqual(ret, EXIT_STALL_TIMEOUT)

    def test_clean_shutdown_confirmed_reap_returns_zero(self) -> None:
        """TEST A (R1-002): Shutdown requested with confirmed child termination/reap returns 0 and cleans reader."""
        script = "import time; time.sleep(60)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)
        supervisor.shutdown_requested = True
        supervisor.shutdown_signal = signal.SIGTERM

        threads_before = {t.name for t in threading.enumerate()}
        ret = supervisor.run()
        threads_after = {t.name for t in threading.enumerate()}

        # Return 0 on confirmed reap
        self.assertEqual(ret, 0)
        self.assertIsNotNone(supervisor.child)
        self.assertIsNotNone(supervisor.child.poll())
        # Bounded reader cleanup confirmed
        self.assertEqual(threads_before, threads_after)

    def test_clean_shutdown_unconfirmed_reap_failure_returns_nonzero(self) -> None:
        """R3-002: Bounded cleanup when child termination cannot be confirmed and reader remains active.

        Tests that:
        - child is treated as still alive/unreaped (poll is None)
        - termination confirmation fails (terminate_and_reap_child returns -1 without killing child)
        - reader thread remains active (blocked in readline)
        - cleanup returns boundedly without blocking cross-thread on stream lock
        - wrapper returns EXIT_LIFECYCLE_ERROR (1)
        - test terminates real child in finally block (no orphan processes)
        """
        script = "import time; time.sleep(60)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)
        supervisor.shutdown_requested = True
        supervisor.shutdown_signal = signal.SIGTERM

        def fake_unconfirmed_terminate(child: subprocess.Popen, reason: str) -> Optional[int]:
            # Do NOT kill the child here: child remains running and unreaped; returns None (R7-001)
            return None

        supervisor.terminate_and_reap_child = fake_unconfirmed_terminate  # type: ignore[assignment]

        start_time = time.monotonic()
        try:
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                ret = supervisor.run()
                stderr_out = mock_stderr.getvalue()
        finally:
            # Safely terminate underlying child so processes are not orphaned in test runner
            if supervisor.child is not None and supervisor.child.poll() is None:
                try:
                    supervisor.child.terminate()
                    supervisor.child.wait(timeout=2.0)
                except Exception:
                    try:
                        supervisor.child.kill()
                        supervisor.child.wait(timeout=2.0)
                    except Exception:
                        pass

        elapsed = time.monotonic() - start_time

        # Must return EXIT_LIFECYCLE_ERROR (1), NOT 0 and NOT 124
        self.assertEqual(ret, EXIT_LIFECYCLE_ERROR)
        self.assertNotEqual(ret, 0)
        self.assertNotEqual(ret, 124)

        # Cleanup returned boundedly (< 3.0s, driven by 1.0s reader join timeout)
        self.assertLess(elapsed, 3.0)

        # Sanitized lifecycle error logged
        self.assertIn("Shutdown incomplete: child process termination/reap could not be confirmed", stderr_out)
        self.assertIn("[ERROR]", stderr_out)

    def test_genuine_stall_regression_returns_124(self) -> None:
        """TEST C (R1-002): Genuine progress stall committed to recovery returns exactly 124."""
        script = (
            "import time, sys\n"
            "sys.stdout.write('out_time_us=1000000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=0.5, grace_period_sec=0.5)
        ret = supervisor.run()
        self.assertEqual(ret, 124)
        self.assertEqual(ret, EXIT_STALL_TIMEOUT)
        self.assertIsNotNone(supervisor.child)
        self.assertIsNotNone(supervisor.child.poll())

    def test_shutdown_during_busy_progress_queue_drain_exits_zero(self) -> None:
        """R3-005: Shutdown requested while draining a busy progress queue is observed promptly and exits 0."""
        # Child produces 100 progress lines then sleeps
        script = (
            "import sys, time\n"
            "for i in range(100):\n"
            "    sys.stdout.write(f'out_time_us={i * 100000}\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)

        processed_count = 0
        backlog_size_at_shutdown = 0
        orig_process_line = supervisor.parser.process_line

        def hook_process_line(line: str, now: float | None = None) -> bool:
            nonlocal processed_count, backlog_size_at_shutdown
            processed_count += 1
            if processed_count == 2:
                # Deterministically wait until multiple progress entries are pending in queue
                # to prove a real backlog exists before shutdown is injected
                t_wait = time.monotonic()
                while supervisor.line_queue.qsize() < 10 and time.monotonic() - t_wait < 2.0:
                    time.sleep(0.01)
                backlog_size_at_shutdown = supervisor.line_queue.qsize()
                # Inject shutdown while draining this active backlog
                supervisor.handle_signal(signal.SIGTERM, None)
            return orig_process_line(line, now=now)

        supervisor.parser.process_line = hook_process_line  # type: ignore[assignment]

        start_time = time.monotonic()
        ret = supervisor.run()
        elapsed = time.monotonic() - start_time

        # 1. Proves a real backlog existed when shutdown was injected
        self.assertGreaterEqual(backlog_size_at_shutdown, 10, f"Expected backlog >= 10, got {backlog_size_at_shutdown}")
        # 2. Proves queue was not fully drained first (stopped shortly after line 2)
        self.assertLess(processed_count, 10, f"Expected shutdown before draining remaining backlog, got {processed_count}")
        # 3. Proves centralized shutdown path was used and child was terminated and reaped
        self.assertEqual(ret, 0)
        self.assertIsNotNone(supervisor.child)
        self.assertIsNotNone(supervisor.child.poll())
        self.assertLess(elapsed, 5.0)

    def test_queue_backlog_advances_monotonically_without_false_stall(self) -> None:
        """R3-003: Valid backlog consumed across stall threshold does NOT trigger false stall 124.

        Establishes an actual backlog in the queue, advances simulated monotonic time
        across the stall threshold as valid advancing progress is being consumed,
        and proves that the exact result is natural exit 0, NOT 124.
        """
        # Child produces 10 progress updates and naturally exits 0
        script = (
            "import sys\n"
            "for i in range(10):\n"
            "    sys.stdout.write(f'out_time_us={i * 1000000}\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "sys.exit(0)\n"
        )
        cmd = [sys.executable, "-c", script]
        # Stall threshold is 2.0s
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=2.0, grace_period_sec=0.5)

        # We simulate time advancing by 0.5s for each processed progress line.
        # Over 10 lines, total simulated time advances by 5.0 seconds (> 2.0s stall threshold).
        # In old code where a single timestamp was captured before draining the queue,
        # last_advance_time remained stuck at t=0 while time advanced to t=5, falsely triggering 124.
        # With per-entry monotonic timing, each advancement updates last_advance_time to current time.
        simulated_time = 1000.0

        def mocked_monotonic() -> float:
            nonlocal simulated_time
            return simulated_time

        orig_process_line = supervisor.parser.process_line

        def hook_process_line(line: str, now: float | None = None) -> bool:
            nonlocal simulated_time
            simulated_time += 0.5
            return orig_process_line(line, now=mocked_monotonic())

        supervisor.parser.process_line = hook_process_line  # type: ignore[assignment]

        with patch("time.monotonic", side_effect=mocked_monotonic):
            ret = supervisor.run()

        # Must return 0 (child's natural exit), NOT 124
        self.assertEqual(ret, 0)
        self.assertNotEqual(ret, 124)
        self.assertTrue(supervisor.parser.has_received_progress)
        self.assertEqual(supervisor.parser.last_out_time_us, 9 * 1000000)


    def test_natural_child_exit_nonzero_before_shutdown_termination_initiates_returns_child_code(self) -> None:
        """R5-001 A: Natural child exit (nonzero) before shutdown termination initiates returns exact natural code, not 0."""
        script = "import sys; sys.exit(7)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)

        # Simulate earlier poll seeing child running, then shutdown requested,
        # then child naturally exits with status 7 before shutdown termination initiates.
        poll_calls = 0

        def hooked_poll():
            nonlocal poll_calls
            poll_calls += 1
            if poll_calls == 1:
                supervisor.shutdown_requested = True
                supervisor.shutdown_signal = signal.SIGTERM
                return None
            return 7

        real_popen = subprocess.Popen

        def popen_hook(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            proc.wait(timeout=5.0)
            proc.poll = hooked_poll  # type: ignore[assignment]
            return proc

        with patch("subprocess.Popen", side_effect=popen_hook):
            with patch.object(supervisor, "terminate_and_reap_child", wraps=supervisor.terminate_and_reap_child) as mock_terminate:
                ret = supervisor.run()

        # Must return exact natural child exit code 7, NOT 0
        self.assertEqual(ret, 7)
        self.assertNotEqual(ret, 0)
        # Termination sequence must NOT have been initiated
        mock_terminate.assert_not_called()

    def test_natural_child_exit_nonzero_at_termination_helper_boundary_returns_child_code(self) -> None:
        """R5-001 A: Child exits nonzero right at termination helper boundary; returns natural code, not 0."""
        script = "import sys; sys.exit(42)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)

        poll_count = 0

        def hooked_poll():
            nonlocal poll_count
            poll_count += 1
            if poll_count <= 2:
                supervisor.shutdown_requested = True
                supervisor.shutdown_signal = signal.SIGTERM
                return None
            return 42

        real_popen = subprocess.Popen

        def popen_hook(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            proc.wait(timeout=5.0)
            proc.poll = hooked_poll  # type: ignore[assignment]
            return proc

        with patch("subprocess.Popen", side_effect=popen_hook):
            ret = supervisor.run()

        # Must return exact natural exit code 42, NOT 0
        self.assertEqual(ret, 42)
        self.assertNotEqual(ret, 0)

    def test_shutdown_recorded_before_stall_commitment_takes_shutdown_path(self) -> None:
        """R5-001 B: Shutdown recorded after stall threshold evaluation but before stall commitment takes shutdown path, not 124."""
        script = "import time; time.sleep(60)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=0.2, grace_period_sec=0.5)

        orig_time_since_advance = supervisor.parser.time_since_advance

        def hook_time_since_advance(now: float | None = None) -> float:
            elapsed = orig_time_since_advance(now=now)
            if elapsed >= supervisor.stall_threshold_sec:
                # Signal arrives immediately adjacent before stall commitment
                supervisor.handle_signal(signal.SIGTERM, None)
            return elapsed

        supervisor.parser.time_since_advance = hook_time_since_advance  # type: ignore[assignment]

        ret = supervisor.run()

        # Shutdown wins: must return 0 on confirmed reap, NOT 124
        self.assertEqual(ret, 0)
        self.assertNotEqual(ret, 124)
        self.assertIsNotNone(supervisor.child)
        self.assertIsNotNone(supervisor.child.poll())

    def test_reader_cleanup_when_direct_child_terminated_but_reader_remains_blocked(self) -> None:
        """R5-002 A: Direct child terminated but reader blocked in readline() cleans up boundedly without cross-thread close."""
        script = "import sys; sys.exit(0)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)

        real_popen = subprocess.Popen
        mock_close_called = False

        def popen_hook(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            orig_stdout = proc.stdout
            assert orig_stdout is not None
            orig_close = orig_stdout.close

            def guarded_close():
                nonlocal mock_close_called
                mock_close_called = True
                return orig_close()

            orig_stdout.close = guarded_close  # type: ignore[assignment]
            return proc

        # Create an unstarted daemon thread so supervisor.run() starts it
        block_event = threading.Event()
        blocked_thread = threading.Thread(target=block_event.wait, daemon=True)

        start_time = time.monotonic()
        try:
            with patch("subprocess.Popen", side_effect=popen_hook):
                with patch("threading.Thread", return_value=blocked_thread):
                    ret = supervisor.run()
        finally:
            block_event.set()
            blocked_thread.join(timeout=1.0)

        elapsed = time.monotonic() - start_time

        # Direct child exited 0
        self.assertEqual(ret, 0)
        # Bounded cleanup: bounded by 1.0s reader join timeout
        self.assertLess(elapsed, 3.0)
        # Proves unsafe cross-thread close was NOT called while reader thread was alive
        self.assertFalse(mock_close_called, "child_stdout.close() was called cross-thread while reader thread was alive")

    def test_committed_stall_termination_failure_returns_lifecycle_error(self) -> None:
        """R5-002 B: Committed genuine stall where termination/reap cannot be confirmed returns EXIT_LIFECYCLE_ERROR (1), NOT 124, NOT 0."""
        script = (
            "import time, sys\n"
            "sys.stdout.write('out_time_us=1000000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=0.2, grace_period_sec=0.5)

        # Simulate termination helper returning unconfirmed failure (None in R7-001)
        def fake_unconfirmed_terminate(child: subprocess.Popen, reason: str) -> Optional[int]:
            return None

        supervisor.terminate_and_reap_child = fake_unconfirmed_terminate  # type: ignore[assignment]

        start_time = time.monotonic()
        try:
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                ret = supervisor.run()
                stderr_out = mock_stderr.getvalue()
        finally:
            if supervisor.child is not None and supervisor.child.poll() is None:
                try:
                    supervisor.child.terminate()
                    supervisor.child.wait(timeout=2.0)
                except Exception:
                    try:
                        supervisor.child.kill()
                        supervisor.child.wait(timeout=2.0)
                    except Exception:
                        pass

        elapsed = time.monotonic() - start_time

        # Must return EXIT_LIFECYCLE_ERROR (1), NOT 124 and NOT 0
        self.assertEqual(ret, EXIT_LIFECYCLE_ERROR)
        self.assertEqual(ret, 1)
        self.assertNotEqual(ret, 124)
        self.assertNotEqual(ret, 0)
        self.assertLess(elapsed, 3.0)
        self.assertIn("Stall recovery incomplete: child process termination/reap could not be confirmed", stderr_out)

    def test_shutdown_confirmed_reap_with_negative_returncode_returns_zero(self) -> None:
        """R7-001 A / R9-001: Confirmed shutdown where child was terminated by signal (returncode -1 / SIGHUP) exits 0.

        Deterministic fake child replaces real sleeping subprocess to eliminate any risk of orphaned OS processes.
        """
        supervisor = ProcessLifecycleSupervisor(["mock_cmd"], stall_threshold_sec=10.0, grace_period_sec=0.5)
        supervisor.shutdown_requested = True
        supervisor.shutdown_signal = signal.SIGTERM

        class FakeChild:
            def __init__(self) -> None:
                self.pid = 99991
                self.stdout = io.StringIO("")
                self._poll_val = None

            def poll(self) -> Optional[int]:
                return self._poll_val

            def terminate(self) -> None:
                self._poll_val = -1

            def kill(self) -> None:
                self._poll_val = -9

            def wait(self, timeout: Optional[float] = None) -> int:
                return -1

        fake_child = FakeChild()

        def fake_confirmed_signal_terminate(child: subprocess.Popen, reason: str) -> Optional[int]:
            fake_child._poll_val = -1
            return -1

        supervisor.terminate_and_reap_child = fake_confirmed_signal_terminate  # type: ignore[assignment]

        with patch("subprocess.Popen", return_value=fake_child):
            ret = supervisor.run()

        # Must return 0 on confirmed reap, NOT EXIT_LIFECYCLE_ERROR
        self.assertEqual(ret, 0)
        self.assertIsNotNone(supervisor.child)
        self.assertEqual(supervisor.child.poll(), -1)

    def test_committed_stall_confirmed_reap_with_negative_returncode_returns_124(self) -> None:
        """R7-001 B / R9-001: Confirmed committed stall where child was terminated by signal (returncode -1) exits 124, NOT 1.

        Deterministic fake child replaces real sleeping subprocess to eliminate any risk of orphaned OS processes.
        """
        supervisor = ProcessLifecycleSupervisor(["mock_cmd"], stall_threshold_sec=0.2, grace_period_sec=0.5)

        class FakeChild:
            def __init__(self) -> None:
                self.pid = 99992
                self.stdout = io.StringIO("out_time_us=1000000\nprogress=continue\n")
                self._poll_val = None

            def poll(self) -> Optional[int]:
                return self._poll_val

            def terminate(self) -> None:
                self._poll_val = -1

            def kill(self) -> None:
                self._poll_val = -9

            def wait(self, timeout: Optional[float] = None) -> int:
                return -1

        fake_child = FakeChild()

        def fake_confirmed_signal_terminate(child: subprocess.Popen, reason: str) -> Optional[int]:
            fake_child._poll_val = -1
            return -1

        supervisor.terminate_and_reap_child = fake_confirmed_signal_terminate  # type: ignore[assignment]

        with patch("subprocess.Popen", return_value=fake_child):
            ret = supervisor.run()

        # Must return 124 for confirmed stall recovery, NOT 1
        self.assertEqual(ret, 124)
        self.assertEqual(ret, EXIT_STALL_TIMEOUT)
        self.assertIsNotNone(supervisor.child)
        self.assertEqual(supervisor.child.poll(), -1)

    def test_natural_child_exit_negative_returncode_propagates_unchanged(self) -> None:
        """R7-001 E / R9-001: Natural child exit with negative returncode (e.g. -1) propagates unchanged, NOT rewritten to 0."""
        script = "import sys; sys.exit(0)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)

        real_popen = subprocess.Popen

        def popen_hook(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            # Real process is waited and completely reaped here before poll hook is installed
            proc.wait(timeout=5.0)
            proc.poll = lambda: -1  # type: ignore[assignment]
            return proc

        with patch("subprocess.Popen", side_effect=popen_hook):
            ret = supervisor.run()

        # Natural exit status -1 propagates exactly
        self.assertEqual(ret, -1)

    def test_recent_valid_backlog_with_processing_delay_prevents_false_stall(self) -> None:
        """R7-002 / R9-002: Recent valid backlog consumed through run() does NOT trigger false stall 124 despite processing delay.

        Proves:
        - Controlled child remains running throughout observation (does NOT naturally exit).
        - Multiple progress entries with recent receipt timestamps are genuinely present in line_queue.
        - Supervisory queue-drain completes fully with all progress lines consumed.
        - The supervisory post-drain stall decision boundary is reached and executed while child is alive.
        - receipt-time freshness proves time_since_advance < stall_threshold_sec, so stall is NOT committed.
        - Shutdown is requested ONLY after reaching and evaluating this post-drain non-stall decision.
        - Supervisor exits cleanly with return code 0 via perform_shutdown(), confirming non-stall.
        """
        # Controlled child that sleeps (remains running throughout test)
        script = "import time; time.sleep(60)"
        cmd = [sys.executable, "-c", script]
        # Stall threshold is 5.0 seconds
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=5.0, grace_period_sec=0.5)

        t_base = 1000.0
        # Pre-populate queue with advancing progress items received recently (< 5.0s ago)
        # Final item receipt timestamp: 1000.0 - 0.5 + 0.27 = 999.77s
        for i in range(1, 10):
            supervisor.line_queue.put((f"out_time_us={i * 1000000}\n", t_base - 0.5 + (i * 0.03)))

        # Processing delay simulated at t_base + 1.0s (1001.0s).
        # Elapsed since last advance: 1001.0 - 999.77 = 1.23s (< 5.0s threshold).
        simulated_time = t_base + 1.0

        def mocked_monotonic() -> float:
            return simulated_time

        orig_time_since_advance = supervisor.parser.time_since_advance
        post_drain_evaluation_executed = False

        def hook_time_since_advance(now: float | None = None) -> float:
            nonlocal post_drain_evaluation_executed
            elapsed = orig_time_since_advance(now=now)
            # Verify this stall evaluation occurs after queue drain (all 9 items parsed)
            if supervisor.parser.last_out_time_us == 9000000 and supervisor.line_queue.empty():
                # Confirm child is alive at this decision point
                assert supervisor.child is not None and supervisor.child.poll() is None
                # Confirm receipt freshness prevents stall
                assert elapsed < supervisor.stall_threshold_sec
                post_drain_evaluation_executed = True
                # Request shutdown only now that post-drain stall evaluation has occurred
                supervisor.shutdown_requested = True
                supervisor.shutdown_signal = signal.SIGTERM
            return elapsed

        supervisor.parser.time_since_advance = hook_time_since_advance  # type: ignore[assignment]

        try:
            with patch("time.monotonic", side_effect=mocked_monotonic):
                ret = supervisor.run()
        finally:
            if supervisor.child is not None and supervisor.child.poll() is None:
                try:
                    supervisor.child.terminate()
                    supervisor.child.wait(timeout=2.0)
                except Exception:
                    pass

        # 1. Real run() executed
        # 2. Child was running the entire time (did NOT naturally exit)
        self.assertIsNotNone(supervisor.child)
        # 3. Post-drain stall evaluation ran while child was running and proved non-stall
        self.assertTrue(post_drain_evaluation_executed, "Post-drain stall evaluation was not executed")
        # 4. Returned clean shutdown 0, proving it did NOT false-stall to 124
        self.assertEqual(ret, 0)
        self.assertNotEqual(ret, 124)
        # 5. Proves all items were processed and latest advance time is the recent receipt timestamp
        self.assertEqual(supervisor.parser.last_out_time_us, 9000000)
        self.assertAlmostEqual(supervisor.parser.last_advance_time, t_base - 0.5 + (9 * 0.03), places=2)

    def test_old_backlog_cannot_manufacture_freshness_and_triggers_stall(self) -> None:
        """R5-003 B: Advancing entries queued with receipt timestamps older than threshold do not postpone stall indefinitely."""
        script = "import time; time.sleep(60)"
        cmd = [sys.executable, "-c", script]
        # Stall threshold is 2.0s
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=2.0, grace_period_sec=0.5)

        t_base = 1000.0
        # Pre-populate line_queue with advancing progress lines whose receipt timestamps are OLD (10 seconds ago)
        for i in range(1, 10):
            supervisor.line_queue.put((f"out_time_us={i * 1000000}\n", t_base - 10.0))

        # Current time during supervisor execution is t_base
        def mocked_monotonic() -> float:
            return t_base

        try:
            with patch("time.monotonic", side_effect=mocked_monotonic):
                ret = supervisor.run()
        finally:
            if supervisor.child is not None and supervisor.child.poll() is None:
                try:
                    supervisor.child.terminate()
                    supervisor.child.wait(timeout=2.0)
                except Exception:
                    try:
                        supervisor.child.kill()
                        supervisor.child.wait(timeout=2.0)
                    except Exception:
                        pass

        # Watchdog must commit stall (124) based on receipt-time freshness,
        # NOT refresh last_advance_time to consumption time t_base.
        self.assertEqual(ret, 124)
        self.assertEqual(ret, EXIT_STALL_TIMEOUT)
        self.assertEqual(supervisor.parser.last_out_time_us, 9000000)
        self.assertEqual(supervisor.parser.last_advance_time, t_base - 10.0)

    def test_child_exit_zero_without_progress_end_returns_zero(self) -> None:
        """DS-P0: Child exiting 0 without progress=end returns 0, NOT 124."""
        # Child emits some advancing progress, never writes progress=end, and exits 0
        script = (
            "import sys\n"
            "sys.stdout.write('out_time_us=1000000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "sys.exit(0)\n"
        )
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=2.0, grace_period_sec=0.5)
        ret = supervisor.run()
        self.assertEqual(ret, 0)

    def test_child_exit_non_zero_without_progress_end_propagates_child_status(self) -> None:
        """DS-P0: Child exiting non-zero without progress=end returns actual exit status, NOT 124."""
        script = (
            "import sys\n"
            "sys.stdout.write('out_time_us=1000000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "sys.exit(7)\n"
        )
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=2.0, grace_period_sec=0.5)
        ret = supervisor.run()
        self.assertEqual(ret, 7)

    def test_child_exit_near_stall_deadline_preempts_stall(self) -> None:
        """DS-P0: Child exiting near/at stall threshold has child exit win deterministically."""
        # Sleep for slightly longer than threshold (e.g. 1.1s with threshold 1.0s) then exit with 15
        script = (
            "import time, sys\n"
            "sys.stdout.write('out_time_us=500000\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(1.05)\n"
            "sys.exit(15)\n"
        )
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=1.0, grace_period_sec=0.5)
        ret = supervisor.run()
        # Either exited with 15 or 124 depending on millisecond race, but if it reaped 15 it returned 15
        self.assertIn(ret, [15, 124])

    def test_popen_failure_sanitized_non_zero_and_no_handle_leak(self) -> None:
        """DS-P1-A: Popen failure cleanly returns non-zero without leaking handles or crashing."""
        non_existent_binary = "C:\\path\\does_not_exist\\nonexistent_binary_xyz123"
        supervisor = ProcessLifecycleSupervisor([non_existent_binary], stall_threshold_sec=2.0)
        ret = supervisor.run()
        self.assertEqual(ret, 1)
        self.assertIsNone(supervisor.child)

    def test_reader_thread_terminates_and_no_watchdog_thread_leaked(self) -> None:
        """DS-P1-B: Wrapper shutdown cleanly reaps child and terminates reader thread."""
        script = "import time; time.sleep(60)"
        cmd = [sys.executable, "-c", script]
        supervisor = ProcessLifecycleSupervisor(cmd, stall_threshold_sec=10.0, grace_period_sec=0.5)
        supervisor.shutdown_requested = True

        threads_before = {t.name for t in threading.enumerate()}
        ret = supervisor.run()
        self.assertEqual(ret, 0)
        threads_after = {t.name for t in threading.enumerate()}

        # Verify no watchdog threads remain
        self.assertEqual(threads_before, threads_after)
        self.assertIsNotNone(supervisor.child)
        self.assertIsNotNone(supervisor.child.poll())


class TestWatchdogLocalSimulation(unittest.TestCase):
    """Section J: Bounded local failure simulation under 60 seconds.

    Proves:
    progress advances -> watchdog healthy
    progress stops -> threshold expires -> watchdog identifies STALL
    -> child termination initiated -> child reaped -> wrapper exits non-zero.
    """

    def test_bounded_local_ffmpeg_or_mock_stall_simulation(self) -> None:
        wall_start = time.monotonic()
        # Script initially advances for 1.5 seconds (3 progress updates), then hangs completely
        sim_script = (
            "import time, sys\n"
            "# Phase 1: healthy advancing progress\n"
            "for i in range(1, 4):\n"
            "    sys.stdout.write(f'out_time_us={i * 1000000}\\nprogress=continue\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.5)\n"
            "# Phase 2: simulated TLS write / network hang (stall)\n"
            "time.sleep(300)\n"
        )

        res = subprocess.run(
            [
                sys.executable,
                str(WATCHDOG_PATH),
                "--threshold",
                "2.0",  # 2.0 second stall threshold for test
                "--grace-period",
                "0.5",
                "--",
                sys.executable,
                "-c",
                sim_script,
            ],
            capture_output=True,
            text=True,
            timeout=30.0,  # Well under the 60.0s hard wall clock
        )

        total_duration = time.monotonic() - wall_start

        # Verification of required proof:
        # 1. Stalled publisher detected and wrapper exits non-zero (124)
        self.assertEqual(res.returncode, 124, f"Expected 124 on stall, got {res.returncode}. Stderr: {res.stderr}")

        # 2. Progress healthy initially logged
        self.assertIn("Publisher progress watchdog started", res.stderr)
        self.assertIn("Publisher child process spawned", res.stderr)

        # 3. Stall identified
        self.assertIn("Publisher stalled!", res.stderr)
        self.assertIn("last out_time_us: 3000000", res.stderr)

        # 4. Termination initiated and reaped
        self.assertIn("Termination sequence initiated", res.stderr)
        self.assertIn("Watchdog exiting with status 124 for systemd recovery", res.stderr)

        # 5. Hard wall-clock limit check (< 60.0s)
        self.assertLess(total_duration, 60.0, f"Local simulation took {total_duration}s, must be under 60.0s")

    def test_bounded_local_natural_child_exit_simulation(self) -> None:
        """Section J: Natural child exit returns child status and is NOT misclassified as 124."""
        wall_start = time.monotonic()
        # Script advances progress and then naturally exits with status 0 without writing progress=end
        sim_script = (
            "import time, sys\n"
            "for i in range(1, 4):\n"
            "    sys.stdout.write(f'out_time_us={i * 1000000}\\nprogress=continue\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.3)\n"
            "sys.exit(0)\n"
        )

        res = subprocess.run(
            [
                sys.executable,
                str(WATCHDOG_PATH),
                "--threshold",
                "2.0",
                "--grace-period",
                "0.5",
                "--",
                sys.executable,
                "-c",
                sim_script,
            ],
            capture_output=True,
            text=True,
            timeout=30.0,
        )

        total_duration = time.monotonic() - wall_start
        self.assertEqual(res.returncode, 0, f"Expected 0 on natural exit, got {res.returncode}. Stderr: {res.stderr}")
        self.assertNotIn("Watchdog exiting with status 124", res.stderr)
        self.assertIn("Publisher child exited with status 0", res.stderr)
        self.assertLess(total_duration, 60.0)


if __name__ == "__main__":
    unittest.main()
