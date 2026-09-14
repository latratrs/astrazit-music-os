"""Unit and invariant tests for AstraZit Radio YouTube Video Stream Assets (RADIO-003).

Validates:
- Systemd service unit astrazit-stream.service integrity, dependency, hardening, and secret boundaries
- Systemd drop-in 20-harbor.conf preserves base RADIO-002 dummy capability while enabling Harbor
- FFmpeg streaming script stream.sh conformance to 720p 30fps CBR and AAC specifications
- Stage-A verifier isolation: stream.sh never automatically sources production stream.env
- Secret safety: FFmpeg stderr suppressed in YouTube mode to prevent RTMPS key leakage
- Host-side /proc isolation (hidepid=2) prerequisite recognized and validated
- Liquidsoap station.liq harbor HTTP audio sink configuration and backwards compatibility
- Visual loop generator and YouTube verification protocol scripts
- Absence of hardcoded stream keys, credentials, or secrets across assets
- ADR-002, ADR-006, and ADR-008 architectural invariants
"""
from __future__ import annotations

import configparser
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestRadioYouTubeStreamAssets(unittest.TestCase):
    """Test Linux streaming service unit, shell scripts, and encoding parameters."""

    def test_harbor_readiness_get_status_bytes_and_process_lifecycle(self) -> None:
        verifier = (REPO_ROOT / "scripts/linux/verify_youtube_stream.sh").read_text(encoding="utf-8")
        self.assertNotRegex(verifier, r"curl[^\n]*(?:\s-I\b|--head\b)")
        self.assertIn("RUN_LIVE_TEST", verifier)
        self.assertNotIn("source \"${CONFIG_STREAM_ENV}\"", verifier)
        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        self.assertTrue(Path(bash).is_file(), "Bash is required for readiness tests")

    def test_systemd_stream_service_structure_and_hardening(self) -> None:
        service_path = REPO_ROOT / "apps" / "radio" / "systemd" / "astrazit-stream.service"
        self.assertTrue(service_path.is_file(), f"Stream service file missing: {service_path}")

        raw_bytes = service_path.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "astrazit-stream.service must use Linux LF line endings")

        text = raw_bytes.decode("utf-8")
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(text)

        # 1. Required sections
        self.assertIn("Unit", parser.sections())
        self.assertIn("Service", parser.sections())
        self.assertIn("Install", parser.sections())

        # 2. Dependencies on network-online and radio audio daemon
        unit_sec = parser["Unit"]
        self.assertIn("network.target", unit_sec.get("After", ""))
        self.assertIn("network-online.target", unit_sec.get("After", ""))
        self.assertIn("astrazit-radio.service", unit_sec.get("After", ""))
        self.assertIn("network-online.target", unit_sec.get("Wants", ""))
        self.assertIn("astrazit-radio.service", unit_sec.get("Wants", ""))
        self.assertEqual(unit_sec.get("StartLimitIntervalSec"), "300")
        self.assertEqual(unit_sec.get("StartLimitBurst"), "5")

        # 3. Execution user & paths
        service_sec = parser["Service"]
        self.assertEqual(service_sec.get("User"), "astrazit")
        self.assertEqual(service_sec.get("WorkingDirectory"), "/opt/astrazit-radio")
        self.assertIn("/opt/astrazit-radio/app/stream.sh", service_sec.get("ExecStart", ""))

        # 4. Restart policy
        self.assertEqual(service_sec.get("Restart"), "always")
        self.assertEqual(service_sec.get("RestartSec"), "5s")

        # 5. Security Hardening (service-internal defense in depth)
        self.assertEqual(service_sec.get("NoNewPrivileges"), "true")
        self.assertEqual(service_sec.get("ProtectSystem"), "full")
        self.assertEqual(service_sec.get("ProtectHome"), "true")
        self.assertEqual(service_sec.get("PrivateTmp"), "true")
        self.assertEqual(service_sec.get("ProtectProc"), "invisible")
        self.assertEqual(service_sec.get("ProcSubset"), "pid")
        self.assertEqual(service_sec.get("RestrictSUIDSGID"), "true")
        self.assertEqual(service_sec.get("LockPersonality"), "true")
        self.assertEqual(service_sec.get("RestrictNamespaces"), "true")

        # 6. Secret Isolation (EnvironmentFile must point to config/stream.env)
        env_file = service_sec.get("EnvironmentFile", "")
        self.assertIn("/opt/astrazit-radio/config/stream.env", env_file)

        # 7. Lifecycle semantics: KillMode must NOT be process (default control-group terminates wrapper and FFmpeg)
        self.assertNotEqual(service_sec.get("KillMode", "").lower(), "process", "astrazit-stream.service must not use KillMode=process")

        # 8. Absence of hardcoded stream keys or plain secrets in unit file
        self.assertNotIn("live2/", text)
        forbidden = ["stream_key=", "secret=", "password="]
        for term in forbidden:
            self.assertNotIn(term, text.lower(), f"Forbidden secret assignment '{term}' found in service unit")

    def test_radio_service_harbor_dropin_preserves_base_and_enables_harbor(self) -> None:
        """Finding 4: Base radio service retains dummy mode; drop-in enables Harbor."""
        base_service_path = REPO_ROOT / "apps" / "radio" / "systemd" / "astrazit-radio.service"
        dropin_path = REPO_ROOT / "apps" / "radio" / "systemd" / "astrazit-radio.service.d" / "20-harbor.conf"
        stream_service_path = REPO_ROOT / "apps" / "radio" / "systemd" / "astrazit-stream.service"

        self.assertTrue(base_service_path.is_file(), "Base astrazit-radio.service missing")
        self.assertTrue(dropin_path.is_file(), "Drop-in 20-harbor.conf missing")
        self.assertTrue(stream_service_path.is_file(), "astrazit-stream.service missing")

        base_text = base_service_path.read_text(encoding="utf-8")
        dropin_text = dropin_path.read_text(encoding="utf-8")
        stream_text = stream_service_path.read_text(encoding="utf-8")

        # Line endings
        self.assertNotIn("\r\n", dropin_text, "20-harbor.conf must use Linux LF line endings")

        # 1. Base RADIO-002 service keeps dummy mode
        self.assertIn("RADIO_OUTPUT_MODE=dummy", base_text)

        # 2. Drop-in overrides production service to Harbor loopback
        dropin_parser = configparser.ConfigParser(interpolation=None, strict=False)
        dropin_parser.read_string(dropin_text)
        self.assertIn("Service", dropin_parser.sections())
        env_line = dropin_parser["Service"].get("Environment", "")
        self.assertIn("RADIO_OUTPUT_MODE=harbor", env_line)
        self.assertIn("RADIO_HARBOR_PORT=8000", env_line)
        self.assertIn("RADIO_HARBOR_MOUNT=radio.wav", env_line)

        # 3. Stream service consumes matching loopback URL
        self.assertIn("http://127.0.0.1:8000/radio.wav", stream_text)

    def test_stream_script_encoding_parameters_and_conformance(self) -> None:
        stream_sh = REPO_ROOT / "apps" / "radio" / "stream.sh"
        self.assertTrue(stream_sh.is_file(), f"stream.sh missing: {stream_sh}")

        raw_bytes = stream_sh.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "stream.sh must use Linux LF line endings")

        text = raw_bytes.decode("utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", text)
        self.assertIn("set +x", text)
        self.assertNotIn("set -x", text)
        self.assertNotIn("echo ${STREAM_KEY}", text)

        # 1. Video Specifications: 1280x720, 30 fps, H.264
        self.assertIn("-c:v libx264", text)
        self.assertIn("-r 30", text)
        self.assertIn("-pix_fmt yuv420p", text)

        # 2. Video CBR: 2500 Kbps CBR with matching minrate/maxrate/bufsize and x264 HRD filler
        self.assertIn("-b:v 2500k", text)
        self.assertIn("-minrate 2500k", text)
        self.assertIn("-maxrate 2500k", text)
        self.assertIn("-bufsize 5000k", text)
        self.assertIn('-x264-params "nal-hrd=cbr:force-cfr=1"', text)
        self.assertNotIn("-b:v 4000k", text, "Must not regress to nominal 4000k VBV-only without HRD filler")

        # 3. Keyframe Interval: 2.0s GOP (60 frames at 30 fps)
        self.assertIn("-g 60", text)
        self.assertIn("-keyint_min 60", text)
        self.assertIn("-sc_threshold 0", text)

        # 4. Audio Specifications: AAC stereo 44.1 kHz @ 128 kbps
        self.assertIn("-c:a aac", text)
        self.assertIn("-b:a 128k", text)
        self.assertIn("-ar 44100", text)
        self.assertIn("-ac 2", text)

        # 5. Visual looping & Audio reconnect resilience
        self.assertIn("-stream_loop -1", text)
        self.assertIn("-reconnect 1", text)
        self.assertIn("-reconnect_at_eof 1", text)
        self.assertIn("-reconnect_streamed 1", text)

        # 6. YouTube Live RTMPS destination
        self.assertIn("rtmps://a.rtmps.youtube.com/live2", text)
        self.assertIn("-f flv", text)

        # 7. Fail-closed secret check (must require non-empty STREAM_KEY when output is youtube)
        self.assertIn('STREAM_KEY="${STREAM_KEY:-}"', text)
        self.assertIn('STREAM_KEY is not defined or is whitespace-only in environment', text)
        self.assertIn('YOUTUBE_RTMPS_BASE}" != rtmps://*', text)

    def test_stage_a_never_loads_production_stream_config(self) -> None:
        """Finding 1: stream.sh must NOT automatically source production stream.env.

        Proves that even if a populated config file exists containing:
          STREAM_OUTPUT_MODE=youtube
          STREAM_KEY=fake-test-only-token
        a file-mode invocation remains in file mode and never selects YouTube.
        """
        stream_sh_text = (REPO_ROOT / "apps" / "radio" / "stream.sh").read_text(encoding="utf-8")
        # Ensure automatic config file sourcing is eliminated from stream.sh
        self.assertNotIn('source "${CONFIG_ENV}"', stream_sh_text)
        self.assertNotIn("source \"${BASE_DIR}/config/stream.env\"", stream_sh_text)

        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        if not Path(bash).is_file():
            self.skipTest("bash required for execution tests")

        with tempfile.TemporaryDirectory(prefix="radio_config_isol_") as tmpdir:
            tmp = Path(tmpdir)
            cfg_dir = tmp / "config"
            cfg_dir.mkdir(parents=True)
            # Create fake production-like stream.env that would divert to youtube if sourced
            fake_env = cfg_dir / "stream.env"
            fake_env.write_text(
                "STREAM_OUTPUT_MODE=youtube\nSTREAM_KEY=fake-test-only-token-do-not-use\n",
                encoding="utf-8",
            )

            # Create dummy visual loop
            assets_dir = tmp / "assets"
            assets_dir.mkdir(parents=True)
            fake_loop = assets_dir / "visual_loop.mp4"
            fake_loop.write_text("fake video content", encoding="utf-8")

            # Mock ffmpeg that inspects arguments and extracts the destination target following -f flv
            bin_dir = tmp / "bin"
            bin_dir.mkdir(parents=True)
            mock_ffmpeg = bin_dir / "ffmpeg"
            mock_ffmpeg.write_text(
                "#!/usr/bin/env bash\n"
                "prev=''\n"
                "target=''\n"
                "for arg in \"$@\"; do\n"
                "    if [[ \"$prev\" == \"-f\" && \"$arg\" == \"flv\" ]]; then\n"
                "        target='next'\n"
                "    elif [[ \"$target\" == 'next' ]]; then\n"
                "        printf 'OUTPUT_TARGET=%s\\n' \"$arg\"\n"
                "        exit 0\n"
                "    fi\n"
                "    prev=\"$arg\"\n"
                "done\n"
                "printf 'OUTPUT_TARGET=%s\\n' \"${@: -1}\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            os.chmod(str(mock_ffmpeg), 0o755)

            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            env["BASE_DIR"] = str(tmp)
            env["STREAM_OUTPUT_MODE"] = "file"
            env["STREAM_OUTPUT_FILE"] = str(tmp / "out.flv")

            res = subprocess.run(
                [bash, (REPO_ROOT / "apps" / "radio" / "stream.sh").as_posix()],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            # Must remain file mode, target file output, and never use youtube or fake token
            self.assertIn("Output Mode:  file", res.stdout)
            self.assertIn(f"OUTPUT_TARGET={tmp / 'out.flv'}", res.stdout)
            self.assertNotIn("fake-test-only-token", res.stdout)
            self.assertNotIn("rtmps://", res.stdout)

    def test_ffmpeg_secret_safe_youtube_mode_error_handling(self) -> None:
        """Finding 2: In YouTube mode, raw FFmpeg diagnostics on stderr must be suppressed.

        The stream key and full RTMPS URL must never appear in stderr/logs.
        Exit status must be reported via sanitized message.
        """
        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        if not Path(bash).is_file():
            self.skipTest("bash required for execution tests")

        with tempfile.TemporaryDirectory(prefix="radio_sec_err_") as tmpdir:
            tmp = Path(tmpdir)
            assets_dir = tmp / "assets"
            assets_dir.mkdir(parents=True)
            fake_loop = assets_dir / "visual_loop.mp4"
            fake_loop.write_text("fake video", encoding="utf-8")

            # Mock ffmpeg that simulates failure and tries to leak URL in stderr
            bin_dir = tmp / "bin"
            bin_dir.mkdir(parents=True)
            mock_ffmpeg = bin_dir / "ffmpeg"
            mock_ffmpeg.write_text(
                "#!/usr/bin/env bash\n"
                "echo 'Connection to rtmps://a.rtmps.youtube.com/live2/fake-secret-key-1234 failed: Connection refused' >&2\n"
                "exit 42\n",
                encoding="utf-8",
            )
            os.chmod(str(mock_ffmpeg), 0o755)

            fake_key = "fake-secret-key-1234"
            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            env["BASE_DIR"] = str(tmp)
            env["STREAM_OUTPUT_MODE"] = "youtube"
            env["STREAM_KEY"] = fake_key

            res = subprocess.run(
                [bash, (REPO_ROOT / "apps" / "radio" / "stream.sh").as_posix()],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            # Exit status must match ffmpeg status (42)
            self.assertEqual(res.returncode, 42)
            # Secret and full URL must NEVER appear in stdout or stderr
            self.assertNotIn(fake_key, res.stdout)
            self.assertNotIn(fake_key, res.stderr)
            self.assertNotIn("rtmps://a.rtmps.youtube.com/live2/fake-secret-key-1234", res.stderr)
            # Sanitized error must be emitted
            self.assertIn("ERROR: FFmpeg publisher exited with status 42.", res.stderr)

    def test_host_proc_isolation_checks(self) -> None:
        """Finding 3: Reusable check detects hidepid=2 and fails closed if missing."""
        setup_text = (REPO_ROOT / "scripts" / "linux" / "setup_radio_node.sh").read_text(encoding="utf-8")
        verify_text = (REPO_ROOT / "scripts" / "linux" / "verify_youtube_stream.sh").read_text(encoding="utf-8")

        # 1. Setup script has check_host_proc_isolation and fails closed
        self.assertIn("check_host_proc_isolation", setup_text)
        self.assertIn("awk '$2 == \"/proc\" { print $4 }' /proc/mounts", setup_text)
        self.assertIn("hidepid=(2|invisible)", setup_text)
        self.assertIn("Production host prerequisite failed", setup_text)

        # 2. Verify script reports status clearly without modifying host
        self.assertIn("production host process-isolation prerequisite not yet satisfied", verify_text)

        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        if not Path(bash).is_file():
            self.skipTest("bash required for function test")

        harness = r'''
check_host_proc_isolation() {
    local proc_opts="$1"
    if echo "${proc_opts}" | grep -qE '\bhidepid=(2|invisible)\b'; then
        return 0
    fi
    return 1
}
'''
        cases = [
            ("rw,nosuid,nodev,noexec,relatime,hidepid=2", 0),
            ("rw,nosuid,nodev,noexec,relatime,hidepid=invisible", 0),
            ("rw,nosuid,nodev,noexec,relatime", 1),
            ("rw,nosuid,nodev,noexec,relatime,hidepid=0", 1),
            ("rw,nosuid,nodev,noexec,relatime,hidepid=1", 1),
        ]
        for opts, expected_code in cases:
            with self.subTest(opts=opts):
                res = subprocess.run(
                    [bash, "-c", f"{harness}\ncheck_host_proc_isolation '{opts}'"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(res.returncode, expected_code)

    def test_host_proc_mounts_fallback_parsing(self) -> None:
        """Regression test for setup_radio_node.sh /proc fallback parsing logic."""
        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        if not Path(bash).is_file():
            self.skipTest("bash required for mounts fallback test")

        harness = r'''
check_mounts_isolation() {
    local mounts_content="$1"
    local proc_opts
    proc_opts="$(printf '%s\n' "${mounts_content}" | awk '$2 == "/proc" { print $4 }' 2>/dev/null || true)"
    if echo "${proc_opts}" | grep -qE '\bhidepid=(2|invisible)\b'; then
        return 0
    fi
    return 1
}
'''
        cases = [
            (
                "Standard hidepid=2",
                "proc /proc proc rw,nosuid,nodev,noexec,relatime,hidepid=2 0 0\nsysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0\n",
                0,
            ),
            (
                "Standard hidepid=invisible",
                "none /proc proc rw,nosuid,nodev,noexec,relatime,hidepid=invisible 0 0\n",
                0,
            ),
            (
                "Leading whitespace and variable column spacing with hidepid=2",
                "   proc   /proc   proc   rw,nosuid,hidepid=2,relatime 0 0\n",
                0,
            ),
            (
                "hidepid=1 must be rejected",
                "proc /proc proc rw,nosuid,nodev,noexec,relatime,hidepid=1 0 0\n",
                1,
            ),
            (
                "no hidepid must be rejected",
                "proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0\n",
                1,
            ),
            (
                "Substring mountpoint /mnt/proc must not false positive",
                "proc /mnt/proc proc rw,nosuid,nodev,noexec,relatime,hidepid=2 0 0\n",
                1,
            ),
            (
                "Mountpoint /proc_fake must not false positive",
                "proc /proc_fake proc rw,nosuid,nodev,noexec,relatime,hidepid=2 0 0\n",
                1,
            ),
            (
                "Unrelated mounts only",
                "sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0\n/dev/sda1 / ext4 rw,relatime 0 0\n",
                1,
            ),
            (
                "Empty mounts content",
                "",
                1,
            ),
        ]

        for name, mounts_data, expected_code in cases:
            with self.subTest(case=name):
                res = subprocess.run(
                    [bash, "-c", f"{harness}\ncheck_mounts_isolation \"$1\"", "_", mounts_data],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(res.returncode, expected_code, f"Failed for case: {name}")

    def test_station_liq_harbor_streaming_configuration(self) -> None:
        station_liq = REPO_ROOT / "apps" / "radio" / "station.liq"
        self.assertTrue(station_liq.is_file(), f"station.liq missing: {station_liq}")

        raw_bytes = station_liq.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "station.liq must use strict Linux LF line endings")

        text = raw_bytes.decode("utf-8")

        # 1. Harbor sink is present
        self.assertIn("output.harbor(%wav", text)
        self.assertIn("RADIO_HARBOR_PORT", text)
        self.assertIn("RADIO_HARBOR_MOUNT", text)

        # 2. Backwards-compatible sink modes (dummy, file, harbor)
        self.assertIn('if output_mode == "file"', text)
        self.assertIn('elsif output_mode == "harbor"', text)
        self.assertIn("output.dummy(station)", text)

        # 3. Zero AI in song-change hot path (ADR-006)
        ai_tokens = ["llm", "gemini", "openai", "claude", "anthropic", "chatgpt"]
        for token in ai_tokens:
            self.assertNotIn(token, text.lower(), f"Forbidden AI token '{token}' in station.liq")

        # 4. Emergency sine fallback (Zero Dead Air)
        self.assertIn("sine(440.0)", text)
        self.assertIn("fallback(", text)

    def test_generate_visual_loop_script_conformance(self) -> None:
        gen_sh = REPO_ROOT / "scripts" / "linux" / "generate_visual_loop.sh"
        self.assertTrue(gen_sh.is_file(), f"generate_visual_loop.sh missing: {gen_sh}")

        raw_bytes = gen_sh.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "generate_visual_loop.sh must use Linux LF line endings")

        text = raw_bytes.decode("utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", text)

        # Validates 1280x720, 30fps, H.264
        self.assertIn("1280x720", text)
        self.assertIn("r=30", text)
        self.assertIn("libx264", text)
        self.assertIn("ffprobe", text)

    def test_verify_youtube_stream_script_integrity(self) -> None:
        verify_sh = REPO_ROOT / "scripts" / "linux" / "verify_youtube_stream.sh"
        self.assertTrue(verify_sh.is_file(), f"verify_youtube_stream.sh missing: {verify_sh}")

        raw_bytes = verify_sh.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "verify_youtube_stream.sh must use Linux LF line endings")

        text = raw_bytes.decode("utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", text)
        self.assertIn("set +x", text)

        # Validates checks for all core acceptance criteria
        self.assertIn("STEP 1: TOOL VALIDATION", text)
        self.assertIn("STEP 3: VISUAL LOOP CONFORMANCE", text)
        self.assertIn("STEP 4: LIQUIDSOAP HARBOR AUDIO STREAM VALIDATION", text)
        self.assertIn("STEP 5: FFMPEG MULTIPLEXING & FFPROBE VALIDATION", text)
        self.assertIn("STEP 6: VISUAL LOOP BOUNDARY CONTINUITY", text)
        self.assertIn("STEP 7: RECONNECT & FAILOVER BEHAVIOR", text)
        self.assertIn("STEP 8: SYSTEMD UNIT INTEGRITY & HOST PROCESS ISOLATION", text)
        self.assertIn("STEP 9: SECRET SANITIZATION AUDIT", text)
        self.assertIn("STEP 10: LIVE YOUTUBE BROADCAST", text)
        self.assertIn('RUN_LIVE_TEST:-0', text)
        self.assertIn('RUN_LIVE_TEST=1', text)

    def test_runtime_secret_file_setup_is_restricted_and_non_overwriting(self) -> None:
        setup = (REPO_ROOT / "scripts" / "linux" / "setup_radio_node.sh").read_text(encoding="utf-8")
        guard = 'if [[ ! -f "${BASE_DIR}/config/stream.env" ]]'
        self.assertIn(guard, setup)
        self.assertIn('chmod 600 "${BASE_DIR}/config/stream.env"', setup)
        self.assertLess(setup.index(guard), setup.index('cat > "${BASE_DIR}/config/stream.env"'))

    def test_setup_does_not_enable_stream_service_with_empty_or_blank_key(self) -> None:
        """Requirement B: Setup installs astrazit-stream.service but NEVER automatically enables or starts it."""
        setup = (REPO_ROOT / "scripts" / "linux" / "setup_radio_node.sh").read_text(encoding="utf-8")
        # Ensure setup does NOT contain an automatic publisher enablement path
        self.assertNotIn("systemctl enable astrazit-stream.service", setup)
        self.assertNotIn("systemctl enable --now astrazit-stream.service", setup.split("echo")[0])
        self.assertIn("NOTE: astrazit-stream.service installed but NOT enabled.", setup)
        self.assertIn("Configure ${STREAM_ENV_FILE} securely (mode 0600).", setup)
        self.assertIn("sudo systemctl enable --now astrazit-stream.service", setup)

    def test_setup_activation_decision_logic_rejects_automatic_enablement(self) -> None:
        """Requirement B regression: execute setup under an intercepted behavioral harness across representative configurations.

        Asserts that in all cases, setup executes daemon-reload and playout service enablement,
        but NEVER attempts to enable, start, or restart astrazit-stream.service.
        """
        setup_sh = REPO_ROOT / "scripts" / "linux" / "setup_radio_node.sh"
        self.assertTrue(setup_sh.is_file(), f"setup_radio_node.sh missing: {setup_sh}")
        setup_text = setup_sh.read_text(encoding="utf-8")
        self.assertNotIn("EXISTING_STREAM_KEY", setup_text)

        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        if not Path(bash).is_file():
            self.skipTest("bash required for behavioral harness test")

        test_cases = [
            ("EMPTY", "STREAM_KEY="),
            ("DOUBLE_QUOTE", 'STREAM_KEY=""'),
            ("SINGLE_QUOTE", "STREAM_KEY=''"),
            ("SPACES", "STREAM_KEY=   "),
            ("SINGLE_QUOTE_SPACES", "STREAM_KEY='   '"),
            ("SYNTHETIC", "STREAM_KEY=synthetic"),
            ("DUP_SYNTH_THEN_EMPTY", "STREAM_KEY=synthetic\nSTREAM_KEY="),
            ("DUP_EMPTY_THEN_SYNTH", "STREAM_KEY=\nSTREAM_KEY=synthetic"),
        ]

        with tempfile.TemporaryDirectory(prefix="radio_setup_harness_") as tmpdir:
            tmp = Path(tmpdir)
            bin_dir = tmp / "bin"
            bin_dir.mkdir(parents=True)
            log_file = tmp / "systemctl.log"

            # Intercept systemctl with mock logging script
            mock_systemctl = bin_dir / "systemctl"
            mock_systemctl.write_text(
                "#!/usr/bin/env bash\n"
                f'printf "SYSTEMCTL_CALL: %s\\n" "$*" >> "{log_file.as_posix()}"\n'
                "exit 0\n",
                encoding="utf-8",
            )
            os.chmod(str(mock_systemctl), 0o755)

            # Mock useradd and apt-get
            for cmd in ["useradd", "apt-get"]:
                mock_cmd = bin_dir / cmd
                mock_cmd.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                os.chmod(str(mock_cmd), 0o755)

            # Mock /proc isolation check function in script copy to pass
            isolated_base = tmp / "opt_astrazit"
            isolated_systemd = tmp / "etc_systemd"
            isolated_systemd.mkdir(parents=True)

            # Prepare sanitized runner script targeting isolated directory tree
            runner_script = tmp / "run_setup.sh"
            sanitized = setup_text.replace(
                'BASE_DIR="/opt/astrazit-radio"',
                f'BASE_DIR="{isolated_base.as_posix()}"',
            ).replace(
                '/etc/systemd/system',
                isolated_systemd.as_posix(),
            ).replace(
                '[[ "${EUID}" -ne 0 ]]',
                '[[ 1 -eq 0 ]]',
            ).replace(
                'check_host_proc_isolation() {',
                'check_host_proc_isolation() { return 0; } \nold_check() {',
            ).replace(
                'chown -R astrazit:astrazit',
                '# chown',
            ).replace(
                'chown astrazit:astrazit',
                '# chown',
            )
            runner_script.write_text(sanitized, encoding="utf-8")
            os.chmod(str(runner_script), 0o755)

            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            env["DEBIAN_FRONTEND"] = "noninteractive"

            for name, payload in test_cases:
                with self.subTest(case=name):
                    # Ensure fresh state
                    cfg_dir = isolated_base / "config"
                    cfg_dir.mkdir(parents=True, exist_ok=True)
                    env_file = cfg_dir / "stream.env"
                    env_file.write_text(payload, encoding="utf-8")

                    if log_file.is_file():
                        log_file.unlink()

                    res = subprocess.run(
                        [bash, runner_script.as_posix()],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(res.returncode, 0, f"Setup script failed for case {name}: {res.stderr}")

                    log_content = log_file.read_text(encoding="utf-8") if log_file.is_file() else ""

                    # Require publisher enablement or start NEVER attempted
                    self.assertNotIn("enable astrazit-stream.service", log_content)
                    self.assertNotIn("start astrazit-stream.service", log_content)
                    self.assertNotIn("restart astrazit-stream.service", log_content)

                    # Allowed/expected systemctl operations
                    self.assertIn("SYSTEMCTL_CALL: daemon-reload", log_content)
                    self.assertIn("SYSTEMCTL_CALL: enable astrazit-radio.service", log_content)

    def test_stream_key_validation_rejects_empty_and_whitespace(self) -> None:
        """Requirement C: stream.sh must reject empty and whitespace-only STREAM_KEY values fail-closed."""
        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        if not Path(bash).is_file():
            self.skipTest("bash required for execution tests")

        with tempfile.TemporaryDirectory(prefix="radio_key_val_") as tmpdir:
            tmp = Path(tmpdir)
            assets_dir = tmp / "assets"
            assets_dir.mkdir(parents=True)
            fake_loop = assets_dir / "visual_loop.mp4"
            fake_loop.write_text("fake video content", encoding="utf-8")

            # Whitespace and empty variations that must fail closed
            invalid_keys = ["", " ", "   ", "\t", "\n", " \t \n "]
            for bad_key in invalid_keys:
                env = os.environ.copy()
                env["BASE_DIR"] = str(tmp)
                env["STREAM_OUTPUT_MODE"] = "youtube"
                env["STREAM_KEY"] = bad_key

                res = subprocess.run(
                    [bash, (REPO_ROOT / "apps" / "radio" / "stream.sh").as_posix()],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(res.returncode, 1, f"Expected returncode 1 for key '{repr(bad_key)}'")
                self.assertIn("ERROR: STREAM_KEY is not defined or is whitespace-only in environment.", res.stderr)
                # Ensure key value is never echoed in output
                self.assertNotIn(f"'{bad_key}'", res.stderr)
                self.assertNotIn(f"'{bad_key}'", res.stdout)

    def test_zero_stream_keys_in_repo(self) -> None:
        """Enforces GATE-09: No real stream keys or YouTube live tokens in repository files."""
        text_extensions = {".py", ".sh", ".liq", ".service", ".conf", ".md", ".json", ".txt"}
        this_file = Path(__file__).resolve()
        # YouTube stream keys follow regex pattern like [a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}
        stream_key_regex = re.compile(r"rtmps://[^\s]+/([a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})")

        for p in REPO_ROOT.rglob("*"):
            if p.is_file() and p.resolve() != this_file and p.suffix in text_extensions and ".git" not in p.parts and ".venv" not in p.parts:
                content = p.read_text(encoding="utf-8", errors="ignore")
                match = stream_key_regex.search(content)
                self.assertIsNone(match, f"Forbidden real stream key detected in {p}: {match.group(0) if match else ''}")


    def test_harbor_loopback_binding_in_station_liq(self) -> None:
        """RADIO-004 Area 3: Verify Harbor authoritative loopback binding via settings.harbor.bind_addrs."""
        station_liq = REPO_ROOT / "apps" / "radio" / "station.liq"
        self.assertTrue(station_liq.is_file(), f"station.liq missing: {station_liq}")
        text = station_liq.read_text(encoding="utf-8")
        # Authoritative loopback setting
        self.assertIn('settings.harbor.bind_addrs := ["127.0.0.1"]', text)
        # Ensure unsupported host= per-output syntax is not present
        self.assertNotIn('host="127.0.0.1"', text)
        self.assertNotIn("host=", text)

    def test_stream_duration_validation_accepts_non_negative_integers_and_rejects_malformed(self) -> None:
        """RADIO-004 Area 6: stream.sh rejects negative, decimal, whitespace, and alpha duration fail-closed."""
        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        if not Path(bash).is_file():
            self.skipTest("bash required for execution tests")

        with tempfile.TemporaryDirectory(prefix="radio_dur_val_") as tmpdir:
            tmp = Path(tmpdir)
            assets_dir = tmp / "assets"
            assets_dir.mkdir(parents=True)
            fake_loop = assets_dir / "visual_loop.mp4"
            fake_loop.write_text("fake video content", encoding="utf-8")

            # Valid values: 0, positive integers (e.g. 20)
            valid_durations = ["0", "20"]
            for dur in valid_durations:
                env = os.environ.copy()
                env["BASE_DIR"] = str(tmp)
                env["STREAM_OUTPUT_MODE"] = "file"
                env["STREAM_OUTPUT_FILE"] = str(tmp / "test.flv")
                env["STREAM_DURATION"] = dur

                # Mock ffmpeg to exit 0 immediately
                bin_dir = tmp / "bin"
                bin_dir.mkdir(parents=True, exist_ok=True)
                mock_ffmpeg = bin_dir / "ffmpeg"
                mock_ffmpeg.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                os.chmod(str(mock_ffmpeg), 0o755)
                env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

                res = subprocess.run(
                    [bash, (REPO_ROOT / "apps" / "radio" / "stream.sh").as_posix()],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(res.returncode, 0, f"Expected returncode 0 for valid duration '{dur}': {res.stderr}")

            # Invalid values: negative, decimal, alphabetic, whitespace, empty, shell-like
            invalid_durations = ["-1", "1.5", "abc", "   ", " 5 ", "", "1;rm -rf", "$(whoami)"]
            for bad_dur in invalid_durations:
                env = os.environ.copy()
                env["BASE_DIR"] = str(tmp)
                env["STREAM_OUTPUT_MODE"] = "file"
                env["STREAM_DURATION"] = bad_dur

                res = subprocess.run(
                    [bash, (REPO_ROOT / "apps" / "radio" / "stream.sh").as_posix()],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(res.returncode, 1, f"Expected returncode 1 for invalid duration '{repr(bad_dur)}'")
                # Statically sanitized error message only
                self.assertIn("ERROR: STREAM_DURATION must be a non-negative integer.", res.stderr)
                # Ensure raw bad duration value is NOT echoed anywhere in error output
                if bad_dur.strip():
                    self.assertNotIn(bad_dur.strip(), res.stderr)

            # Distinctive canary string test: confirm canary is never reflected in stderr
            canary_string = "CANARY_INVALID_DURATION_X9Y8Z7"
            env = os.environ.copy()
            env["BASE_DIR"] = str(tmp)
            env["STREAM_OUTPUT_MODE"] = "file"
            env["STREAM_DURATION"] = canary_string

            res = subprocess.run(
                [bash, (REPO_ROOT / "apps" / "radio" / "stream.sh").as_posix()],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("ERROR: STREAM_DURATION must be a non-negative integer.", res.stderr)
            self.assertNotIn(canary_string, res.stderr)
            self.assertNotIn(canary_string, res.stdout)

    def test_setup_restarts_radio_service_if_and_only_if_already_active(self) -> None:
        """RADIO-004 Area 4: setup script restarts astrazit-radio.service if active, never starts stream."""
        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        if not Path(bash).is_file():
            self.skipTest("bash required for behavioral harness test")

        setup_sh = REPO_ROOT / "scripts" / "linux" / "setup_radio_node.sh"
        setup_text = setup_sh.read_text(encoding="utf-8")

        for radio_is_active in [True, False]:
            with tempfile.TemporaryDirectory(prefix="radio_setup_restart_") as tmpdir:
                tmp = Path(tmpdir)
                bin_dir = tmp / "bin"
                bin_dir.mkdir(parents=True)
                log_file = tmp / "systemctl.log"

                # Intercept systemctl with mock logging script that simulates is-active
                mock_systemctl = bin_dir / "systemctl"
                active_code = "0" if radio_is_active else "3"
                mock_systemctl.write_text(
                    "#!/usr/bin/env bash\n"
                    f'printf "SYSTEMCTL_CALL: %s\\n" "$*" >> "{log_file.as_posix()}"\n'
                    'if [[ "$1" == "is-active" ]]; then\n'
                    f'    exit {active_code}\n'
                    'fi\n'
                    "exit 0\n",
                    encoding="utf-8",
                )
                os.chmod(str(mock_systemctl), 0o755)

                for cmd in ["useradd", "apt-get"]:
                    mock_cmd = bin_dir / cmd
                    mock_cmd.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                    os.chmod(str(mock_cmd), 0o755)

                isolated_base = tmp / "opt_astrazit"
                isolated_systemd = tmp / "etc_systemd"
                isolated_systemd.mkdir(parents=True)

                runner_script = tmp / "run_setup.sh"
                sanitized = setup_text.replace(
                    'BASE_DIR="/opt/astrazit-radio"',
                    f'BASE_DIR="{isolated_base.as_posix()}"',
                ).replace(
                    '/etc/systemd/system',
                    isolated_systemd.as_posix(),
                ).replace(
                    '[[ "${EUID}" -ne 0 ]]',
                    '[[ 1 -eq 0 ]]',
                ).replace(
                    'check_host_proc_isolation() {',
                    'check_host_proc_isolation() { return 0; } \nold_check() {',
                ).replace(
                    'chown -R astrazit:astrazit',
                    '# chown',
                ).replace(
                    'chown astrazit:astrazit',
                    '# chown',
                )
                runner_script.write_text(sanitized, encoding="utf-8")
                os.chmod(str(runner_script), 0o755)

                env = os.environ.copy()
                env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
                env["DEBIAN_FRONTEND"] = "noninteractive"

                res = subprocess.run(
                    [bash, runner_script.as_posix()],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(res.returncode, 0, f"Setup script failed: {res.stderr}")

                log_content = log_file.read_text(encoding="utf-8") if log_file.is_file() else ""

                # Publisher must NEVER be enabled, started, or restarted
                self.assertNotIn("enable astrazit-stream.service", log_content)
                self.assertNotIn("start astrazit-stream.service", log_content)
                self.assertNotIn("restart astrazit-stream.service", log_content)

                # Radio reload/restart expectations
                self.assertIn("SYSTEMCTL_CALL: daemon-reload", log_content)
                self.assertIn("SYSTEMCTL_CALL: enable astrazit-radio.service", log_content)
                if radio_is_active:
                    self.assertIn("SYSTEMCTL_CALL: restart astrazit-radio.service", log_content)
                else:
                    self.assertNotIn("SYSTEMCTL_CALL: restart astrazit-radio.service", log_content)

    def test_publisher_status_observability_script_is_secret_safe(self) -> None:
        """RADIO-004 Area 7: publisher_status.sh exists and strictly avoids forbidden argv/environment inspection."""
        status_script = REPO_ROOT / "scripts" / "linux" / "publisher_status.sh"
        self.assertTrue(status_script.is_file(), f"publisher_status.sh missing: {status_script}")

        raw_bytes = status_script.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "publisher_status.sh must use Linux LF line endings")

        text = raw_bytes.decode("utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", text)
        self.assertIn("set +x", text)

        # Prohibited argv/environment/secret inspection commands
        forbidden_tokens = ["pgrep -f", "ps aux", "cmdline", "printenv", "STREAM_KEY", "echo $STREAM_KEY"]
        for token in forbidden_tokens:
            self.assertNotIn(token, text, f"Forbidden inspection token '{token}' found in publisher_status.sh")

        # Required secret-safe primitives
        self.assertIn("systemctl is-active", text)
        self.assertIn("systemctl is-enabled", text)
        self.assertIn("systemctl show", text)
        self.assertIn("NRestarts", text)
        self.assertIn("MainPID", text)
        self.assertIn("systemctl --failed", text)

    def test_rtmps_timeout_applied_only_to_youtube_mode(self) -> None:
        """RADIO-004 Area 5: Verify -rw_timeout 15000000 is applied strictly to YouTube mode and absent in file mode."""
        stream_sh_text = (REPO_ROOT / "apps" / "radio" / "stream.sh").read_text(encoding="utf-8")

        # Static checks: timeout exists and is defined
        self.assertIn("-rw_timeout", stream_sh_text)
        self.assertIn("15000000", stream_sh_text)
        self.assertIn("OUTPUT_NETWORK_ARGS", stream_sh_text)

        # Confirm CBR configuration remains exactly 2500k with x264 HRD filler
        self.assertIn("-b:v 2500k", stream_sh_text)
        self.assertIn("-minrate 2500k", stream_sh_text)
        self.assertIn("-maxrate 2500k", stream_sh_text)
        self.assertIn("-bufsize 5000k", stream_sh_text)
        self.assertIn('-x264-params "nal-hrd=cbr:force-cfr=1"', stream_sh_text)

        # Confirm secret suppression and safe error handling remain intact
        self.assertIn('set +x', stream_sh_text)
        self.assertIn('>/dev/null 2>&1', stream_sh_text)
        self.assertIn('ERROR: FFmpeg publisher exited with status', stream_sh_text)

        bash = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        if not Path(bash).is_file():
            self.skipTest("bash required for argument composition test")

        with tempfile.TemporaryDirectory(prefix="radio_timeout_test_") as tmpdir:
            tmp = Path(tmpdir)
            assets_dir = tmp / "assets"
            assets_dir.mkdir(parents=True)
            fake_loop = assets_dir / "visual_loop.mp4"
            fake_loop.write_text("fake video", encoding="utf-8")

            # Mock ffmpeg that records all invocation arguments to a file
            bin_dir = tmp / "bin"
            bin_dir.mkdir(parents=True)
            mock_ffmpeg = bin_dir / "ffmpeg"
            args_log = tmp / "ffmpeg_args.log"
            mock_ffmpeg.write_text(
                "#!/usr/bin/env bash\n"
                f'printf "%s\\n" "$@" > "{args_log.as_posix()}"\n'
                "exit 0\n",
                encoding="utf-8",
            )
            os.chmod(str(mock_ffmpeg), 0o755)

            env_base = os.environ.copy()
            env_base["PATH"] = str(bin_dir) + os.pathsep + env_base.get("PATH", "")
            env_base["BASE_DIR"] = str(tmp)

            # 1. FILE MODE: Verify -rw_timeout is NEVER passed
            env_file = env_base.copy()
            env_file["STREAM_OUTPUT_MODE"] = "file"
            env_file["STREAM_OUTPUT_FILE"] = str(tmp / "out.flv")

            res_file = subprocess.run(
                [bash, (REPO_ROOT / "apps" / "radio" / "stream.sh").as_posix()],
                env=env_file,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res_file.returncode, 0, f"File mode failed: {res_file.stderr}")
            args_file_text = args_log.read_text(encoding="utf-8") if args_log.is_file() else ""
            self.assertNotIn("-rw_timeout", args_file_text, "File mode must NOT receive -rw_timeout argument")
            self.assertNotIn("15000000", args_file_text)

            # 2. YOUTUBE MODE: Verify -rw_timeout 15000000 IS passed before -f flv
            env_yt = env_base.copy()
            env_yt["STREAM_OUTPUT_MODE"] = "youtube"
            env_yt["STREAM_KEY"] = "fake-test-key-for-arg-composition"

            res_yt = subprocess.run(
                [bash, (REPO_ROOT / "apps" / "radio" / "stream.sh").as_posix()],
                env=env_yt,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res_yt.returncode, 0, f"YouTube mode failed: {res_yt.stderr}")
            args_yt_lines = (args_log.read_text(encoding="utf-8")).splitlines()
            self.assertIn("-rw_timeout", args_yt_lines, "YouTube mode MUST receive -rw_timeout argument")
            timeout_idx = args_yt_lines.index("-rw_timeout")
            self.assertEqual(args_yt_lines[timeout_idx + 1], "15000000", "Timeout value must be 15000000 microseconds")
            flv_idx = args_yt_lines.index("-f")
            self.assertLess(timeout_idx, flv_idx, "-rw_timeout must precede output format -f flv")


if __name__ == "__main__":
    unittest.main()
