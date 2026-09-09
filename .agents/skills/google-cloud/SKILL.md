---
name: google-cloud
description: Governs Google Cloud Platform (GCP) infrastructure, Cloud Storage, Secret Manager, Cloud Run, IAM, and project resource standards.
---

# Google Cloud Skill

## 1. Purpose
This skill establishes conventions, architectural patterns, and operational safety rules for Google Cloud Platform services within the `astrazit-music-os` project.

## 2. Activation Context
Activate this skill when:
- Designing or reviewing cloud infrastructure configurations (`infrastructure/google-cloud/`).
- Configuring Google Cloud Storage (GCS) buckets for master audio archives or transcode caches.
- Integrating Secret Manager, Cloud SQL, or Cloud Run services.
- Managing IAM service accounts, roles, and least-privilege policies.

## 3. Constraints
- **Human Approval Required (GATE-03)**: Provisioning paid resources, enabling billable APIs, creating VMs, or altering billing configurations requires explicit human approval.
- **Target Verification**: The repository name does not establish an existing GCP project or gcloud configuration. Confirm the human-approved project ID and configuration before any cloud operation; these are not established by OS-001/OS-002.
- **Zero Hardcoded Credentials**: Service account keys (`.json`), client secrets, or auth tokens must NEVER be stored in the codebase.
- **Scope Restriction**: In tickets OS-001/OS-002, NO cloud resources may be created, altered, or deleted.

## 4. Authoritative References
- [PROJECT.md](file:///c:/AI-PROJECTS/astrazit-music-os/PROJECT.md)
- [AGENTS.md - Human Approval Gates](file:///c:/AI-PROJECTS/astrazit-music-os/AGENTS.md)
- TODO: Cloud Infrastructure Blueprint (`infrastructure/google-cloud/` - to be established)
- TODO: GCS Storage Hierarchy & Lifecycle Policies (to be established)
