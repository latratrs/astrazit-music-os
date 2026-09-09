# Workflow: Ticket Execution

This document details the step-by-step procedure for executing any development or architectural task in the AstraZit Music OS project.

---

## The Standard Task Lifecycle

Every ticket follows this strict lifecycle:

$$\text{TICKET} \longrightarrow \text{PLAN} \longrightarrow \text{IMPLEMENT} \longrightarrow \text{TEST} \longrightarrow \text{REPORT} \longrightarrow \text{INDEPENDENT REVIEW} \longrightarrow \text{HUMAN APPROVAL} \longrightarrow \text{COMMIT / DEPLOY}$$

---

## 1. Step 1: Ticket Ingestion & Context Reading
- Retrieve or open the ticket definition (e.g., `tasks/OS-XXX.md`).
- Review core governance:
  - [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
  - [AGENTS.md](file:///c:/AI-PROJECTS/astrazit-music-os/AGENTS.md)
  - Relevant records in [DECISIONS.md](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md)
- Verify working directory, branch, and clean git state.

---

## 2. Step 2: Implementation Plan
- If the task is non-trivial or alters architecture/data:
  - Formulate an explicit implementation plan covering proposed file changes, dependency impacts, and verification criteria.
  - Present the plan for review and verify no human approval gates (e.g., GATE-01 through GATE-09) are breached.

---

## 3. Step 3: Implementation
- Inspect existing files before editing or adding new files.
- Adhere strictly to ticket scope. Do not fix unrelated issues or build unrequested features.
- Preserve cross-platform file format guidelines (enforce LF for runtime/docs, CRLF for Windows scripts).
- Never hardcode credentials, secrets, or platform keys.

---

## 4. Step 4: Verification & Testing
- Run automated tests, linters, or schema validators.
- Inspect file system changes using `git status` and `git diff`.
- Ensure no untracked secrets, build artifacts, or temporary files remain.

---

## 5. Step 5: Structured Task Report
- Conclude execution with the standard report:
  - **STATUS**: `PASS`, `PARTIAL`, or `BLOCKED`
  - **CHANGED**: Concrete list of files modified, created, or deleted
  - **TESTS**: Commands executed and verification output
  - **RISKS**: Identified risks, assumptions, or edge cases
  - **NOT DONE**: Explicit exclusions and deferred scope
  - **NEXT**: Recommended subsequent ticket or action

---

## 6. Step 6: Independent Review & Human Approval
- Invoke [Independent Review Workflow](file:///c:/AI-PROJECTS/astrazit-music-os/.agents/workflows/independent-review.md) for every ticket before human approval.
- Present findings to the human operator and pause execution.
- **NEVER** commit or deploy autonomously unless explicit human approval has been granted.
