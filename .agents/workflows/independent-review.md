# Workflow: Independent Review

This workflow defines the protocol for conducting an adversarial, objective, second-opinion review of work completed by an implementation agent before changes are presented for human sign-off.

---

## 1. Review Objectives
The reviewer agent or review phase must verify that:
1. **Scope Integrity**: The implementation did not exceed the ticket scope or perform unauthorized refactoring.
2. **Governance Compliance**: All rules in [AGENTS.md](file:///c:/AI-PROJECTS/astrazit-music-os/AGENTS.md) and [DECISIONS.md](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md) were strictly respected.
3. **Security Audit**: No secrets, credentials, API keys, or private identifiers were committed or exposed.
4. **Broadcast Hot Path Safety**: No AI, LLM, or synchronous network calls were introduced into live audio or song-change hot paths.
5. **Cross-Platform Cleanliness**: Line endings adhere to `.gitattributes` (LF for Linux/POSIX, CRLF for Windows scripts).
6. **Zero Silent Migrations**: No schema, rights, or identity fields were mutated without formal ADR or human permission.

---

## 2. Review Procedure

### Step 1: Git Diff & Status Inspection
```bash
git status
git diff --staged
git diff
```
Verify that only expected files have been modified or created.

### Step 2: Secret & Security Scan
Check for stray `.env` files, `.key`, `.pem`, or GCP credentials:
```bash
git check-ignore -v .env .env.local id_rsa key.pem service-account.json
```

### Step 3: Test Execution Verification
Re-run or audit the tests reported in the implementation report. Ensure tests actually executed and passed rather than being simulated or mocked without note.

### Step 4: Review Verdict Formulation
The reviewer must issue one of three verdicts:
- **APPROVED**: Work complies with all criteria, test evidence is valid, and ticket is ready for human approval.
- **CHANGES_REQUESTED**: Specific deficiencies identified. Work returns to Step 3 of Ticket Execution.
- **BLOCKED**: Fundamental architectural violation, scope breach, or security issue detected. Requires human intervention.

---

## 3. Review Report Template
```markdown
### REVIEW VERDICT
APPROVED / CHANGES_REQUESTED / BLOCKED

### AUDIT FINDINGS
- Scope check: [PASS / FAIL]
- Security check: [PASS / FAIL]
- Hot path check: [PASS / FAIL]
- Cross-platform formatting: [PASS / FAIL]

### NOTES & RECOMMENDATIONS
[Detailed observations or required fixes]
```
