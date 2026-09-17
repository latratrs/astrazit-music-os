# Architecture: OpenRouter Specialist Review Matrix (OS-009)

## 1. Executive Summary

This architecture defines the automated, multi-model review harness connecting AstraZit Music OS review protocols with independent AI specialist models via OpenRouter.

The harness automates the Specialist Review stage of the engineering lifecycle:
$$\text{TICKET} \rightarrow \text{PLAN} \rightarrow \text{IMPLEMENT} \rightarrow \text{TEST} \rightarrow \text{REVIEW PACKET} \rightarrow \mathbf{SPECIALIST\ REVIEWS} \rightarrow \text{CHATGPT TRIAGE} \rightarrow \text{CODEX GATE} \rightarrow \text{HUMAN APPROVAL}$$

It guarantees deterministic model selection, strict Zero Data Retention (ZDR), domain file allowlisting, dual-layer local pre-send secret sanitization, machine-validated structured output, and local-only report persistence.

---

## 2. Component Architecture & Data Flow

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Developer Environment (Windows PowerShell 7 / Python >= 3.12 Standard Lib)  │
│                                                                             │
│  User executes: .\scripts\review.ps1 RADIO-003 [-Live]                      │
│         │                                                                   │
│         ▼                                                                   │
│  [Review CLI Wrapper (review.ps1)]                                          │
│    ├─ Resolves Python >= 3.12 (no virtualenv required)                      │
│    └─ Forwards arguments to Python runner                                   │
│         │                                                                   │
│         ▼                                                                   │
│  [Review Matrix Runner (review_runner.py)]                                  │
│    ├─ 1. Load Ticket Review Profile (e.g. RADIO-003)                        │
│    ├─ 2. Dual-Layer Path Deny & Pre-Send Content Scanner ──[Fail Closed]    │
│    ├─ 3. Generate Preflight Manifest (manifest.json)                        │
│    └─ 4. Sequential Specialist Dispatcher:                                  │
│              │                                                              │
│              ├─► Claude Sonnet 5 (HTTP / TLS)                               │
│              │     └─ Local Schema Validation ──► Write Reports to Disk     │
│              │                                                              │
│              ├─► DeepSeek V4 Pro (HTTP / TLS)                               │
│              │     └─ Local Schema Validation ──► Write Reports to Disk     │
│              │                                                              │
│              └─► Grok 4.6 (HTTP / TLS, no reasoning block)                  │
│                    └─ Local Schema Validation ──► Write Reports to Disk     │
└──────────────┼──────────────────────────────────────────────────────────────┘
               │
       (HTTP / TLS, ZDR: true, data_collection: "deny")
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ OpenRouter API (api.openrouter.ai/api/v1/chat/completions)                  │
│   Headers: Authorization: Bearer $OPENROUTER_API_KEY                        │
│   Body Policy: provider: { zdr: true, data_collection: "deny" }             │
│                                                                             │
│   Approved Models (Strict Dispatch, No Auto-Router):                        │
│     - anthropic/claude-sonnet-5                                             │
│     - deepseek/deepseek-v4-pro                                              │
│     - x-ai/grok-4.6                                                         │
└──────────────┬──────────────────────────────────────────────────────────────┘
               │
               ▼ (Immediate per-specialist disk write)
┌─────────────────────────────────────────────────────────────────────────────┐
│ Local Artifact Output (reports/reviews/RADIO-003/<RUN-ID>/ - Gitignored)   │
│   ├─ manifest.json                                                          │
│   ├─ claude-review.json / claude-review.md                                  │
│   ├─ deepseek-review.json / deepseek-review.md                              │
│   ├─ grok-review.json / grok-review.md                                      │
│   └─ run-summary.json                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Privacy Boundary & External Controls

1. **Zero Data Retention (ZDR)**: Every outbound JSON payload must include:
   ```json
   {
     "provider": {
       "zdr": true,
       "data_collection": "deny"
     }
   }
   ```
2. **Deterministic Model Identifiers**:
   - `anthropic/claude-sonnet-5`
   - `deepseek/deepseek-v4-pro`
   - `x-ai/grok-4.6`
   *Auto-router (`openrouter/auto`) or dynamic fallback is strictly prohibited.*
3. **Model Verification on Ingest**: The runner inspects the HTTP response `model` field. If it does not match the requested approved model ID (or an approved canonical alias), the review fails closed.
4. **Secret Isolation**:
   - `OPENROUTER_API_KEY` is loaded from the OS user environment variable only.
   - It is never written to disk, passed via CLI args, printed in stdout, or logged in HTTP diagnostics.
5. **External Controls as Defense-in-Depth**: Observed external OpenRouter controls (workspace guardrails, $5 key limit, $10 workspace limit, allowed models) are operational guardrails, not permanent guarantees. The runner locally enforces all model and privacy rules and fails closed if OpenRouter refuses or cannot satisfy them.

---

## 4. Sequential Dispatch & Fault Tolerance

Specialists are dispatched **sequentially** rather than concurrently:
$$\text{Claude Sonnet 5} \longrightarrow \text{DeepSeek V4 Pro} \longrightarrow \text{Grok 4.6}$$

- **Immediate Persistence**: Each specialist's raw response, normalized JSON, and rendered Markdown are validated and written to disk immediately upon completion before the next model is invoked.
- **Retry Semantics**:
  - Exactly one (1) bounded retry after 2 seconds for transient HTTP 502/503/504 server errors.
  - **Zero retries** for 400, 401, 403, or 429 errors.
- **Fail-Closed Council State**: If any specialist fails, subsequent specialists may be aborted or marked skipped, and the overall council run is marked `INCOMPLETE`. No synthetic or defaulted PASS verdicts are ever emitted.

---

## 5. Model-Specific Request Adapters

Empirical testing confirms different parameter requirements per provider:

1. **Claude Sonnet 5** (RADIO-003 specialist configuration):
   - `max_output_tokens: 8000`
   - `reasoning`: `{"max_tokens": 3000}` (bounded reasoning tokens to handle extended structured thinking without HTTP 404 parameter routing failures or output truncation under `require_parameters: true`)
   - `temperature`: omitted (`temperature` is omitted for Claude Sonnet 5 under `require_parameters: true` compatibility)
2. **DeepSeek V4 Pro**:
   - `temperature: 0.2`, `max_tokens: 4000`
   - Reasoning disabled (`reasoning: {"effort": "none"}`).
3. **Grok 4.6**:
   - `temperature: 0.2`, `max_tokens: 4000`
   - **Omit `reasoning` parameter completely**: Grok 4.6 returns HTTP 400 if `reasoning.effort` is present. The adapter dynamically omits this block for Grok.

---

## 6. Pre-Send Secret Scanner & Path Filtering

The scanner employs a decoupled two-layer validation architecture:

### Layer 1: Path & Filename Deny Rules (Fail-Closed)
Prevents any secret-bearing or environment file from ever entering a payload:
- `*.env*` (e.g., `stream.env`, `.env.production`)
- `*id_rsa*`, `*id_ed25519*`, `*.pem`, `*.key`, `*.pkcs12`, `*.pfx`
- Any credentials store (`credentials.json`, `token.pickle`)

### Layer 2: Content Scanner (Entropy & Semantic Distinction)
Distinguishes real high-entropy secrets from legitimate code and documentation references:

#### Prohibited (Fail-Closed):
- Real OpenRouter API keys: `sk-or-v1-[a-zA-Z0-9]{64}`.
- Exact match of the runtime value of `$env:OPENROUTER_API_KEY`.
- Private key headers: `-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----`.
- Real YouTube stream keys: 4 groups of 4 alphanumeric characters plus a 4-character suffix (e.g., `[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}`).
- Real Bearer tokens: `Authorization:\s*Bearer\s+[A-Za-z0-9\-_\.]{32,}` where the token is not an explicit placeholder.

#### Permitted (Harmless References & Placeholders):
- The literal string `OPENROUTER_API_KEY` in documentation or scripts.
- The prefix `sk-or-v1-` when used in documentation, error strings, or regex patterns.
- `Authorization: Bearer <placeholder>` or `Bearer <token>`.
- `STREAM_KEY=<placeholder>` or `STREAM_KEY=xxxx-xxxx-xxxx-xxxx-xxxx`.
- Mentions, prose explanations, and example snippets referencing `stream.env`.

---

## 7. Machine-Validated Output & Normalization

To eliminate reliance on unstructured free-form Markdown, the runner requires specialist models to output a strict JSON structure, validated locally before acceptance.

### Normalized Output Schema
```json
{
  "verdict": "PASS | CORRECTION REQUIRED | FAIL",
  "findings": [
    {
      "severity": "P0 | P1 | P2 | P3",
      "file": "path/to/file",
      "line": 42,
      "failure_mode": "Concrete description of defect",
      "smallest_correction": "Minimal targeted fix"
    }
  ],
  "evidence": ["Verification evidence or log excerpt"],
  "files_reviewed": ["path/to/inspected/file"],
  "tests_checks": ["Static check or simulation run"],
  "risks": ["Identified operational hazard"],
  "next_gate": "CHATGPT TRIAGE | CODEX RELEASE GATE | HUMAN APPROVAL"
}
```

### Normalization Pipeline:
1. Model response is parsed as JSON.
2. Structure is validated locally against required fields and enum values.
3. Normalized data is saved to `<specialist>-review.json`.
4. Runner renders validated data into a clean, human-readable `<specialist>-review.md` artifact.
5. If parsing or validation fails, sanitized error diagnostics are saved to `<specialist>-error.txt`, the specialist is marked `FAILED`, and the council fails closed. Only sanitized error messages, HTTP status codes, and bounded response diagnostics (token counts, finish reasons, block type flags) are persisted; raw message content, reasoning text, refusal text, or repository material are strictly excluded to prevent credential or prompt leakage.

---

## 8. Report Storage & Version Control Policy

- **Location**: `reports/reviews/<TICKET>/<RUN-ID>/`
- **Default Git Status**: The directory `/reports/reviews/` is gitignored. Raw model outputs, manifests, and ephemeral tokens are not tracked in git.
- **Canonical Records**: Canonical review packets (`reports/<TICKET>-review-packet.md`) and architect triage summaries (`reports/<TICKET>-review-summary.md`) are the only review artifacts deliberately committed to version control following ChatGPT triage and human approval.

---

## 9. Python Runtime Specification

- **Version**: Python `>= 3.12` (forward compatible with newer supported Python versions).
- **Core Dependencies**: Standard library only (`urllib.request`, `json`, `re`, `pathlib`, `hashlib`, `os`, `sys`).
- **Virtual Environment**: **Not required** for MVP. The PowerShell 7 wrapper discovers an appropriate Python >= 3.12 binary on `PATH` or standard locations, validates standard library execution, and fails clearly if no supported interpreter is found.

### 9.1 CLI Execution Modes & Wrapper Semantics
- **Offline / Mock Review (Default)**:
  ```powershell
  .\scripts\review.ps1 RADIO-003
  ```
  Executes offline mock review against `MockTransport` and does **NOT** authorize network dispatch or read `OPENROUTER_API_KEY`.
- **Validation-Only Dry Run**:
  ```powershell
  .\scripts\review.ps1 RADIO-003 --dry-run
  ```
  Validates path allowlists, path deny rules, payload byte sizes, and pre-send content secret scans, generating only a preflight `manifest.json` with zero network dispatch.
- **Explicit Live Network Review**:
  ```powershell
  .\scripts\review.ps1 RADIO-003 -Live
  ```
  Explicit live network review requires the `-Live` switch, loads `OPENROUTER_API_KEY` from the environment, and remains strictly subject to human authorization (GATE-03 / GATE-09).

---

## 10. Governance & Relationship to Human Gatekeeper

- **Role of the Specialist Matrix**: Supplements human and architect review by catching domain-specific blindspots early; it never replaces human approval or the final Codex release gate.
- **Triage Protocol**: ChatGPT triages the raw findings, deduplicates overlapping items, and presents a synthesized action list.
- **Codex Release Gate**: For T3 tickets, Codex executes a final token-minimized release audit.
- **Human Authority**: All deployment, live streaming, commit, and push operations remain governed by human approval (GATE-01 through GATE-09).
