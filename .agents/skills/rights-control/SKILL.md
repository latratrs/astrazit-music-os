---
name: rights-control
description: Governs copyright ownership, PRO registrations, split sheets, Content ID allowlists, and distribution rights for AstraZit works.
---

# Rights Control Skill

## 1. Purpose
This skill enforces strict legal governance, ownership tracking, and licensing safety across all AstraZit musical compositions, sound recordings, and broadcast distributions.

## 2. Activation Context
Activate this skill when:
- Tracking composition ownership, lyricist/composer credits, and publishing rights.
- Managing Performing Rights Organization (PRO) affiliations and work registrations.
- Reviewing split sheets, master recording ownership, and derivative licenses.
- Managing YouTube Content ID policies, claims, disputes, and channel allowlists.
- Preparing distribution metadata packages for DSP delivery.

## 3. Constraints
- **Absolute Human Gatekeeper (GATE-06 & GATE-07)**: Automated agents MUST NOT modify ownership splits, publishing metadata, PRO details, or Content ID policies without explicit human authorization.
- **Zero Silent Edits**: All rights changes must be accompanied by an audit log entry referencing legal source documents.
- **Financial Privacy**: Royalty rates, payout details, and sensitive financial data must remain isolated and protected.

## 4. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [AGENTS.md - Human Approval Gates](file:///c:/AI-PROJECTS/astrazit-music-os/AGENTS.md)
- [DECISIONS.md - ADR-007](file:///c:/AI-PROJECTS/astrazit-music-os/DECISIONS.md)
- TODO: Rights Data Schema Specification (`docs/rights/` - to be established)
- TODO: Content ID Allowlist Registry (`docs/rights/content-id.md` - to be established)
