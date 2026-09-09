# AstraZit Music OS - Core Agent Rules

## Core Operating Principles
- **DATABASE = truth | CODE = execution | AI = reasoning | HUMAN = gatekeeper**
- Never promote AI-generated metadata directly to canonical catalog state.
- Never place LLM or external AI API calls inside live broadcast song-change hot paths.
- All rights, publishing, PRO registrations, split sheets, and Content ID allowlists require human approval.

## Execution Rules
- Always read `PROJECT.md`, `AGENTS.md`, and `DECISIONS.md` before making architectural or catalog modifications.
- Enforce LF line endings for Linux/runtime files (.sh, .liq, .service, .conf, .py, .json, .yaml, .yml, .md, .sql).
- Never commit secrets, service account keys, or environment files containing real credentials.
- Conclude every task with the standard structured report (`STATUS`, `CHANGED`, `TESTS`, `RISKS`, `NOT DONE`, `NEXT`).
