# Security Review Template

**Reviewer Role**: Security / Operations Specialist Reviewer  
**Focus Area**: Secrets, credential leakage, environment variable isolation, shell tracing, journal logs, subprocess handling, file permissions, systemd sandboxing, networking, process isolation (`/proc`), fail-open behavior, and production safety.

---

### VERDICT
[PASS / CORRECTION REQUIRED / FAIL]

### FINDINGS
<!-- Focus on secrets, leak paths, permission boundaries, and isolation. Maximum 5 findings unless blocking. -->

- **[Severity: BLOCKER / P1 / P2 / P3 / NIT]** `path/to/file:line`
  - **Failure Mode**: 
  - **Smallest Recommended Correction**: 

### EVIDENCE
<!-- Shell output, leak demonstration, permission checks, or log audits. Zero secret values. -->

### FILES REVIEWED
- `path/to/file1`
- `path/to/file2`

### TESTS / CHECKS RUN
<!-- Commands run (e.g. bash -n, leak simulations, permission checks). -->
- `command executed` -> `result`

### RISKS
<!-- Unprivileged exposure, host trust boundary assumptions, network egress hazards. -->

### NEXT GATE
[CHATGPT TRIAGE / RELEASE GATE / HUMAN APPROVAL]
