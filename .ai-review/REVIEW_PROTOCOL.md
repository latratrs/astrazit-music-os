# REVIEW_PROTOCOL.md — Multi-Model AI Review Protocol

This document defines the review-handoff protocol and multi-model review lifecycle for the **AstraZit Music OS** repository.

The goal is to enable multiple independent AI reviewers (and human gatekeepers) to evaluate changes rigorously, objectively, and efficiently without requiring full conversational history.

---

## 1. Review Lifecycle

```text
TICKET
  ↓
PLAN
  ↓
IMPLEMENT
  ↓
TEST (Local verification & regression checks)
  ↓
REVIEW PACKET (Self-contained context generated in reports/)
  ↓
SPECIALIST REVIEWS (Independent model reviews)
  ↓
CHATGPT TRIAGE (Deduplication, synthesis, priority assessment)
  ↓
FINAL RELEASE GATE WHEN REQUIRED (Codex gate for T3)
  ↓
HUMAN APPROVAL (Non-negotiable gatekeeper)
  ↓
COMMIT / DEPLOY
```

---

## 2. Risk Tiers

Every ticket or change set must be classified into a risk tier, dictating the required review panel:

| Tier | Scope / Characteristics | Review Requirement |
| :--- | :--- | :--- |
| **T0** | Documentation, comments, prose, minor wording fixes | Builder + ChatGPT |
| **T1** | Normal application features, UI tweaks, schema-neutral code | Builder + 1 independent reviewer |
| **T2** | Infrastructure, networking, shell/systemd units, data migrations | Builder + 2 specialist reviewers + ChatGPT |
| **T3** | Secrets, credentials, authentication, payments, production deployment, privileged infrastructure, externally reachable network services | Builder + Specialist Review Council + ChatGPT + Final Codex release gate + Human approval |

> [!IMPORTANT]
> **RADIO-003 is classified as T3** due to RTMPS live streaming, systemd service installation, host process isolation requirements, and runtime secret handling.

---

## 3. Agent Roles

- **ChatGPT**:
  - Chief architect and ticket author.
  - Cross-project integrator.
  - Review finding triage, deduplication, and resolution guidance.
  - Human-facing decision support.
- **Antigravity**:
  - Primary implementation agent.
  - Local test and validation execution.
  - Review packet generation and maintenance.
- **Claude**:
  - Documentation, specification, and acceptance criteria consistency reviewer.
  - Invariant fidelity and drift auditor.
- **DeepSeek**:
  - Code, test, and shell edge-case reviewer.
  - Error handling, environment precedence, and POSIX/bash mechanics.
- **Grok**:
  - Adversarial operational reviewer.
  - System failure modes, recovery assumptions, and unhandled edge cases.
- **Codex**:
  - Scarce final independent release auditor.
  - Reserved primarily for T3 final release gates.
  - Not an iterative or routine reviewer; operates with token-minimized context.
- **Human**:
  - Sole authority for non-negotiable approval gates (GATE-01 through GATE-09).
  - Supplies runtime secrets, authorizes deployment, and approves commits when gated.

---

## 4. Fallback Policy

Independent specialist reviews require **two (2)** available reviewers from the specialist pool:
- **Claude**
- **DeepSeek**
- **Grok**

1. If one specialist is unavailable, use the remaining two.
2. If fewer than two specialists are available:
   - An independent Antigravity review instance and ChatGPT review may temporarily substitute.
   - However, a **T3 final commit/deployment still requires the configured final release gate (Codex)** unless the human gatekeeper explicitly waives or modifies the policy.

---

## 5. Standard Review Output Format

Every AI reviewer must return findings formatted according to this structure:

```markdown
### VERDICT
PASS / FAIL / CORRECTION REQUIRED

### FINDINGS
For each finding:
- Severity: BLOCKER / P1 / P2 / P3 / NIT
- Location: file:line (when applicable)
- Failure Mode: Concrete description of how it fails or regresses
- Recommended Correction: Smallest necessary change to resolve

### EVIDENCE
Concrete command output, code snippets, or verification results.

### FILES REVIEWED
List of specific repository files inspected.

### TESTS / CHECKS RUN
Concrete verification commands executed by the reviewer (or explicitly stated if inspection only).

### RISKS
Operational, security, or regression concerns.

### NEXT GATE
Recommended handoff or clearance state.
```

### Reviewer Conduct Rules:
- **No speculative findings**: Ground all findings in actual code, shell traces, or documented invariants.
- **Do not rewrite implementation**: Suggest minimal targeted diffs rather than full-file replacements unless assigned as the implementation agent.
- **Avoid duplicate findings**: Focus on novel or unaddressed defects.
- **Distinguish blocking vs. non-blocking**: Clearly separate critical failures from non-blocking polish.
- **Zero secret exposure**: Never output credentials, keys, or sensitive environment tokens.
- **Honest testing claims**: Never claim a test was executed if only static inspection occurred.

---

## 6. Usage-Efficient Review Rules

To maximize efficiency and prevent context-window saturation across multi-model reviews:

1. **Never send full conversation history**: Reviewers must only receive the self-contained Review Packet plus direct repository access.
2. **Targeted specialist prompts**: Reviewer prompts must be scoped to their designated focus domain (e.g. Claude = docs/spec/acceptance, DeepSeek = bash/code/tests, Grok = adversarial operations).
3. **Finding limits**: Return a maximum of 5 high-priority findings per review pass unless additional true blockers exist.
4. **No re-reporting resolved items**: Do not repeat previously resolved findings unless an active regression is detected.
5. **Codex reserved for final T3 gates**: Use Codex only after specialist findings are addressed and triaged.
6. **Review packet maintenance**: Antigravity generates or updates the review packet in `reports/` immediately after completing implementation changes.
7. **Packet is evidence, not authority**: The review packet provides orientation and current status; reviewers must inspect the actual codebase when they have filesystem access.

---

## 7. Automated Specialist Execution (OS-009)

To eliminate manual prompt preparation and enforce strict privacy guardrails during the **SPECIALIST REVIEWS** phase, ticket `OS-009` defines the automation runner (`scripts/review.ps1` / `scripts/review_runner.py`) using OpenRouter:
- **Mandatory Privacy**: Requires Zero Data Retention (`provider: { zdr: true, data_collection: "deny" }`).
- **Deterministic Routing**: Maps roles directly to `anthropic/claude-sonnet-5`, `deepseek/deepseek-v4-pro`, and `x-ai/grok-4.6` without auto-routing.
- **Pre-Send Secret Scanning**: Filters out credentials, tokens, and stream keys before any network egress.
- **Domain Scoping**: Delivers strictly allowlisted files per specialist domain.
See [OS-009.md](file:///c:/AI-PROJECTS/astrazit-music-os/tasks/OS-009.md) and [OPENROUTER_REVIEW_MATRIX.md](file:///c:/AI-PROJECTS/astrazit-music-os/docs/architecture/OPENROUTER_REVIEW_MATRIX.md) for architectural and execution details.
