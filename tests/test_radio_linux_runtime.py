"""Unit tests for AstraZit Radio Linux VPS Playout Runtime Assets (RADIO-002).

Validates:
- systemd service unit integrity, hardening, and forbidden token boundaries
- station.liq script syntax conventions, LF line endings, and fallback protection
- Linux node setup script and verification protocol integrity
- Path alignment with standard /opt/astrazit-radio layout
- ADR-002, ADR-006, and ADR-008 architectural invariants
"""
from __future__ import annotations

import configparser
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestRadioLinuxRuntimeAssets(unittest.TestCase):
    """Test Linux VPS service unit, Liquidsoap script, and provisioning scripts."""

    def test_systemd_service_file_structure_and_hardening(self) -> None:
        service_path = REPO_ROOT / "apps" / "radio" / "systemd" / "astrazit-radio.service"
        self.assertTrue(service_path.is_file(), f"Service file missing: {service_path}")

        raw_bytes = service_path.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "systemd service file must use Linux LF line endings")

        text = raw_bytes.decode("utf-8")
        # Systemd files are INI-style
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(text)

        # 1. Required sections
        self.assertIn("Unit", parser.sections())
        self.assertIn("Service", parser.sections())
        self.assertIn("Install", parser.sections())

        # 2. Execution user & paths
        service_sec = parser["Service"]
        self.assertEqual(service_sec.get("User"), "astrazit")
        self.assertEqual(service_sec.get("WorkingDirectory"), "/opt/astrazit-radio")
        self.assertIn("/usr/bin/liquidsoap", service_sec.get("ExecStart", ""))
        self.assertIn("/opt/astrazit-radio/app/station.liq", service_sec.get("ExecStart", ""))

        # 3. Restart policy
        self.assertEqual(service_sec.get("Restart"), "always")
        self.assertEqual(service_sec.get("RestartSec"), "5s")

        # 4. Security Hardening
        self.assertEqual(service_sec.get("NoNewPrivileges"), "true")
        self.assertEqual(service_sec.get("ProtectSystem"), "full")
        self.assertEqual(service_sec.get("ProtectHome"), "true")
        self.assertEqual(service_sec.get("PrivateTmp"), "true")

        # 5. Output / Journal logging
        self.assertEqual(service_sec.get("StandardOutput"), "journal")
        self.assertEqual(service_sec.get("StandardError"), "journal")

        # 6. Absence of forbidden items
        forbidden = ["youtube", "rtmp", "stream_key", "secret", "gcp", "google_application_credentials"]
        for word in forbidden:
            self.assertNotIn(word, text.lower(), f"Forbidden word '{word}' found in systemd service file")

    def test_station_liq_linux_conventions_and_invariants(self) -> None:
        station_liq = REPO_ROOT / "apps" / "radio" / "station.liq"
        self.assertTrue(station_liq.is_file(), f"station.liq missing: {station_liq}")

        raw_bytes = station_liq.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "station.liq must use strict Linux LF line endings")

        text = raw_bytes.decode("utf-8")

        # 1. Directory conventions align with /opt/astrazit-radio
        self.assertIn('default="/opt/astrazit-radio/music"', text)
        self.assertIn('default="/opt/astrazit-radio/logs/plays.jsonl"', text)

        # 2. Zero AI in song-change hot path
        ai_tokens = ["llm", "gemini", "openai", "claude", "anthropic", "chatgpt"]
        for token in ai_tokens:
            self.assertNotIn(token, text.lower(), f"Forbidden AI token '{token}' in station.liq hot path")

        # 3. Emergency fallback tone present (Zero Dead Air)
        self.assertIn("sine(440.0)", text)
        self.assertIn("fallback(", text)

        # 4. Lifecycle logging present
        self.assertIn('"event":"STATION_START"', text)
        self.assertIn('"event":"TRACK_START"', text)
        self.assertIn('"event":"STATION_STOP"', text)

        # 5. Output sink options (dummy and verifiable file output)
        self.assertIn("output.dummy(station)", text)
        self.assertIn("output.file(%wav", text)
        self.assertIn("RADIO_OUTPUT_MODE", text)

    def test_setup_radio_node_script_integrity(self) -> None:
        setup_sh = REPO_ROOT / "scripts" / "linux" / "setup_radio_node.sh"
        self.assertTrue(setup_sh.is_file(), f"setup script missing: {setup_sh}")

        raw_bytes = setup_sh.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "setup script must use Linux LF line endings")

        text = raw_bytes.decode("utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", text)

        # Installs prerequisites
        self.assertIn("liquidsoap", text)
        self.assertIn("ffmpeg", text)

        # Non-root user creation
        self.assertIn("useradd", text)
        self.assertIn("astrazit", text)

        # Directory layout & permissions
        self.assertIn("/opt/astrazit-radio", text)
        self.assertIn("chmod 750", text)
        self.assertNotIn("chmod 777", text, "Broad chmod 777 permissions are strictly forbidden")

    def test_verify_audible_playout_script_integrity(self) -> None:
        verify_sh = REPO_ROOT / "scripts" / "linux" / "verify_audible_playout.sh"
        self.assertTrue(verify_sh.is_file(), f"verify script missing: {verify_sh}")

        raw_bytes = verify_sh.read_bytes()
        self.assertNotIn(b"\r\n", raw_bytes, "verify script must use Linux LF line endings")

        text = raw_bytes.decode("utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", text)

        # Checks 3-tone test frequencies
        self.assertIn("440.0", text)
        self.assertIn("554.37", text)
        self.assertIn("659.25", text)

        # Tool validation & ffprobe inspection
        self.assertIn("ffprobe", text)
        self.assertIn("liquidsoap --check", text)
        self.assertIn("audible_playout_test.wav", text)

        # Systemd lifecycle commands
        self.assertIn('sudo systemctl start "${SERVICE_NAME}"', text)
        self.assertIn('sudo systemctl restart "${SERVICE_NAME}"', text)
        self.assertIn('sudo systemctl stop "${SERVICE_NAME}"', text)
        self.assertIn("kill -9", text)


if __name__ == "__main__":
    unittest.main()

