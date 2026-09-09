# Task [TICKET-ID]: [Brief Title]

## Summary
[Provide a clear, 1-3 paragraph description of the problem, feature, or architectural change to be addressed in this ticket.]

## Metadata
- **Ticket ID**: `[e.g., OS-003, OS-004, RADIO-001]`
- **Status**: `[DRAFT / READY / IN_PROGRESS / IN_REVIEW / DONE / BLOCKED]`
- **Assignee**: `[Agent or Human Name]`
- **Component**: `[e.g., catalog, radio, infrastructure, ingestion, rights]`
- **Parent Ticket / Milestone**: `[e.g., OS-001]`
- **Target Completion**: `[Phase / Date]`

---

## Background & Context
[Explain why this work is needed, relevant ADRs, and technical prerequisites. Reference PROJECT.md and DECISIONS.md where applicable.]

---

## Scope & Deliverables
- [ ] Deliverable 1: [Specific file, feature, or schema change]
- [ ] Deliverable 2: [Specific script, component, or test]
- [ ] Deliverable 3: [Documentation update]

### Out of Scope (Explicit Non-Goals)
- [Explicitly list what must NOT be done in this ticket to prevent scope creep.]

---

## Technical Approach & Architecture Constraints
- **Canonical Model Alignment**: [How does this work interact with the canonical database?]
- **Identity Handling**: [Verify compliance with immutable internal ID principles (AST-WRK-XXXXXX / AST-REC-XXXXXX / AST-REL-XXXXXX).]
- **Hot Path Safety**: [Confirm zero synchronous AI calls in live broadcast hot paths.]
- **Cross-Platform Compatibility**: [Specify Linux VPS vs. Windows dev requirements.]

---

## Human Approval Requirements
Does this ticket trigger any gates from [AGENTS.md](file:///c:/AI-PROJECTS/astrazit-music-os/AGENTS.md)?
- [ ] GATE-01: Destructive actions / file deletions (>5 files)
- [ ] GATE-02: Production deployment / public release
- [ ] GATE-03: Cloud resource creation / billing impact
- [ ] GATE-04: Major architectural changes
- [ ] GATE-05: Incompatible database schema changes
- [ ] GATE-06: Rights, ownership, or PRO records
- [ ] GATE-07: YouTube Content ID allowlist changes
- [ ] GATE-08: Financial or payout data
- [ ] GATE-09: Production secrets or credential rotations

---

## Acceptance Criteria
- [ ] AC-1: [Specific, objectively verifiable acceptance test]
- [ ] AC-2: [Automated test passes with output evidence]
- [ ] AC-3: [Documentation and ADRs updated]
- [ ] AC-4: [Security check: zero secrets or credentials committed]
- [ ] AC-5: [Structured task report submitted and human approval obtained]

---

## Verification & Test Plan
```bash
# Provide specific validation and test commands
pytest tests/path/to/test.py
git status
```

---

## Task Execution Report (To be completed upon ticket conclusion)
```markdown
### STATUS
[PASS / PARTIAL / BLOCKED]

### CHANGED
- [List of files]

### TESTS
- [Command results]

### RISKS
- [Identified risks]

### NOT DONE
- [Deferred items]

### NEXT
- [Next ticket recommendation]
```
