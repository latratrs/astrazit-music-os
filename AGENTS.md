# AGENTS.md — Agent Governance & Operating Charter

This document governs the operational behavior, constraints, and authority boundaries of all AI coding agents working within the **AstraZit Music OS** repository.

---

## 1. Core Operating Hierarchy

All agents must adhere to the four-tier governance model:

$$\text{DATABASE} = \text{truth} \quad\vert\quad \text{CODE} = \text{execution} \quad\vert\quad \text{AI} = \text{reasoning} \quad\vert\quad \text{HUMAN} = \text{gatekeeper}$$

- **AI is reasoning, never authority**: AI-generated metadata, summaries, tags, or suggestions must never silently overwrite or become canonical records.
- **Fact vs. Assumption**: Agents must explicitly distinguish verified facts (backed by code, file contents, or test runs) from assumptions or conjectures.

---

## 2. Mandatory Agent Responsibilities

Prior to and during any task execution, agents MUST:

1. **Read Foundational Context**: Read [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md), [AGENTS.md](file:///c:/AI-PROJECTS/astrazit-music-os/AGENTS.md), and relevant [DECISIONS.md](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md) before undertaking non-trivial modifications.
2. **Strict Scope Confinement**: Operate strictly within the boundaries defined in the active ticket or prompt. Never implement speculative features, future ticket scopes, or unrequested refactors.
3. **Inspect Before Modifying**: Inspect existing files, interfaces, and directory trees before writing code or making edits.
4. **Execute Validation**: Run relevant tests, lint checks, or dry runs to verify changes before marking work as complete.
5. **Report Thoroughly**: Conclude every task using the mandatory reporting format detailed below.

---

## 3. Human Approval Gates (Non-Negotiable)

Agents **MUST NOT** proceed without explicit, documented human approval when encountering any of the following operations:

| Gate | Category | Threshold / Description |
| :--- | :--- | :--- |
| **GATE-01** | **Destructive Actions** | Any irreversible operation, database drops/truncates, or deleting more than five (5) files at once. |
| **GATE-02** | **Deployments** | Any production deployment, DNS change, or release cut. |
| **GATE-03** | **Cloud Billing** | Provisioning paid Google Cloud resources, enabling billable APIs, creating VMs, or allocating external IPs. |
| **GATE-04** | **Architecture** | Major architectural modifications or introduction of new core external dependencies/frameworks. |
| **GATE-05** | **Schema Migrations** | Incompatible database schema changes, destructive column drops, or breaking type alterations. |
| **GATE-06** | **Rights & Ownership** | Modifying song ownership splits, master rights, publishing metadata, or PRO registrations. |
| **GATE-07** | **Content ID** | Modifying YouTube Content ID policies, claims, or allowlist entries. |
| **GATE-08** | **Financials** | Reading, editing, or generating financial records, payout data, or banking metadata. |
| **GATE-09** | **Secrets & Security** | Exposing, creating, rotating, or revoking production secrets, private keys, or credentials. |

---

## 4. Broadcast Reliability & AI Boundary

> [!CAUTION]
> **Live Radio Song-Change Hot Path Restriction**
> No LLM, Gemini API, or external network-dependent AI call may be placed in a live radio song-change, track-selection, or audio-rendering hot path without an explicit future Architectural Decision Record approved by a human.
>
> Broadcast playback must be deterministic, offline-capable, and resilient against latency, rate limits, or network failures.

---

## 5. Standard Task Reporting Format

Every agent task execution must terminate with a structured report following this exact format:

```markdown
### STATUS
PASS / PARTIAL / BLOCKED

### CHANGED
- List of modified, created, or deleted files

### TESTS
- Concrete commands executed and output results

### RISKS
- Remaining concerns, edge cases, or potential regressions

### NOT DONE
- Explicit exclusions, deferred work, or out-of-scope items

### NEXT
- Recommended next ticket or immediate next step
```
