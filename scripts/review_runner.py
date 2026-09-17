"""OpenRouter Specialist Review Matrix Automation Core.

OS-009 implementation:
- Pure Python >= 3.12 standard library only.
- Strict path deny rules and two-layer content secret scanning.
- Robust OpenRouter key detection (prefix + realistic length + placeholder exemption).
- Sequential specialist dispatch (Claude -> DeepSeek -> Grok).
- Model-specific request body adaptation (omitting reasoning for Grok).
- provider.require_parameters = true and provider.zdr / data_collection enforcement.
- Local schema validation on structured specialist responses.
- Path traversal prevention for finding file references.
- Zero credential leakage on HTTP error bodies or raw responses.
- Transport abstraction with fail-closed offline/dry-run defaults.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple
import urllib.error
import urllib.request
import uuid

# Approved Model Identifiers
APPROVED_MODELS = {
    "claude": "anthropic/claude-sonnet-5",
    "deepseek": "deepseek/deepseek-v4-pro",
    "grok": "x-ai/grok-4.6",
}

# Accepted Canonical Aliases
APPROVED_MODEL_ALIASES = {
    "anthropic/claude-sonnet-5": ["anthropic/claude-sonnet-5"],
    "deepseek/deepseek-v4-pro": ["deepseek/deepseek-v4-pro"],
    "x-ai/grok-4.6": ["x-ai/grok-4.6"],
}

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str
    file: str
    line: int
    failure_mode: str
    smallest_correction: str


@dataclass
class SpecialistResult:
    specialist: str
    model_requested: str
    model_returned: str
    verdict: str
    findings: List[Finding] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    files_reviewed: List[str] = field(default_factory=list)
    tests_checks: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    next_gate: str = "CHATGPT TRIAGE"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    http_status: Optional[int] = None
    request_id: Optional[str] = None
    error_message: Optional[str] = None
    response_diagnostics: Optional[Dict[str, Any]] = None


@dataclass
class FileManifestItem:
    path: str
    bytes: int
    sha256: str


@dataclass
class ReviewManifest:
    run_id: str
    ticket: str
    risk_tier: str
    timestamp: str
    execution_mode: str  # "DRY-RUN" | "MOCK-REVIEW" | "REAL-REVIEW" | "OFFLINE-REVIEW"
    review_scope: str = "FULL-COUNCIL"  # "FULL-COUNCIL" | "SINGLE-SPECIALIST" | "SINGLE-SPECIALIST / SMOKE"
    required_specialists: List[str] = field(default_factory=list)
    invoked_specialists: List[str] = field(default_factory=list)
    council_status: str = "PENDING"
    specialists: Dict[str, Any] = field(default_factory=dict)
    files_included: List[Dict[str, Any]] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Path Deny & Content Secret Scanner
# -----------------------------------------------------------------------------

FORBIDDEN_FILE_PATTERNS = [
    re.compile(r"^.*\.env.*$", re.IGNORECASE),
    re.compile(r"^.*id_rsa.*$", re.IGNORECASE),
    re.compile(r"^.*id_ed25519.*$", re.IGNORECASE),
    re.compile(r"^.*\.pem$", re.IGNORECASE),
    re.compile(r"^.*\.key$", re.IGNORECASE),
    re.compile(r"^.*\.pkcs12$", re.IGNORECASE),
    re.compile(r"^.*\.pfx$", re.IGNORECASE),
    re.compile(r"^.*credentials\.json$", re.IGNORECASE),
    re.compile(r"^.*token\.pickle$", re.IGNORECASE),
]

# Prohibited actual high-entropy secrets
PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
# Check 2: Flexible OpenRouter key detection (sk-or-v1- followed by 32 to 128 chars)
OPENROUTER_KEY_FLEXIBLE_PATTERN = re.compile(r"\bsk-or-v1-([a-zA-Z0-9]{32,128})\b")
REAL_STREAM_KEY_PATTERN = re.compile(r"\b[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}\b")
BEARER_TOKEN_PATTERN = re.compile(r"Authorization:\s*Bearer\s+([A-Za-z0-9\-_\.]{32,})", re.IGNORECASE)
ASSIGNMENT_SECRET_PATTERN = re.compile(r"\b(password|token|secret)\s*=\s*['\"]([A-Za-z0-9!@#$%^&*()_+\-=]{16,})['\"]", re.IGNORECASE)

# Allowed placeholder strings & documented phrases
ALLOWED_PLACEHOLDERS = [
    "<placeholder>",
    "<token>",
    "<STREAM_KEY>",
    "<stream-key>",
    "xxxx-xxxx-xxxx-xxxx-xxxx",
    "sk-or-v1-placeholder",
    "placeholder",
]


def is_path_forbidden(relative_path: str) -> bool:
    """Check if the path/filename violates strict path deny rules."""
    for component in Path(relative_path).parts:
        for pattern in FORBIDDEN_FILE_PATTERNS:
            if pattern.match(component):
                return True
    return False


def resolve_allowlisted_file(repo_root: Path, relative_path: str) -> Path:
    """Resolve one allowlisted regular file while containing it within the repository."""
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Allowlisted path must be repository-relative: {relative_path!r}")
    root = repo_root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"Allowlisted path escapes the repository: {relative_path!r}"
        ) from error
    if not resolved.is_file():
        raise FileNotFoundError(f"Allowlisted file not found in repository: {relative_path}")
    return resolved


def resolve_cli_output_dir(repo_root: Path, output_arg: str) -> Path:
    """Contain CLI artifacts beneath the repository's ignored review directory."""
    root = repo_root.resolve()
    base = (root / "reports" / "reviews").resolve()
    candidate_arg = Path(output_arg)
    candidate = (
        candidate_arg.resolve()
        if candidate_arg.is_absolute()
        else (root / candidate_arg).resolve()
    )
    try:
        candidate.relative_to(base)
    except ValueError as error:
        raise ValueError("review output must remain beneath reports/reviews") from error
    return candidate


def scan_content_for_secrets(content: str, runtime_key: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Inspect in-memory content for realistic credentials.

    Distinguishes high-entropy secrets from legitimate placeholders and documentation.
    Returns (is_safe, failure_reason).
    """
    if not content:
        return True, None

    # 1. In-memory check against actual runtime key (if provided)
    if runtime_key and len(runtime_key.strip()) >= 16:
        if runtime_key in content:
            return False, "Payload contains the runtime API key in plaintext"

    # 2. OpenRouter API key detection (Check 2: realistic range 32-128 chars, placeholder exempt)
    for match in OPENROUTER_KEY_FLEXIBLE_PATTERN.finditer(content):
        suffix = match.group(1)
        if not any(ph in suffix for ph in ALLOWED_PLACEHOLDERS):
            return False, "Payload contains an OpenRouter-key-shaped credential (sk-or-v1-...)"

    # 3. Private key blocks
    if PRIVATE_KEY_HEADER.search(content):
        return False, "Payload contains a private key header"

    # 4. Realistic YouTube stream key (4x4 + 4 chars, excluding documented placeholder xxxx...)
    for match in REAL_STREAM_KEY_PATTERN.finditer(content):
        candidate = match.group(0)
        if candidate not in ALLOWED_PLACEHOLDERS and "xxxx" not in candidate:
            return False, "Payload contains a high-entropy stream key matching pattern"

    # 5. Active Bearer credentials
    for match in BEARER_TOKEN_PATTERN.finditer(content):
        token_candidate = match.group(1)
        if not any(ph in token_candidate for ph in ALLOWED_PLACEHOLDERS):
            if len(token_candidate) >= 32 and not token_candidate.startswith("<"):
                return False, "Payload contains an active Bearer credential token"

    # 6. Hardcoded high-entropy assignment secrets (password=..., token=...)
    for match in ASSIGNMENT_SECRET_PATTERN.finditer(content):
        val = match.group(2)
        if not any(ph in val for ph in ALLOWED_PLACEHOLDERS):
            return False, f"Payload contains an assigned secret ({match.group(1)}=...)"

    return True, None


def sanitize_text_for_logging(text: str, runtime_key: Optional[str] = None) -> str:
    """Sanitize error messages or headers so no credentials leak to logs or terminal (Check 4)."""
    if not text:
        return ""
    sanitized = text
    if runtime_key and len(runtime_key.strip()) >= 8:
        sanitized = sanitized.replace(runtime_key, "[REDACTED_API_KEY]")
    sanitized = OPENROUTER_KEY_FLEXIBLE_PATTERN.sub("sk-or-v1-[REDACTED]", sanitized)
    sanitized = PRIVATE_KEY_HEADER.sub("-----BEGIN [REDACTED] PRIVATE KEY-----", sanitized)
    sanitized = BEARER_TOKEN_PATTERN.sub("Authorization: Bearer [REDACTED]", sanitized)
    return sanitized


def extract_safe_response_diagnostics(resp_data: Any, http_status: Optional[int] = None) -> Dict[str, Any]:
    """Extract strictly bounded, non-sensitive metadata from an LLM HTTP response.

    Safe metadata extracted:
      - response_id (str)
      - choices_count (int)
      - choice_index (int)
      - finish_reason (str)
      - native_finish_reason (str)
      - message_role (str)
      - message_keys (List[str])
      - content_type (str)
      - content_length (int)
      - content_block_types (List[str] if list)
      - reasoning_present (bool)
      - reasoning_details_present (bool)
      - refusal_present (bool)
      - prompt_tokens (int)
      - completion_tokens (int)
      - total_tokens (int)
      - reasoning_tokens (Optional[int])

    CRITICAL PRIVACY/SECURITY INVARIANTS:
      - NEVER include message content or raw body text.
      - NEVER include reasoning text or refusal text.
      - NEVER include repository content or secret-like material.
    """
    diag: Dict[str, Any] = {
        "http_status": http_status,
        "response_id": None,
        "choices_count": 0,
        "choice_index": None,
        "finish_reason": None,
        "native_finish_reason": None,
        "message_role": None,
        "message_keys": [],
        "content_type": "none",
        "content_length": 0,
        "content_block_types": [],
        "reasoning_present": False,
        "reasoning_details_present": False,
        "refusal_present": False,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": None,
    }

    if not isinstance(resp_data, dict):
        return diag

    if isinstance(resp_data.get("id"), str):
        diag["response_id"] = resp_data.get("id")

    usage = resp_data.get("usage")
    if isinstance(usage, dict):
        diag["prompt_tokens"] = usage.get("prompt_tokens", 0) if isinstance(usage.get("prompt_tokens"), int) else 0
        diag["completion_tokens"] = usage.get("completion_tokens", 0) if isinstance(usage.get("completion_tokens"), int) else 0
        diag["total_tokens"] = usage.get("total_tokens", 0) if isinstance(usage.get("total_tokens"), int) else 0
        
        # Check details for reasoning tokens
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict) and "reasoning_tokens" in details:
            diag["reasoning_tokens"] = details.get("reasoning_tokens")

    choices = resp_data.get("choices")
    if isinstance(choices, list):
        diag["choices_count"] = len(choices)
        if choices and isinstance(choices[0], dict):
            c0 = choices[0]
            diag["choice_index"] = c0.get("index", 0)
            if c0.get("finish_reason") is not None:
                diag["finish_reason"] = str(c0.get("finish_reason"))
            if c0.get("native_finish_reason") is not None:
                diag["native_finish_reason"] = str(c0.get("native_finish_reason"))

            msg = c0.get("message")
            if isinstance(msg, dict):
                diag["message_keys"] = sorted(list(msg.keys()))
                if msg.get("role") is not None:
                    diag["message_role"] = str(msg.get("role"))
                
                diag["reasoning_present"] = bool(msg.get("reasoning"))
                diag["reasoning_details_present"] = bool(msg.get("reasoning_details"))
                diag["refusal_present"] = bool(msg.get("refusal"))

                content = msg.get("content")
                if content is None:
                    diag["content_type"] = "none"
                    diag["content_length"] = 0
                elif isinstance(content, str):
                    diag["content_type"] = "str"
                    diag["content_length"] = len(content)
                elif isinstance(content, list):
                    diag["content_type"] = "list"
                    diag["content_length"] = len(content)
                    block_types = []
                    for blk in content:
                        if isinstance(blk, dict) and "type" in blk:
                            block_types.append(str(blk["type"]))
                        else:
                            block_types.append(type(blk).__name__)
                    diag["content_block_types"] = block_types
                else:
                    diag["content_type"] = type(content).__name__
                    diag["content_length"] = 0

    return diag


# -----------------------------------------------------------------------------
# Structured Schema Validator & Path Traversal Guard
# -----------------------------------------------------------------------------

VALID_VERDICTS = {"PASS", "CORRECTION REQUIRED", "FAIL", "INCOMPLETE"}
VALID_SEVERITIES = {"P0", "P1", "P2", "P3"}


def validate_structured_response(raw_text: str, allowlisted_files: List[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Validate that specialist response is valid JSON conforming to required schema.

    Enforces Check 8: Finding file paths must not use traversal or absolute paths.
    Returns (parsed_dict, error_message).
    """
    if not raw_text or not raw_text.strip():
        return None, "Empty response received from reviewer"

    # Handle potential markdown fence wrapping: ```json ... ```
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"Response is not valid JSON: {exc}"

    if not isinstance(data, dict):
        return None, "Response JSON root must be an object"

    # Required root keys
    required_keys = ["verdict", "findings", "evidence", "files_reviewed", "tests_checks", "risks", "next_gate"]
    for k in required_keys:
        if k not in data:
            return None, f"Missing required response field: '{k}'"

    # Verdict validation
    verdict = str(data["verdict"]).upper().strip()
    if verdict not in VALID_VERDICTS:
        return None, f"Invalid verdict '{verdict}'. Must be one of {sorted(VALID_VERDICTS)}"
    data["verdict"] = verdict

    # Findings validation
    findings = data.get("findings")
    if not isinstance(findings, list):
        return None, "Field 'findings' must be a list"

    p0_p1_count = 0
    parsed_findings = []
    allowlisted_set = set(allowlisted_files)

    for idx, f in enumerate(findings):
        if not isinstance(f, dict):
            return None, f"Finding item {idx} must be an object"
        for field_name in ["severity", "file", "line", "failure_mode", "smallest_correction"]:
            if field_name not in f:
                return None, f"Finding {idx} missing field '{field_name}'"

        # Check 8: Validate file path security
        file_ref = str(f["file"]).strip()
        if ".." in file_ref or file_ref.startswith("/") or re.match(r"^[a-zA-Z]:", file_ref):
            return None, f"Finding {idx} has invalid or unsafe file reference '{file_ref}' (traversal or absolute path prohibited)"
        if file_ref not in allowlisted_set:
            return None, f"Finding {idx} references non-allowlisted file '{file_ref}'"

        line = f["line"]
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            return None, f"Finding {idx} field 'line' must be a positive integer"
        for text_field in ["failure_mode", "smallest_correction"]:
            if not isinstance(f[text_field], str) or not f[text_field].strip():
                return None, f"Finding {idx} field '{text_field}' must be a non-empty string"

        sev = str(f["severity"]).upper().strip()
        if sev not in VALID_SEVERITIES:
            return None, f"Finding {idx} has invalid severity '{sev}'. Must be one of {sorted(VALID_SEVERITIES)}"
        f["severity"] = sev
        if sev in {"P0", "P1"}:
            p0_p1_count += 1
        parsed_findings.append(f)

    # Maximum 5 findings unless extra findings are P0/P1 blockers
    if len(parsed_findings) > 5 and p0_p1_count == 0:
        return None, f"Response contains {len(parsed_findings)} findings (maximum permitted is 5 without blockers)"

    data["findings"] = parsed_findings

    # String list checks
    for list_field in ["evidence", "files_reviewed", "tests_checks", "risks"]:
        if not isinstance(data.get(list_field), list):
            return None, f"Field '{list_field}' must be a list"
        if not all(isinstance(item, str) for item in data[list_field]):
            return None, f"Field '{list_field}' must contain only strings"

    non_allowlisted_reviews = set(data["files_reviewed"]) - allowlisted_set
    if non_allowlisted_reviews:
        return None, (
            "Field 'files_reviewed' contains non-allowlisted paths: "
            f"{sorted(non_allowlisted_reviews)}"
        )

    if not isinstance(data["next_gate"], str) or data["next_gate"] not in {
        "CHATGPT TRIAGE", "CODEX RELEASE GATE", "HUMAN APPROVAL"
    }:
        return None, "Field 'next_gate' has an unsupported value"

    return data, None


# -----------------------------------------------------------------------------
# Transport Layer (Mockable / Real)
# -----------------------------------------------------------------------------

class Transport(Protocol):
    def send_request(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout: int = 60,
    ) -> Tuple[int, Dict[str, Any]]:
        """Send request and return (http_status, response_json)."""
        ...


class UrllibTransport:
    """Real HTTP transport using urllib.request (only used when --live is explicitly given)."""

    def send_request(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout: int = 60,
    ) -> Tuple[int, Dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
                return status, json.loads(raw)
        except urllib.error.HTTPError as err:
            # Check 4: Sanitize error text immediately upon read
            err_body = err.read().decode("utf-8", errors="replace")
            clean_err_body = sanitize_text_for_logging(err_body)
            try:
                err_json = json.loads(clean_err_body)
            except Exception:
                err_json = {"error": clean_err_body}
            return err.code, err_json
        except Exception as err:
            clean_err_msg = sanitize_text_for_logging(str(err))
            return 500, {"error": clean_err_msg}


class MockTransport:
    """Deterministic offline mock transport for Phase 1 verification."""

    def __init__(
        self,
        responses: Optional[Dict[str, Any]] = None,
        fail_status: Optional[int] = None,
        fail_body: Optional[Any] = None,
        mock_response_data: Optional[Dict[str, Any]] = None,
    ):
        self.responses = responses or {}
        self.fail_status = fail_status
        self.fail_body = fail_body
        self.mock_response_data = mock_response_data
        self.call_history: List[Dict[str, Any]] = []

    def send_request(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout: int = 60,
    ) -> Tuple[int, Dict[str, Any]]:
        self.call_history.append({"url": url, "headers": headers, "payload": payload})
        if self.fail_status:
            err_payload = self.fail_body if self.fail_body is not None else {"error": f"Simulated HTTP {self.fail_status}"}
            return self.fail_status, err_payload

        if self.mock_response_data is not None:
            return 200, self.mock_response_data

        model = payload.get("model", "")
        resp_content = self.responses.get(model)
        if resp_content is None:
            # Default compliant response
            resp_content = json.dumps({
                "verdict": "PASS",
                "findings": [],
                "evidence": ["Offline mock inspection passed."],
                "files_reviewed": [],
                "tests_checks": ["Unit test simulation"],
                "risks": [],
                "next_gate": "CHATGPT TRIAGE",
            })

        body = {
            "id": f"mock-{uuid.uuid4().hex[:8]}",
            "model": model,
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": resp_content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1500,
                "completion_tokens": 350,
                "total_tokens": 1850,
            },
        }
        return 200, body


# -----------------------------------------------------------------------------
# Review Runner Core
# -----------------------------------------------------------------------------

class ReviewRunner:
    def __init__(
        self,
        repo_root: Path,
        profile_path: Path,
        output_dir: Path,
        transport: Transport,
        api_key: Optional[str] = None,
        is_live: bool = False,
        is_mock_run: bool = False,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.repo_root = repo_root
        self.profile_path = profile_path
        self.output_dir = output_dir
        self.transport = transport
        self.api_key = api_key
        self.is_live = is_live
        self.is_mock_run = is_mock_run
        self.sleep_fn = sleep_fn
        self.run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    def load_profile(self) -> Dict[str, Any]:
        if not self.profile_path.exists():
            raise FileNotFoundError(f"Review profile not found: {self.profile_path}")
        with open(self.profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
        ticket = profile.get("ticket")
        if not isinstance(ticket, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,63}", ticket):
            raise ValueError("Profile ticket must be an uppercase, path-safe identifier")
        specialists = profile.get("specialists")
        if not isinstance(specialists, dict) or not specialists:
            raise ValueError("Profile must define at least one specialist")
        for name, config in specialists.items():
            if name not in APPROVED_MODELS or not isinstance(config, dict):
                raise ValueError(f"Profile contains unsupported specialist: {name!r}")
            if config.get("model") != APPROVED_MODELS[name]:
                raise ValueError(f"Profile model for {name!r} is not approved")
            allowlist = config.get("allowlist")
            if not isinstance(allowlist, list) or not all(
                isinstance(path, str) and path for path in allowlist
            ):
                raise ValueError(f"Profile allowlist for {name!r} is invalid")
            if len(allowlist) != len(set(allowlist)):
                raise ValueError(f"Profile allowlist for {name!r} contains duplicates")
        return profile

    def assemble_specialist_payload(
        self,
        specialist_cfg: Dict[str, Any],
        max_payload_bytes: int,
    ) -> Tuple[str, List[FileManifestItem], int]:
        """Assemble domain allowlisted files and prompt into a unified content payload.

        Fails closed on path deny rules, missing files, or size exceedance.
        """
        allowlist = specialist_cfg.get("allowlist", [])
        manifest_items: List[FileManifestItem] = []
        assembled_chunks: List[str] = []

        assembled_chunks.append(f"=== SPECIALIST INSTRUCTIONS ===\n{specialist_cfg.get('prompt', '')}\n")

        for rel_path in allowlist:
            if is_path_forbidden(rel_path):
                raise ValueError(f"Path deny rule triggered: '{rel_path}' is a forbidden secret or environment file")

            full_path = resolve_allowlisted_file(self.repo_root, rel_path)

            content_bytes = full_path.read_bytes()
            sha = hashlib.sha256(content_bytes).hexdigest()
            manifest_items.append(FileManifestItem(path=rel_path, bytes=len(content_bytes), sha256=sha))

            text_content = content_bytes.decode("utf-8", errors="replace")
            assembled_chunks.append(f"\n=== FILE: {rel_path} ===\n{text_content}\n")

        full_payload_text = "\n".join(assembled_chunks)
        total_bytes = len(full_payload_text.encode("utf-8"))

        if total_bytes > max_payload_bytes:
            raise ValueError(f"Assembled payload size ({total_bytes} bytes) exceeds limit ({max_payload_bytes} bytes)")

        return full_payload_text, manifest_items, total_bytes

    def build_request_body(
        self,
        model_id: str,
        user_content: str,
        specialist_cfg: Dict[str, Any],
        max_output_tokens: int,
    ) -> Dict[str, Any]:
        """Build request body enforcing strict Zero Data Retention and model-specific quirks.

        Enforces Check 3: provider.zdr = True, provider.data_collection = 'deny',
        and provider.require_parameters = True.
        """
        body: Dict[str, Any] = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": user_content,
                }
            ],
            "max_tokens": max_output_tokens,
            "provider": {
                "zdr": True,
                "data_collection": "deny",
                "require_parameters": True,
            },
        }

        req_opts = specialist_cfg.get("request_options", {})

        # Temperature handling:
        # Default to 0.2 unless explicitly omitted in profile configuration
        # (e.g. Claude Sonnet 5 endpoint compatibility under require_parameters: true)
        if not req_opts.get("omit_temperature", False):
            body["temperature"] = req_opts.get("temperature", 0.2)

        # Reasoning handling:
        # Added only if explicitly defined in specialist request_options (e.g. DeepSeek)
        if "reasoning" in req_opts:
            body["reasoning"] = req_opts["reasoning"]

        return body

    def render_markdown_report(self, specialist_name: str, model: str, data: Dict[str, Any]) -> str:
        """Render validated JSON structure into standardized human-readable Markdown."""
        lines = [
            f"# Specialist Review: {specialist_name.upper()}",
            f"**Model**: `{model}`  ",
            f"**Verdict**: `{data['verdict']}`  ",
            f"**Next Gate**: `{data['next_gate']}`  \n",
            "---",
            "## Findings",
        ]
        findings = data.get("findings", [])
        if not findings:
            lines.append("- *No defects or blockers identified.*")
        else:
            for f in findings:
                lines.append(f"### [{f['severity']}] `{f['file']}:{f['line']}`")
                lines.append(f"- **Failure Mode**: {f['failure_mode']}")
                lines.append(f"- **Smallest Correction**: {f['smallest_correction']}\n")

        lines.append("\n## Evidence")
        for ev in data.get("evidence", []):
            lines.append(f"- {ev}")

        lines.append("\n## Files Reviewed")
        for fr in data.get("files_reviewed", []):
            lines.append(f"- `{fr}`")

        lines.append("\n## Tests / Checks")
        for tc in data.get("tests_checks", []):
            lines.append(f"- {tc}")

        lines.append("\n## Risks")
        for rk in data.get("risks", []):
            lines.append(f"- {rk}")

        return "\n".join(lines) + "\n"

    def execute_specialist(
        self,
        specialist_name: str,
        specialist_cfg: Dict[str, Any],
        max_payload_bytes: int,
        max_output_tokens: int,
    ) -> SpecialistResult:
        """Execute one specialist review with pre-send checks, bounded retry, and schema validation."""
        requested_model = specialist_cfg["model"]
        start_time = time.time()

        # Step 1: Assemble payload
        try:
            payload_text, file_items, total_bytes = self.assemble_specialist_payload(specialist_cfg, max_payload_bytes)
        except Exception as exc:
            return SpecialistResult(
                specialist=specialist_name,
                model_requested=requested_model,
                model_returned="",
                verdict="FAIL",
                error_message=f"Payload assembly failed: {exc}",
                duration_seconds=time.time() - start_time,
            )

        # Step 2: Content secret scan
        is_safe, reason = scan_content_for_secrets(payload_text, runtime_key=self.api_key)
        if not is_safe:
            return SpecialistResult(
                specialist=specialist_name,
                model_requested=requested_model,
                model_returned="",
                verdict="FAIL",
                error_message=f"Pre-send secret scan rejected payload: {reason}",
                duration_seconds=time.time() - start_time,
            )

        # Step 3: Build request body
        request_body = self.build_request_body(requested_model, payload_text, specialist_cfg, max_output_tokens)

        # Live mode safety gate (Check 5)
        if self.is_live and not self.api_key:
            return SpecialistResult(
                specialist=specialist_name,
                model_requested=requested_model,
                model_returned="",
                verdict="FAIL",
                error_message="Live mode requested but OPENROUTER_API_KEY is not set in environment",
                duration_seconds=time.time() - start_time,
            )

        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/astrazit/astrazit-music-os",
            "X-Title": "AstraZit Review Matrix",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Step 4: Dispatch with bounded retry (5xx retries once after 2s; 4xx does not retry)
        http_status, resp_data = self.transport.send_request(OPENROUTER_ENDPOINT, headers, request_body)
        if http_status in {502, 503, 504}:
            self.sleep_fn(2.0)
            http_status, resp_data = self.transport.send_request(OPENROUTER_ENDPOINT, headers, request_body)

        duration = time.time() - start_time

        # Extract safe metadata unconditionally if HTTP status is 200
        safe_diag = extract_safe_response_diagnostics(resp_data, http_status=http_status) if http_status == 200 else None

        # Check 4: HTTP error handling and sanitization
        if http_status != 200:
            raw_err_body = str(resp_data.get("error", "Unknown"))
            clean_err = sanitize_text_for_logging(raw_err_body, runtime_key=self.api_key)
            return SpecialistResult(
                specialist=specialist_name,
                model_requested=requested_model,
                model_returned="",
                verdict="FAIL",
                http_status=http_status,
                error_message=f"HTTP request failed with status {http_status}: {clean_err}",
                duration_seconds=duration,
                response_diagnostics=None,
            )

        # Extract token usage safely from response
        prompt_tokens = safe_diag["prompt_tokens"] if safe_diag else 0
        completion_tokens = safe_diag["completion_tokens"] if safe_diag else 0
        total_tokens = safe_diag["total_tokens"] if safe_diag else 0
        req_id = resp_data.get("id")

        # Step 5: Model return validation
        returned_model = resp_data.get("model", "")
        valid_aliases = APPROVED_MODEL_ALIASES.get(requested_model, [requested_model])
        if returned_model not in valid_aliases:
            return SpecialistResult(
                specialist=specialist_name,
                model_requested=requested_model,
                model_returned=returned_model,
                verdict="FAIL",
                http_status=http_status,
                request_id=req_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                error_message=f"Model mismatch: requested '{requested_model}', got '{returned_model}'",
                duration_seconds=duration,
                response_diagnostics=safe_diag,
            )

        # Step 6: Extract content
        choices = resp_data.get("choices", [])
        if not choices or not isinstance(choices, list):
            return SpecialistResult(
                specialist=specialist_name,
                model_requested=requested_model,
                model_returned=returned_model,
                verdict="FAIL",
                http_status=http_status,
                request_id=req_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                error_message="OpenRouter response choices missing or empty",
                duration_seconds=duration,
                response_diagnostics=safe_diag,
            )

        raw_content = choices[0].get("message", {}).get("content", "")

        # Step 7: Post-receive content secret scan (Check 7: do not persist secrets if model echoed one)
        resp_safe, resp_reason = scan_content_for_secrets(raw_content, runtime_key=self.api_key)
        if not resp_safe:
            return SpecialistResult(
                specialist=specialist_name,
                model_requested=requested_model,
                model_returned=returned_model,
                verdict="FAIL",
                http_status=http_status,
                request_id=req_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                error_message=f"Model response contained unsafe secret-like material: {resp_reason}",
                duration_seconds=duration,
                response_diagnostics=safe_diag,
            )

        # Step 8: Schema validation & Path Traversal Check (Check 8)
        allowlist = specialist_cfg.get("allowlist", [])
        validated_data, val_err = validate_structured_response(raw_content, allowlist)
        if val_err:
            return SpecialistResult(
                specialist=specialist_name,
                model_requested=requested_model,
                model_returned=returned_model,
                verdict="FAIL",
                http_status=http_status,
                request_id=req_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                error_message=f"Structured output schema validation failed: {val_err}",
                duration_seconds=duration,
                response_diagnostics=safe_diag,
            )

        findings_objects = [Finding(**f) for f in validated_data["findings"]]

        return SpecialistResult(
            specialist=specialist_name,
            model_requested=requested_model,
            model_returned=returned_model,
            verdict=validated_data["verdict"],
            findings=findings_objects,
            evidence=validated_data.get("evidence", []),
            files_reviewed=validated_data.get("files_reviewed", []),
            tests_checks=validated_data.get("tests_checks", []),
            risks=validated_data.get("risks", []),
            next_gate=validated_data.get("next_gate", "CHATGPT TRIAGE"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_seconds=duration,
            http_status=http_status,
            request_id=req_id,
            response_diagnostics=safe_diag,
        )

    def run_dry_run(self, specialist_filter: Optional[str] = None) -> Tuple[Path, Dict[str, Any]]:
        """Validate payloads and persist only a non-review manifest; never dispatch."""
        profile = self.load_profile()
        ticket = profile["ticket"]
        specialists_cfg = profile["specialists"]
        if specialist_filter:
            if specialist_filter not in specialists_cfg:
                raise ValueError(f"Unknown specialist '{specialist_filter}' requested")
            dispatch_order = [specialist_filter]
            review_scope = "SINGLE-SPECIALIST"
        else:
            dispatch_order = [
                name for name in ["claude", "deepseek", "grok"]
                if name in specialists_cfg
            ]
            review_scope = "FULL-COUNCIL"

        manifest = ReviewManifest(
            run_id=self.run_id,
            ticket=ticket,
            risk_tier=profile.get("risk_tier", "T1"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            execution_mode="DRY-RUN",
            review_scope=review_scope,
            required_specialists=list(specialists_cfg.keys()),
            invoked_specialists=[],
            council_status="NOT-REVIEWED",
        )
        all_file_items: Dict[str, FileManifestItem] = {}
        validation: Dict[str, Any] = {}
        max_payload_bytes = profile.get("max_payload_bytes", 131072)

        for name in dispatch_order:
            config = specialists_cfg[name]
            payload_text, items, payload_bytes = self.assemble_specialist_payload(
                config, max_payload_bytes
            )
            is_safe, reason = scan_content_for_secrets(payload_text, runtime_key=None)
            if not is_safe:
                raise ValueError(f"Pre-send secret scan rejected {name!r}: {reason}")
            validation[name] = {
                "model_requested": config["model"],
                "status": "VALIDATED-NOT-SENT",
                "file_count": len(items),
                "payload_bytes": payload_bytes,
            }
            manifest.specialists[name] = validation[name]
            for item in items:
                all_file_items[item.path] = item

        manifest.files_included = [asdict(item) for item in all_file_items.values()]
        run_dir = self.output_dir / ticket / self.run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        manifest_path = run_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as output:
            json.dump(asdict(manifest), output, indent=2)
            output.write("\n")
        return manifest_path, validation

    def run_matrix(self, specialist_filter: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """Run the review matrix sequentially: Claude -> DeepSeek -> Grok.

        Persists each result immediately upon completion.
        Returns (council_status, summary_dict).
        """
        profile = self.load_profile()
        ticket = profile.get("ticket", "UNKNOWN")
        risk_tier = profile.get("risk_tier", "T1")
        max_payload_bytes = profile.get("max_payload_bytes", 131072)
        max_output_tokens = profile.get("max_output_tokens", 4000)
        specialists_cfg = profile.get("specialists", {})

        # Required specialists from profile config:
        required_specialists = list(specialists_cfg.keys()) if specialists_cfg else ["claude", "deepseek", "grok"]

        # Sequential dispatch order: Claude -> DeepSeek -> Grok
        if specialist_filter:
            if specialist_filter not in specialists_cfg:
                raise ValueError(f"Unknown specialist '{specialist_filter}' requested")
            dispatch_order = [specialist_filter]
            review_scope = "SINGLE-SPECIALIST / COMPLETION" if self.is_live else "SINGLE-SPECIALIST"
        else:
            dispatch_order = [s for s in ["claude", "deepseek", "grok"] if s in specialists_cfg] or list(specialists_cfg.keys())
            review_scope = "FULL-COUNCIL"

        invoked_specialists = list(dispatch_order)

        run_dir = self.output_dir / ticket / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        execution_mode = "REAL-REVIEW" if self.is_live else ("MOCK-REVIEW" if self.is_mock_run else "OFFLINE-REVIEW")

        # Preflight manifest
        manifest = ReviewManifest(
            run_id=self.run_id,
            ticket=ticket,
            risk_tier=risk_tier,
            timestamp=datetime.now(timezone.utc).isoformat(),
            execution_mode=execution_mode,
            review_scope=review_scope,
            required_specialists=required_specialists,
            invoked_specialists=invoked_specialists,
            council_status="PENDING",
        )

        all_file_items: Dict[str, FileManifestItem] = {}
        for s_name in dispatch_order:
            s_cfg = specialists_cfg.get(s_name, {})
            manifest.specialists[s_name] = {
                "model_requested": s_cfg.get("model"),
                "status": "PENDING",
            }
            # Collect unique files
            for rel_p in s_cfg.get("allowlist", []):
                if not is_path_forbidden(rel_p):
                    fp = resolve_allowlisted_file(self.repo_root, rel_p)
                    b = fp.read_bytes()
                    all_file_items[rel_p] = FileManifestItem(path=rel_p, bytes=len(b), sha256=hashlib.sha256(b).hexdigest())

        manifest.files_included = [asdict(item) for item in all_file_items.values()]
        manifest_path = run_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(asdict(manifest), f, indent=2)

        results: Dict[str, SpecialistResult] = {}
        any_failed = False

        for s_name in dispatch_order:
            s_cfg = specialists_cfg.get(s_name)
            if not s_cfg:
                continue

            s_max_tokens = s_cfg.get("max_output_tokens", s_cfg.get("request_options", {}).get("max_output_tokens", max_output_tokens))
            result = self.execute_specialist(s_name, s_cfg, max_payload_bytes, s_max_tokens)
            results[s_name] = result

            # Immediate persistence per specialist
            json_path = run_dir / f"{s_name}-review.json"
            result_dict = asdict(result)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, indent=2)

            if result.verdict in {"PASS", "CORRECTION REQUIRED", "FAIL"} and not result.error_message:
                md_path = run_dir / f"{s_name}-review.md"
                md_content = self.render_markdown_report(s_name, result.model_requested, result_dict)
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(md_content)

            # Check for failure
            if result.verdict == "FAIL" or result.error_message:
                any_failed = True
                # Record sanitized error in text
                err_path = run_dir / f"{s_name}-error.txt"
                clean_err_msg = sanitize_text_for_logging(str(result.error_message), runtime_key=self.api_key)
                err_lines = [
                    f"ERROR: {clean_err_msg}",
                    f"HTTP STATUS: {result.http_status}",
                ]
                if result.response_diagnostics:
                    err_lines.append("DIAGNOSTICS:")
                    err_lines.append(json.dumps(result.response_diagnostics, indent=2))
                with open(err_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(err_lines) + "\n")

            manifest.specialists[s_name]["status"] = "COMPLETED" if not result.error_message else "FAILED"
            manifest.specialists[s_name]["verdict"] = result.verdict

        if any_failed:
            council_status = "INCOMPLETE"
        elif set(invoked_specialists) >= set(required_specialists):
            council_status = "COMPLETE"
        else:
            council_status = "PARTIAL"

        manifest.council_status = council_status

        # Finalize run-summary.json
        summary = {
            "run_id": self.run_id,
            "ticket": ticket,
            "risk_tier": risk_tier,
            "execution_mode": execution_mode,
            "review_scope": review_scope,
            "required_specialists": required_specialists,
            "invoked_specialists": invoked_specialists,
            "started_at": manifest.timestamp,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "council_status": council_status,
            "specialists": {name: asdict(res) for name, res in results.items()},
        }
        summary_path = run_dir / "run-summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        # Update manifest.json with final statuses
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(asdict(manifest), f, indent=2)

        return council_status, summary


# -----------------------------------------------------------------------------
# CLI Entry Point
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="AstraZit OpenRouter Review Matrix Runner (OS-009)")
    parser.add_argument("ticket", help="Ticket identifier (e.g. RADIO-003)")
    parser.add_argument("--profile", help="Path to profile JSON file")
    parser.add_argument("--specialist", choices=["claude", "deepseek", "grok"], help="Run a specific specialist only")
    parser.add_argument("--output", default="reports/reviews", help="Base output directory")
    parser.add_argument("--live", action="store_true", help="Enable real network egress (requires OPENROUTER_API_KEY)")
    parser.add_argument("--dry-run", action="store_true", help="Assemble payloads and run secret checks without API calls")
    args = parser.parse_args()

    if args.live and args.dry_run:
        parser.error("--live and --dry-run are mutually exclusive")

    repo_root = Path(__file__).resolve().parent.parent
    profile_arg = Path(args.profile) if args.profile else Path(".ai-review") / "profiles" / f"{args.ticket}.json"
    profile_path = profile_arg.resolve() if profile_arg.is_absolute() else (repo_root / profile_arg).resolve()
    try:
        output_dir = resolve_cli_output_dir(repo_root, args.output)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if not profile_path.exists():
        print(f"ERROR: Review profile '{profile_path}' does not exist.", file=sys.stderr)
        return 1

    # Check 5 & 6: Never read OPENROUTER_API_KEY unless --live is explicitly requested
    if args.live:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            print("ERROR: --live mode requires the OPENROUTER_API_KEY environment variable to be set.", file=sys.stderr)
            return 2
        transport: Transport = UrllibTransport()
    else:
        # Check 6: Real key is NOT read in offline or dry-run mode
        api_key = None
        transport = MockTransport()

    runner = ReviewRunner(
        repo_root=repo_root,
        profile_path=profile_path,
        output_dir=output_dir,
        transport=transport,
        api_key=api_key,
        is_live=args.live,
        is_mock_run=(not args.live and not args.dry_run),
    )

    # Check 9: Dry-run validation writes a manifest only; it never dispatches.
    if args.dry_run:
        print(f"[*] DRY-RUN MODE: Validating ticket '{args.ticket}' allowlists, path rules, and pre-send secret scans...")
        try:
            manifest_path, validation = runner.run_dry_run(args.specialist)
            for s_name, result in validation.items():
                print(
                    f"[+] Specialist '{s_name}': {result['file_count']} files, "
                    f"{result['payload_bytes']} bytes, secret scan PASSED."
                )
            print(f"[+] Manifest: {manifest_path}")
            print("[+] Dry-run validation SUCCESSFUL. Mode: DRY-RUN / NOT REVIEWED. Zero network egress occurred.")
            return 0
        except Exception as exc:
            print(f"[-] Dry-run validation FAILED: {exc}", file=sys.stderr)
            return 4

    print(f"[*] Starting OpenRouter specialist review for {args.ticket} (Live={args.live}, RunID={runner.run_id})...")
    status, summary = runner.run_matrix(specialist_filter=args.specialist)
    print(f"[*] Council execution complete. Overall Status: {status}")
    for s_name, s_res in summary.get("specialists", {}).items():
        verdict = s_res.get("verdict", "UNKNOWN")
        err = s_res.get("error_message")
        err_str = f" ({err})" if err else ""
        print(f"    - {s_name}: {verdict}{err_str}")

    return 0 if status in {"COMPLETE", "PARTIAL"} else 1


if __name__ == "__main__":
    sys.exit(main())

