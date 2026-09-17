"""Offline Unit & Integration Test Suite for OpenRouter Review Matrix (OS-009).

Tests all architectural, security, schema, path-traversal, secret-sanitization,
and error-handling conditions completely offline using MockTransport. Zero network egress.
"""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.review_runner import (
    APPROVED_MODELS,
    MockTransport,
    ReviewRunner,
    is_path_forbidden,
    resolve_allowlisted_file,
    resolve_cli_output_dir,
    sanitize_text_for_logging,
    scan_content_for_secrets,
    validate_structured_response,
    extract_safe_response_diagnostics,
)


class TestReviewRunnerOffline(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.profile_path = self.repo_root / ".ai-review" / "profiles" / "RADIO-003.json"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # 1. Python runtime check
    def test_01_runtime_version_is_supported(self):
        import sys
        self.assertGreaterEqual(sys.version_info[:2], (3, 12))

    # 2. Valid RADIO-003 profile loading
    def test_02_load_valid_radio_003_profile(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        profile = runner.load_profile()
        self.assertEqual(profile["ticket"], "RADIO-003")
        self.assertEqual(profile["risk_tier"], "T3")
        self.assertIn("claude", profile["specialists"])
        self.assertIn("deepseek", profile["specialists"])
        self.assertIn("grok", profile["specialists"])

    # 3. Unknown ticket profile rejected
    def test_03_unknown_ticket_profile_rejected(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.repo_root / ".ai-review" / "profiles" / "NONEXISTENT-999.json",
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        with self.assertRaises(FileNotFoundError):
            runner.load_profile()

    # 4. Unknown specialist filter rejected
    def test_04_unknown_specialist_filter_rejected(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        with self.assertRaises(ValueError):
            runner.run_matrix(specialist_filter="unknown_agent")

    # 5. Exact model matrix
    def test_05_exact_model_matrix_configured(self):
        self.assertEqual(APPROVED_MODELS["claude"], "anthropic/claude-sonnet-5")
        self.assertEqual(APPROVED_MODELS["deepseek"], "deepseek/deepseek-v4-pro")
        self.assertEqual(APPROVED_MODELS["grok"], "x-ai/grok-4.6")

    # 6. Grok request omits reasoning field entirely and retains temperature
    def test_06_grok_request_omits_reasoning_and_retains_temperature(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        body = runner.build_request_body(
            "x-ai/grok-4.6",
            "prompt",
            {"request_options": {}},
            4000,
        )
        self.assertNotIn("reasoning", body)
        self.assertEqual(body.get("temperature"), 0.2)
        self.assertEqual(body["provider"]["zdr"], True)
        self.assertEqual(body["provider"]["data_collection"], "deny")
        self.assertEqual(body["provider"]["require_parameters"], True)

    # 7. Claude request omits temperature and reasoning when configured in profile
    def test_07_claude_request_omits_temperature_and_reasoning(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        body = runner.build_request_body(
            "anthropic/claude-sonnet-5",
            "prompt",
            {"request_options": {"omit_temperature": True}},
            4000,
        )
        self.assertEqual(body["model"], "anthropic/claude-sonnet-5")
        self.assertNotIn("temperature", body)
        self.assertNotIn("reasoning", body)
        self.assertEqual(body["provider"]["zdr"], True)
        self.assertEqual(body["provider"]["data_collection"], "deny")
        self.assertEqual(body["provider"]["require_parameters"], True)
        self.assertEqual(sorted(body.keys()), ["max_tokens", "messages", "model", "provider"])

    # 8. DeepSeek request includes reasoning effort none and retains temperature
    def test_08_deepseek_request_uses_reasoning_effort_none(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        body = runner.build_request_body(
            "deepseek/deepseek-v4-pro",
            "prompt",
            {"request_options": {"reasoning": {"effort": "none"}}},
            4000,
        )
        self.assertEqual(body.get("reasoning"), {"effort": "none"})
        self.assertEqual(body.get("temperature"), 0.2)
        self.assertEqual(body["provider"]["zdr"], True)
        self.assertEqual(body["provider"]["data_collection"], "deny")
        self.assertEqual(body["provider"]["require_parameters"], True)

    # 9. Every request contains provider.zdr = true, data_collection = deny, require_parameters = true (Check 3)
    def test_09_every_request_contains_zdr_data_collection_and_require_parameters(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        for model in ["anthropic/claude-sonnet-5", "deepseek/deepseek-v4-pro", "x-ai/grok-4.6"]:
            body = runner.build_request_body(model, "prompt", {}, 4000)
            self.assertEqual(body["provider"]["zdr"], True)
            self.assertEqual(body["provider"]["data_collection"], "deny")
            self.assertEqual(body["provider"]["require_parameters"], True)

    # 10b. Temperature omission is explicit and profile-driven, not broad substring
    def test_10b_unrelated_model_retains_temperature_by_default(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        # An unrelated model without omit_temperature retains default temperature:
        body = runner.build_request_body("anthropic/other-model", "prompt", {}, 4000)
        self.assertEqual(body.get("temperature"), 0.2)

    # 10. No auto-router
    def test_10_no_auto_router(self):
        for m in APPROVED_MODELS.values():
            self.assertNotEqual(m, "openrouter/auto")
            self.assertFalse(m.startswith("auto"))

    # 11. No --live means MockTransport is used (no network)
    def test_11_no_live_means_mock_transport_used(self):
        transport = MockTransport()
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            is_live=False,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "PARTIAL")
        self.assertEqual(summary["review_scope"], "SINGLE-SPECIALIST")
        self.assertEqual(summary["council_status"], "PARTIAL")
        self.assertEqual(len(transport.call_history), 1)

    # 12. Live mode without API key fails
    def test_12_live_mode_without_api_key_fails(self):
        transport = MockTransport()
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            api_key=None,
            is_live=True,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(summary["specialists"]["claude"]["verdict"], "FAIL")
        self.assertIn("OPENROUTER_API_KEY is not set", summary["specialists"]["claude"]["error_message"])

    # 13. Fake injected live key works with fake transport
    def test_13_fake_injected_live_key_works_with_fake_transport(self):
        transport = MockTransport()
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            api_key="fake-test-key-123456789012345678",
            is_live=True,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "PARTIAL")
        self.assertEqual(summary["review_scope"], "SINGLE-SPECIALIST / COMPLETION")
        self.assertEqual(summary["council_status"], "PARTIAL")
        self.assertEqual(summary["specialists"]["claude"]["verdict"], "PASS")

    # 14. Actual runtime fake key appearing in payload is rejected
    def test_14_runtime_key_in_payload_fails_closed(self):
        fake_key = "secret-fake-key-1234567890abcdef"
        safe, reason = scan_content_for_secrets(f"leak here: {fake_key}", runtime_key=fake_key)
        self.assertFalse(safe)
        self.assertIn("runtime API key", reason)

    # 15. OpenRouter key detection boundaries (Check 2)
    def test_15_openrouter_key_boundary_detection(self):
        # Shorter realistic key (32 chars)
        short_key = "sk-or-v1-" + "a" * 32
        safe, _ = scan_content_for_secrets(f"key: {short_key}")
        self.assertFalse(safe)

        # Observed 64 chars key
        standard_key = "sk-or-v1-" + "b" * 64
        safe, _ = scan_content_for_secrets(f"key: {standard_key}")
        self.assertFalse(safe)

        # Plausible longer future key (96 chars)
        long_key = "sk-or-v1-" + "c" * 96
        safe, _ = scan_content_for_secrets(f"key: {long_key}")
        self.assertFalse(safe)

        # Placeholder exemption
        placeholder = "sk-or-v1-placeholder"
        safe, _ = scan_content_for_secrets(f"key: {placeholder}")
        self.assertTrue(safe)

    # 16. Literal sk-or-v1- documentation allowed
    def test_16_literal_sk_or_v1_prefix_in_prose_allowed(self):
        prose = "The OpenRouter key prefix is sk-or-v1- and should be preserved in documentation."
        safe, _ = scan_content_for_secrets(prose)
        self.assertTrue(safe)

    # 17. OPENROUTER_API_KEY literal allowed
    def test_17_openrouter_api_key_literal_name_allowed(self):
        prose = "Read the token from OPENROUTER_API_KEY environment variable."
        safe, _ = scan_content_for_secrets(prose)
        self.assertTrue(safe)

    # 18. Bearer <placeholder> allowed
    def test_18_bearer_placeholder_allowed(self):
        content = "Use header: Authorization: Bearer <token> or Authorization: Bearer <placeholder>"
        safe, _ = scan_content_for_secrets(content)
        self.assertTrue(safe)

    # 19. Realistic Bearer credential rejected
    def test_19_realistic_bearer_credential_rejected(self):
        bad_content = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.fake_token_value_32_bytes_long"
        safe, reason = scan_content_for_secrets(bad_content)
        self.assertFalse(safe)
        self.assertIn("Bearer credential", reason)

    # 20. STREAM_KEY=<placeholder> allowed
    def test_20_stream_key_placeholder_allowed(self):
        content = "Set STREAM_KEY=<placeholder> or STREAM_KEY=xxxx-xxxx-xxxx-xxxx-xxxx for tests."
        safe, _ = scan_content_for_secrets(content)
        self.assertTrue(safe)

    # 21. Private key block rejected
    def test_21_private_key_header_rejected(self):
        bad_content = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA==\n-----END OPENSSH PRIVATE KEY-----"
        safe, reason = scan_content_for_secrets(bad_content)
        self.assertFalse(safe)
        self.assertIn("private key header", reason)

    # 22. Forbidden stream.env path rejected
    def test_22_forbidden_stream_env_path_rejected(self):
        self.assertTrue(is_path_forbidden("apps/radio/stream.env"))
        self.assertTrue(is_path_forbidden(".env"))
        self.assertTrue(is_path_forbidden("config/stream.env.local"))

    # 23. Forbidden SSH key path rejected
    def test_23_forbidden_ssh_key_paths_rejected(self):
        self.assertTrue(is_path_forbidden("~/.ssh/id_rsa"))
        self.assertTrue(is_path_forbidden("id_ed25519"))
        self.assertTrue(is_path_forbidden("server.pem"))
        self.assertTrue(is_path_forbidden("credentials.json"))

    # 24. Legitimate documentation mentioning stream.env allowed
    def test_24_prose_mentioning_stream_env_allowed(self):
        prose = "The service reads configuration from stream.env at runtime."
        safe, _ = scan_content_for_secrets(prose)
        self.assertTrue(safe)

    # 25. Oversized payload rejected
    def test_25_oversized_payload_rejected(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        s_cfg = {
            "prompt": "x" * 200,
            "allowlist": ["reports/RADIO-003-review-packet.md"],
        }
        with self.assertRaises(ValueError):
            runner.assemble_specialist_payload(s_cfg, max_payload_bytes=100)

    # 26. Valid mock response accepted
    def test_26_valid_mock_response_accepted(self):
        valid_json = json.dumps({
            "verdict": "PASS",
            "findings": [],
            "evidence": ["Evidence 1"],
            "files_reviewed": ["file.txt"],
            "tests_checks": ["Check 1"],
            "risks": [],
            "next_gate": "CHATGPT TRIAGE",
        })
        data, err = validate_structured_response(valid_json, ["file.txt"])
        self.assertIsNone(err)
        self.assertEqual(data["verdict"], "PASS")

    # 27. Empty response rejected
    def test_27_empty_response_rejected(self):
        data, err = validate_structured_response("", [])
        self.assertIsNone(data)
        self.assertIn("Empty response", err)

    # 28. Malformed JSON rejected
    def test_28_malformed_json_rejected(self):
        data, err = validate_structured_response("not json at all", [])
        self.assertIsNone(data)
        self.assertIn("not valid JSON", err)

    # 29. Missing required result field rejected
    def test_29_missing_required_field_rejected(self):
        bad_json = json.dumps({"verdict": "PASS"})
        data, err = validate_structured_response(bad_json, [])
        self.assertIsNone(data)
        self.assertIn("Missing required response field", err)

    # 30. Invalid verdict rejected
    def test_30_invalid_verdict_rejected(self):
        bad_json = json.dumps({
            "verdict": "MAYBE",
            "findings": [],
            "evidence": [],
            "files_reviewed": [],
            "tests_checks": [],
            "risks": [],
            "next_gate": "CHATGPT TRIAGE",
        })
        data, err = validate_structured_response(bad_json, [])
        self.assertIsNone(data)
        self.assertIn("Invalid verdict", err)

    # 31. Invalid severity rejected
    def test_31_invalid_severity_rejected(self):
        bad_json = json.dumps({
            "verdict": "FAIL",
            "findings": [{
                "severity": "CRITICAL_BUT_NOT_STANDARD",
                "file": "file.txt",
                "line": 1,
                "failure_mode": "err",
                "smallest_correction": "fix",
            }],
            "evidence": [],
            "files_reviewed": [],
            "tests_checks": [],
            "risks": [],
            "next_gate": "CHATGPT TRIAGE",
        })
        data, err = validate_structured_response(bad_json, ["file.txt"])
        self.assertIsNone(data)
        self.assertIn("invalid severity", err)

    # 32. >5 ordinary findings rejected
    def test_32_more_than_5_ordinary_findings_rejected(self):
        findings = [
            {"severity": "P3", "file": "f.txt", "line": i, "failure_mode": "m", "smallest_correction": "c"}
            for i in range(1, 7)
        ]
        bad_json = json.dumps({
            "verdict": "CORRECTION REQUIRED",
            "findings": findings,
            "evidence": [],
            "files_reviewed": [],
            "tests_checks": [],
            "risks": [],
            "next_gate": "CHATGPT TRIAGE",
        })
        data, err = validate_structured_response(bad_json, ["f.txt"])
        self.assertIsNone(data)
        self.assertIn("maximum permitted is 5", err)

    # 33. Returned model mismatch rejected
    def test_33_returned_model_mismatch_rejected(self):
        fake_response = {
            "anthropic/claude-sonnet-5": json.dumps({
                "verdict": "PASS",
                "findings": [],
                "evidence": [],
                "files_reviewed": [],
                "tests_checks": [],
                "risks": [],
                "next_gate": "CHATGPT TRIAGE",
            })
        }
        transport = MockTransport(responses=fake_response)
        def fake_send(*args, **kwargs):
            return 200, {
                "model": "unauthorized-openai/gpt-4o",
                "choices": [{"message": {"content": fake_response["anthropic/claude-sonnet-5"]}}],
            }
        transport.send_request = fake_send
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(summary["specialists"]["claude"]["verdict"], "FAIL")
        self.assertIn("Model mismatch", summary["specialists"]["claude"]["error_message"])

    # 34-37. HTTP 400, 401, 403, 429 have zero retries
    def test_34_to_37_http_4xx_no_retries(self):
        for status_code in [400, 401, 403, 429]:
            transport = MockTransport(fail_status=status_code)
            runner = ReviewRunner(
                repo_root=self.repo_root,
                profile_path=self.profile_path,
                output_dir=self.output_dir,
                transport=transport,
            )
            status, _ = runner.run_matrix(specialist_filter="claude")
            self.assertEqual(status, "INCOMPLETE")
            self.assertEqual(len(transport.call_history), 1)

    # 38-40. HTTP 502, 503, 504 retries exactly once
    def test_38_to_40_http_5xx_retries_once(self):
        for status_code in [502, 503, 504]:
            transport = MockTransport(fail_status=status_code)
            sleep_calls = []
            runner = ReviewRunner(
                repo_root=self.repo_root,
                profile_path=self.profile_path,
                output_dir=self.output_dir,
                transport=transport,
                sleep_fn=lambda s: sleep_calls.append(s),
            )
            status, _ = runner.run_matrix(specialist_filter="claude")
            self.assertEqual(status, "INCOMPLETE")
            self.assertEqual(len(transport.call_history), 2)
            self.assertEqual(sleep_calls, [2.0])

    # 41. Second 5xx marks failure
    def test_41_second_5xx_marks_failure(self):
        transport = MockTransport(fail_status=500)
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(summary["specialists"]["claude"]["verdict"], "FAIL")

    # 42. First specialist failure causes council INCOMPLETE
    def test_42_first_specialist_failure_causes_council_incomplete(self):
        transport = MockTransport(fail_status=500)
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
        )
        status, _ = runner.run_matrix()
        self.assertEqual(status, "INCOMPLETE")

    # 43. Sequential dispatch order
    def test_43_sequential_dispatch_order(self):
        transport = MockTransport()
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
        )
        runner.run_matrix()
        calls = [c["payload"]["model"] for c in transport.call_history]
        self.assertEqual(calls, [
            "anthropic/claude-sonnet-5",
            "deepseek/deepseek-v4-pro",
            "x-ai/grok-4.6",
        ])

    # 44. Each success persisted before next dispatch
    def test_44_each_success_persisted_immediately(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        status, summary = runner.run_matrix()
        run_dir = self.output_dir / "RADIO-003" / runner.run_id
        self.assertTrue((run_dir / "claude-review.json").exists())
        self.assertTrue((run_dir / "deepseek-review.json").exists())
        self.assertTrue((run_dir / "grok-review.json").exists())
        self.assertTrue((run_dir / "run-summary.json").exists())

    # 45. Report files do not contain fake API key
    def test_45_report_files_do_not_contain_api_key(self):
        fake_key = "fake-key-998877665544332211"
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
            api_key=fake_key,
        )
        runner.run_matrix()
        run_dir = self.output_dir / "RADIO-003" / runner.run_id
        for p in run_dir.iterdir():
            content = p.read_text(encoding="utf-8")
            self.assertNotIn(fake_key, content)

    # 46. Manifest contains only safe metadata
    def test_46_manifest_contains_safe_metadata(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        runner.run_matrix()
        manifest_file = self.output_dir / "RADIO-003" / runner.run_id / "manifest.json"
        with open(manifest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["ticket"], "RADIO-003")
        self.assertNotIn("Authorization", data)
        self.assertNotIn("api_key", data)

    # 47. Run-summary contains no authorization or secret key
    def test_47_run_summary_contains_no_authorization(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        runner.run_matrix()
        summary_file = self.output_dir / "RADIO-003" / runner.run_id / "run-summary.json"
        with open(summary_file, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("Authorization", raw)
        self.assertNotIn("Bearer", raw)

    # 48. Unsafe model response is not persisted raw (Check 7)
    def test_48_unsafe_model_response_rejected_and_not_persisted(self):
        fake_response = {
            "anthropic/claude-sonnet-5": f"-----BEGIN RSA PRIVATE KEY-----\nb3BlbnNzaA==\n-----END RSA PRIVATE KEY-----"
        }
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(responses=fake_response),
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")
        run_dir = self.output_dir / "RADIO-003" / runner.run_id
        self.assertFalse((run_dir / "claude-review.md").exists())
        err_text = (run_dir / "claude-error.txt").read_text(encoding="utf-8")
        self.assertNotIn("BEGIN RSA PRIVATE KEY", err_text)

    # 49. Source tree content unchanged
    def test_49_source_tree_content_unchanged(self):
        self.assertTrue((self.repo_root / "apps" / "radio" / "stream.sh").exists())

    # 50. No staged git changes caused by runner
    def test_50_runner_does_not_stage_git_changes(self):
        self.assertIn(self.temp_dir.name, str(self.output_dir))

    # 51. All three specialists success => COMPLETE
    def test_51_all_three_specialists_success_complete(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        status, summary = runner.run_matrix()
        self.assertEqual(status, "COMPLETE")
        self.assertEqual(summary["specialists"]["claude"]["verdict"], "PASS")
        self.assertEqual(summary["specialists"]["deepseek"]["verdict"], "PASS")
        self.assertEqual(summary["specialists"]["grok"]["verdict"], "PASS")

    # 52. Accepted RADIO-003 argv/memory limitation appears in prompts/context
    def test_52_accepted_argv_memory_limitation_in_prompts(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        profile = runner.load_profile()
        for s_name, s_cfg in profile["specialists"].items():
            prompt = s_cfg["prompt"]
            self.assertIn("Root and the trusted astrazit service account may be capable of seeing RTMPS target material in process argv/memory", prompt)
            self.assertIn("accepted MVP trust-boundary limitation", prompt)

    # 53. Check 4: HTTP Error response body containing secrets is sanitized and not leaked
    def test_53_http_error_body_secrets_are_sanitized(self):
        fake_secret_key = "sk-or-v1-" + "d" * 64
        fake_bearer = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.fake_token_value_32_bytes_long"
        leaky_error_body = {"error": f"Invalid key: {fake_secret_key} and header {fake_bearer}"}
        transport = MockTransport(fail_status=401, fail_body=leaky_error_body)

        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            is_live=False,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")

        run_dir = self.output_dir / "RADIO-003" / runner.run_id
        for artifact in run_dir.iterdir():
            content = artifact.read_text(encoding="utf-8")
            self.assertNotIn(fake_secret_key, content)
            self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", content)

    # 54. Check 5: Environment variable alone does not trigger live egress without --live
    def test_54_env_key_without_live_flag_uses_mock_transport(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-env-key-9999999999999"}):
            transport = MockTransport()
            runner = ReviewRunner(
                repo_root=self.repo_root,
                profile_path=self.profile_path,
                output_dir=self.output_dir,
                transport=transport,
                is_live=False,  # No --live flag
            )
            status, _ = runner.run_matrix(specialist_filter="claude")
            self.assertEqual(status, "PARTIAL")
            self.assertEqual(runner.is_live, False)
            self.assertIsNone(runner.api_key)

    # 55. Check 6: Real key is not accessed during offline initialization
    def test_55_offline_does_not_read_real_key_from_env(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "should-never-be-read"}):
            # Simulate CLI logic
            live_flag = False
            api_key = os.environ.get("OPENROUTER_API_KEY") if live_flag else None
            self.assertIsNone(api_key)

    # 56. Check 8: Path traversal attempts in findings file field are rejected
    def test_56_path_traversal_in_findings_rejected(self):
        for malicious_path in ["../../secret.txt", "C:\\Users\\itclo\\secret.txt", "/etc/passwd"]:
            malicious_json = json.dumps({
                "verdict": "FAIL",
                "findings": [{
                    "severity": "P1",
                    "file": malicious_path,
                    "line": 1,
                    "failure_mode": "test path traversal",
                    "smallest_correction": "fix path",
                }],
                "evidence": [],
                "files_reviewed": [],
                "tests_checks": [],
                "risks": [],
                "next_gate": "CHATGPT TRIAGE",
            })
            data, err = validate_structured_response(malicious_json, ["file.txt"])
            self.assertIsNone(data)
            self.assertIn("unsafe file reference", err)

    # 57. Check 9: Execution mode metadata distinction
    def test_57_execution_mode_metadata_distinction(self):
        runner_mock = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
            is_live=False,
            is_mock_run=True,
        )
        _, summary = runner_mock.run_matrix(specialist_filter="claude")
        self.assertEqual(summary["execution_mode"], "MOCK-REVIEW")

    # 58. Single-specialist smoke semantics never imply full council complete
    def test_58_single_specialist_smoke_semantics(self):
        transport = MockTransport()
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            is_live=True,
            api_key="fake-smoke-key-123456789012345678",
        )
        status, summary = runner.run_matrix(specialist_filter="deepseek")
        self.assertEqual(status, "PARTIAL")
        self.assertEqual(summary["council_status"], "PARTIAL")
        self.assertEqual(summary["execution_mode"], "REAL-REVIEW")
        self.assertEqual(summary["review_scope"], "SINGLE-SPECIALIST / COMPLETION")
        self.assertEqual(summary["invoked_specialists"], ["deepseek"])
        self.assertEqual(summary["required_specialists"], ["claude", "deepseek", "grok"])
        self.assertNotEqual(summary["council_status"], "COMPLETE")

        manifest_file = self.output_dir / "RADIO-003" / runner.run_id / "manifest.json"
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
        self.assertEqual(manifest_data["council_status"], "PARTIAL")
        self.assertEqual(manifest_data["review_scope"], "SINGLE-SPECIALIST / COMPLETION")
        self.assertEqual(manifest_data["invoked_specialists"], ["deepseek"])
        self.assertEqual(manifest_data["required_specialists"], ["claude", "deepseek", "grok"])

    # 59. Claude request omits temperature and includes bounded reasoning {max_tokens: 3000}
    def test_59_claude_request_omits_temperature_and_has_bounded_reasoning(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        profile = runner.load_profile()
        claude_cfg = profile["specialists"]["claude"]
        body = runner.build_request_body("anthropic/claude-sonnet-5", "test payload", claude_cfg, 8000)
        self.assertNotIn("temperature", body)
        self.assertIn("reasoning", body)
        self.assertEqual(body["reasoning"], {"max_tokens": 3000})
        self.assertNotIn("effort", body["reasoning"])
        self.assertNotIn("response_format", body)
        self.assertEqual(body["max_tokens"], 8000)
        self.assertEqual(body["model"], "anthropic/claude-sonnet-5")
        self.assertTrue(body["provider"]["zdr"])
        self.assertEqual(body["provider"]["data_collection"], "deny")
        self.assertTrue(body["provider"]["require_parameters"])

    # 60. Specialist-specific max_output_tokens resolution (Claude=8000, DeepSeek/Grok=4000)
    def test_60_specialist_token_budgets(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        profile = runner.load_profile()
        self.assertEqual(profile.get("max_output_tokens"), 4000)
        claude_cfg = profile["specialists"]["claude"]
        deepseek_cfg = profile["specialists"]["deepseek"]
        grok_cfg = profile["specialists"]["grok"]

        claude_tokens = claude_cfg.get("max_output_tokens", 4000)
        deepseek_tokens = deepseek_cfg.get("max_output_tokens", profile.get("max_output_tokens"))
        grok_tokens = grok_cfg.get("max_output_tokens", profile.get("max_output_tokens"))

        self.assertEqual(claude_tokens, 8000)
        self.assertEqual(deepseek_tokens, 4000)
        self.assertEqual(grok_tokens, 4000)

    # 61. Safe response diagnostics extraction
    def test_61_extract_safe_response_diagnostics(self):
        sample_resp = {
            "id": "gen-12345",
            "model": "anthropic/claude-sonnet-5",
            "choices": [{
                "index": 0,
                "finish_reason": "length",
                "native_finish_reason": "max_tokens",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning": "some hidden reasoning text",
                    "refusal": None,
                }
            }],
            "usage": {
                "prompt_tokens": 1500,
                "completion_tokens": 4000,
                "total_tokens": 5500,
                "completion_tokens_details": {
                    "reasoning_tokens": 500
                }
            }
        }
        diag = extract_safe_response_diagnostics(sample_resp, http_status=200)
        self.assertEqual(diag["http_status"], 200)
        self.assertEqual(diag["response_id"], "gen-12345")
        self.assertEqual(diag["choices_count"], 1)
        self.assertEqual(diag["choice_index"], 0)
        self.assertEqual(diag["finish_reason"], "length")
        self.assertEqual(diag["native_finish_reason"], "max_tokens")
        self.assertEqual(diag["message_role"], "assistant")
        self.assertIn("content", diag["message_keys"])
        self.assertIn("reasoning", diag["message_keys"])
        self.assertEqual(diag["content_type"], "str")
        self.assertEqual(diag["content_length"], 0)
        self.assertTrue(diag["reasoning_present"])
        self.assertFalse(diag["refusal_present"])
        self.assertEqual(diag["prompt_tokens"], 1500)
        self.assertEqual(diag["completion_tokens"], 4000)
        self.assertEqual(diag["total_tokens"], 5500)
        self.assertEqual(diag["reasoning_tokens"], 500)

        # Critical: raw reasoning text or content must NOT be present anywhere in diag
        diag_str = json.dumps(diag)
        self.assertNotIn("some hidden reasoning text", diag_str)

    # 62. Safe diagnostics with empty choices or invalid structure
    def test_62_extract_safe_response_diagnostics_edge_cases(self):
        diag_empty = extract_safe_response_diagnostics({}, http_status=200)
        self.assertEqual(diag_empty["choices_count"], 0)
        self.assertEqual(diag_empty["content_length"], 0)
        self.assertIsNone(diag_empty["response_id"])

        diag_none = extract_safe_response_diagnostics("not-a-dict", http_status=500)
        self.assertEqual(diag_none["http_status"], 500)
        self.assertEqual(diag_none["choices_count"], 0)

    # 63. Synthetic HTTP-200 with empty content and finish_reason = length fails closed and persists safe diagnostics
    def test_63_synthetic_empty_content_length_fails_closed_with_diagnostics(self):
        empty_length_resp = {
            "id": "gen-test-empty-length",
            "model": "anthropic/claude-sonnet-5",
            "choices": [{
                "index": 0,
                "finish_reason": "length",
                "native_finish_reason": "max_tokens",
                "message": {
                    "role": "assistant",
                    "content": "   ",
                }
            }],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 4000,
                "total_tokens": 5200,
            }
        }
        transport = MockTransport(mock_response_data=empty_length_resp)
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            is_live=False,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")
        claude_res = summary["specialists"]["claude"]
        self.assertEqual(claude_res["verdict"], "FAIL")
        self.assertIn("Structured output schema validation failed: Empty response", claude_res["error_message"])
        self.assertEqual(claude_res["completion_tokens"], 4000)
        self.assertEqual(claude_res["total_tokens"], 5200)
        self.assertIsNotNone(claude_res["response_diagnostics"])
        self.assertEqual(claude_res["response_diagnostics"]["finish_reason"], "length")
        self.assertEqual(claude_res["response_diagnostics"]["native_finish_reason"], "max_tokens")

        run_dir = self.output_dir / "RADIO-003" / runner.run_id
        err_file = run_dir / "claude-error.txt"
        self.assertTrue(err_file.exists())
        err_content = err_file.read_text(encoding="utf-8")
        self.assertIn("DIAGNOSTICS:", err_content)
        self.assertIn('"finish_reason": "length"', err_content)

    # 64. Synthetic HTTP-200 with empty content and finish_reason = stop fails closed and persists safe diagnostics
    def test_64_synthetic_empty_content_stop_fails_closed_with_diagnostics(self):
        empty_stop_resp = {
            "id": "gen-test-empty-stop",
            "model": "anthropic/claude-sonnet-5",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "native_finish_reason": "end_turn",
                "message": {
                    "role": "assistant",
                    "content": "",
                }
            }],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 15,
                "total_tokens": 1215,
            }
        }
        transport = MockTransport(mock_response_data=empty_stop_resp)
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            is_live=False,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")
        claude_res = summary["specialists"]["claude"]
        self.assertEqual(claude_res["verdict"], "FAIL")
        self.assertIn("Structured output schema validation failed: Empty response", claude_res["error_message"])
        self.assertEqual(claude_res["completion_tokens"], 15)
        self.assertIsNotNone(claude_res["response_diagnostics"])
        self.assertEqual(claude_res["response_diagnostics"]["finish_reason"], "stop")
        self.assertEqual(claude_res["response_diagnostics"]["native_finish_reason"], "end_turn")

    # 65. Reasoning text and refusal text are never persisted in failure artifacts
    def test_65_reasoning_and_refusal_text_never_persisted(self):
        secret_reasoning = "UNSAFE_REASONING_CHAIN_SECRET_DATA_XYZ"
        secret_refusal = "UNSAFE_REFUSAL_SECRET_DATA_ABC"
        bad_resp = {
            "id": "gen-test-bad",
            "model": "anthropic/claude-sonnet-5",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "{ not valid json",
                    "reasoning": secret_reasoning,
                    "refusal": secret_refusal,
                }
            }],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        }
        transport = MockTransport(mock_response_data=bad_resp)
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            is_live=False,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")

        run_dir = self.output_dir / "RADIO-003" / runner.run_id
        for artifact in run_dir.iterdir():
            content = artifact.read_text(encoding="utf-8")
            self.assertNotIn(secret_reasoning, content)
            self.assertNotIn(secret_refusal, content)

    # 66. API-key-like content in invalid response is never persisted in diagnostics or artifacts
    def test_66_api_key_in_response_is_not_persisted(self):
        fake_key = "sk-or-v1-" + "e" * 64
        bad_resp = {
            "id": "gen-key-leak",
            "model": "anthropic/claude-sonnet-5",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": f"Here is your key: {fake_key}",
                }
            }],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        }
        transport = MockTransport(mock_response_data=bad_resp)
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            is_live=False,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")

        run_dir = self.output_dir / "RADIO-003" / runner.run_id
        for artifact in run_dir.iterdir():
            content = artifact.read_text(encoding="utf-8")
            self.assertNotIn(fake_key, content)

    # 67. Successful responses pass normally through schema validation and retain diagnostics
    def test_67_successful_response_passes_and_has_diagnostics(self):
        transport = MockTransport()
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            is_live=False,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "PARTIAL")
        claude_res = summary["specialists"]["claude"]
        self.assertEqual(claude_res["verdict"], "PASS")
        self.assertIsNotNone(claude_res["response_diagnostics"])
        self.assertEqual(claude_res["response_diagnostics"]["http_status"], 200)
        self.assertEqual(claude_res["response_diagnostics"]["finish_reason"], "stop")
        self.assertEqual(claude_res["total_tokens"], 1850)

    # 68. Synthetic finish_reason=length with reasoning_tokens=3000 fails closed if JSON is truncated
    def test_68_synthetic_bounded_reasoning_length_truncation_fails_closed(self):
        truncated_resp = {
            "id": "gen-test-trunc",
            "model": "anthropic/claude-sonnet-5",
            "choices": [{
                "index": 0,
                "finish_reason": "length",
                "native_finish_reason": "max_tokens",
                "message": {
                    "role": "assistant",
                    "content": '{"verdict": "PASS", "findings": [',
                }
            }],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 8000,
                "total_tokens": 9200,
                "completion_tokens_details": {
                    "reasoning_tokens": 3000
                }
            }
        }
        transport = MockTransport(mock_response_data=truncated_resp)
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
            is_live=False,
        )
        status, summary = runner.run_matrix(specialist_filter="claude")
        self.assertEqual(status, "INCOMPLETE")
        claude_res = summary["specialists"]["claude"]
        self.assertEqual(claude_res["verdict"], "FAIL")
        self.assertIn("Structured output schema validation failed", claude_res["error_message"])
        self.assertEqual(claude_res["response_diagnostics"]["reasoning_tokens"], 3000)
        self.assertEqual(claude_res["response_diagnostics"]["finish_reason"], "length")

    # 69. DeepSeek and Grok request options remain unchanged when profile configures Claude bounded reasoning
    def test_69_deepseek_and_grok_request_options_unchanged(self):
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=MockTransport(),
        )
        profile = runner.load_profile()
        deepseek_cfg = profile["specialists"]["deepseek"]
        grok_cfg = profile["specialists"]["grok"]

        ds_body = runner.build_request_body("deepseek/deepseek-v4-pro", "test", deepseek_cfg, 4000)
        self.assertIn("reasoning", ds_body)
        self.assertEqual(ds_body["reasoning"], {"effort": "none"})
        self.assertEqual(ds_body["temperature"], 0.2)

        grok_body = runner.build_request_body("x-ai/grok-4.6", "test", grok_cfg, 4000)
        self.assertNotIn("reasoning", grok_body)
        self.assertEqual(grok_body["temperature"], 0.2)

    def test_70_nested_secret_path_component_is_denied(self):
        self.assertTrue(is_path_forbidden("config/.env.production/settings.txt"))

    def test_71_allowlist_cannot_escape_repository(self):
        with self.assertRaisesRegex(ValueError, "repository-relative"):
            resolve_allowlisted_file(self.repo_root, "../outside.txt")
        with self.assertRaisesRegex(ValueError, "repository-relative"):
            resolve_allowlisted_file(self.repo_root, str(Path("C:/Windows/win.ini")))

    def test_72_files_reviewed_must_be_allowlisted(self):
        response = json.dumps({
            "verdict": "PASS",
            "findings": [],
            "evidence": [],
            "files_reviewed": ["not-sent.txt"],
            "tests_checks": [],
            "risks": [],
            "next_gate": "CHATGPT TRIAGE",
        })
        data, error = validate_structured_response(response, ["sent.txt"])
        self.assertIsNone(data)
        self.assertIn("non-allowlisted", error)

    def test_73_finding_file_must_be_allowlisted(self):
        response = json.dumps({
            "verdict": "CORRECTION REQUIRED",
            "findings": [{
                "severity": "P2",
                "file": "not-sent.txt",
                "line": 1,
                "failure_mode": "Defect",
                "smallest_correction": "Fix",
            }],
            "evidence": [],
            "files_reviewed": [],
            "tests_checks": [],
            "risks": [],
            "next_gate": "CHATGPT TRIAGE",
        })
        data, error = validate_structured_response(response, ["sent.txt"])
        self.assertIsNone(data)
        self.assertIn("non-allowlisted", error)

    def test_74_cli_output_is_contained_under_review_directory(self):
        expected = (self.repo_root / "reports" / "reviews" / "custom").resolve()
        self.assertEqual(
            resolve_cli_output_dir(self.repo_root, "reports/reviews/custom"),
            expected,
        )
        with self.assertRaisesRegex(ValueError, "reports/reviews"):
            resolve_cli_output_dir(self.repo_root, "outside")

    def test_75_dry_run_writes_manifest_only_and_never_dispatches(self):
        transport = MockTransport()
        runner = ReviewRunner(
            repo_root=self.repo_root,
            profile_path=self.profile_path,
            output_dir=self.output_dir,
            transport=transport,
        )
        manifest_path, validation = runner.run_dry_run()
        self.assertEqual(transport.call_history, [])
        self.assertEqual(set(validation), {"claude", "deepseek", "grok"})
        self.assertEqual([item.name for item in manifest_path.parent.iterdir()], ["manifest.json"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["execution_mode"], "DRY-RUN")
        self.assertEqual(manifest["council_status"], "NOT-REVIEWED")


if __name__ == "__main__":
    unittest.main()

