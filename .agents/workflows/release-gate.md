# Workflow: Release Gate

This workflow defines the mandatory verification gates and approval checkpoints required before any commit, release, tag, or deployment is authorized within AstraZit Music OS.

---

## 1. Release Gating Hierarchy

No release or production modification can bypass the **Release Gate**:

$$\text{AUTOMATED CHECKS} \longrightarrow \text{INDEPENDENT AUDIT} \longrightarrow \text{HUMAN SIGN-OFF} \longrightarrow \text{RELEASE EXECUTION}$$

---

## 2. Checkpoints

### Gate 1: Automated Sanity Checks
- [ ] Working tree is clean except for intentional, scoped changes.
- [ ] All unit and integration tests pass cleanly with zero ignored failures.
- [ ] Linters and formatters report zero errors.
- [ ] `.gitattributes` compliance verified (no unintended CRLF in runtime files).
- [ ] `.gitignore` verification: No secret, log, or build file is tracked.

### Gate 2: Security & Credentials Check
- [ ] No private keys (`*.pem`, `*.key`), tokens, or service account files are present in the git tree.
- [ ] Environment variable files adhere strictly to `.env.example` sanitization.
- [ ] No secrets are logged or embedded in commit messages.

### Gate 3: Governance & Legal Integrity
- [ ] No unapproved changes to rights, ownership, PRO details, or split sheets (GATE-06).
- [ ] No modifications to YouTube Content ID allowlists without explicit sign-off (GATE-07).
- [ ] No unpromoted AI metadata written to canonical catalog tables (ADR-005).
- [ ] Broadcast hot path remains free of non-deterministic LLM/API dependencies (ADR-006).

### Gate 4: Human Sign-Off (MANDATORY)
- [ ] Explicit approval granted by project owner for commit, tag, or deployment.
- [ ] Release notes or ticket summary verified by the human gatekeeper.

---

## 3. Post-Approval Release Action
Once all four gates are satisfied:
1. Stage verified files: `git add <files>`
2. Format commit message with ticket ID and structured description:
   ```
   [TICKET-ID] Concise imperative summary

   - Detail 1
   - Detail 2

   Approved-by: Human Gatekeeper
   ```
3. Create signed tag if executing a semantic release: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
4. Push to remote only if authorized by ticket instructions.
