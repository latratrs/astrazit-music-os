# RADIO-003 Review Packet

## Identity
- **Ticket**: RADIO-003 — YouTube Video Stream MVP
- **Risk Tier**: T3 (Secrets, systemd units, host `/proc` isolation, external RTMPS streaming)
- **Branch**: `feat/RADIO-003-youtube-video-stream`
- **Base Commit**: `0ac39fc`

---

## Objective
Establish an end-to-end AstraZit Radio video streaming MVP from the Linux VPS to a private/unlisted YouTube Live event:
- 1280x720, 30 fps, H.264 video (~4 Mbps CBR, 2s keyframe interval).
- AAC stereo audio at 44.1 kHz (~128 kbps).
- Audio supplied by Liquidsoap via loopback HTTP Harbor endpoint.
- Visual loop continuously multiplexed with station audio via FFmpeg.
- Secure RTMPS egress with runtime-only stream key handling, zero git secrets, and hardened process/journal logging.

---

## Architecture
```text
┌────────────────────────────────────────────────────────┐
│ Linux VPS (astrazit service account)                  │
│                                                        │
│  [astrazit-radio.service]                              │
│    Liquidsoap (station.liq)                            │
│      └─ Harbor HTTP endpoint (127.0.0.1:8000/radio.wav)│
│               │                                        │
│               ▼ HTTP Loopback                          │
│  [astrazit-stream.service]                             │
│    FFmpeg Publisher (stream.sh)                        │
│      ├─ Video: generated visual loop (H.264 720p30)   │
│      ├─ Audio: Harbor PCM stream                      │
│      └─ Output: RTMPS (YouTube Live Ingest)            │
└────────────────────────────────────────────────────────┘
```

---

## Trust Boundary

- **TRUSTED**:
  - `root` user on the host.
  - `astrazit` system service account.
  - FFmpeg publisher process running as `astrazit`.
- **UNTRUSTED**:
  - Unrelated local system users on the multi-tenant VPS.
  - Repository readers (public/private git remotes).
  - Unprivileged system log readers (journald / syslog).

> [!WARNING]
> **Accepted Limitation**: Root and same-user (`astrazit`) process inspection may expose secret-bearing `argv` or process memory via `/proc`. `ProtectProc=invisible` and `ProcSubset=pid` in systemd sandbox the service's view outward, but do **not** hide the unit's command-line from other host users unless the host kernel/filesystem mounts `/proc` with `hidepid=2` (or `hidepid=invisible`). We do not claim otherwise.

---

## Security Invariants

1. **Harbor Loopback**: Liquidsoap Harbor binds strictly to `127.0.0.1:8000` (`radio.wav`). It is never exposed on external interfaces.
2. **Runtime Secret Injection**: Stream keys are supplied exclusively via runtime environment variables (`STREAM_KEY`). No production stream key is stored in the repository.
3. **Environment File Hygiene**: Production unit loads `/opt/astrazit-radio/config/stream.env` via `EnvironmentFile=-...` (owned by `astrazit:astrazit`, permissions `0600`). The host `stream.env` is a restricted runtime secret file and is not committed.
4. **No Implicit Config Sourcing**: Neither `apps/radio/stream.sh` nor `scripts/linux/verify_youtube_stream.sh` automatically source production `stream.env`. Test harnesses and manual runs require explicit environment parameters.
5. **No Shell Tracing (`set -x`)**: Tracing is strictly forbidden in secret-handling scripts. Explicit `set +x` guards are positioned before any secret parsing.
6. **Sanitized YouTube Error Handling**: When `STREAM_OUTPUT_MODE="youtube"`, all raw FFmpeg stdout/stderr output is redirected to `/dev/null` (`>/dev/null 2>&1`), preventing URL/key leakage in journald. The script captures the exit code and logs only `ERROR: FFmpeg publisher exited with status <n>.` File output mode retains full stderr diagnostics for local development.
7. **Explicit Live-Test Opt-In**: The verification harness (`scripts/linux/verify_youtube_stream.sh`) runs Stage-A file verification by default and will only attempt YouTube live testing if both `RUN_LIVE_TEST=1` and `STREAM_KEY` are explicitly passed.
8. **Host `/proc` Isolation Prerequisite**: Host setup script validates `hidepid=2` or `hidepid=invisible` in `/proc` mount options prior to deploying `astrazit-stream.service`.
9. **Explicit Operator Activation**: Node setup installs `astrazit-stream.service` but never automatically enables or starts it. Publisher activation is an explicit operator action after reviewing configuration and installing a valid stream key.
10. **Preservation of Existing Configs**: Deploy scripts never overwrite existing `/opt/astrazit-radio/config/stream.env`.

---

## Files Changed

### Status Summary
```text
Modified Existing:
 M .agents/skills/ffmpeg-streaming/SKILL.md
 M .agents/skills/youtube-live/SKILL.md
 M .gitignore
 M apps/radio/station.liq
 M scripts/linux/setup_radio_node.sh

Untracked / New (RADIO-003):
?? apps/radio/stream.sh
?? apps/radio/systemd/astrazit-radio.service.d/20-harbor.conf
?? apps/radio/systemd/astrazit-stream.service
?? docs/architecture/YOUTUBE_VIDEO_STREAM.md
?? scripts/linux/generate_visual_loop.sh
?? scripts/linux/verify_youtube_stream.sh
?? tasks/RADIO-003.md
?? tests/test_radio_youtube_stream.py

Untracked / New (Review Infrastructure):
?? .ai-review/REVIEW_PROTOCOL.md
?? .ai-review/templates/implementation-review.md
?? .ai-review/templates/release-gate.md
?? .ai-review/templates/security-review.md
?? reports/RADIO-003-review-packet.md
```

### Diff Stat against 0ac39fc
```text
 .agents/skills/ffmpeg-streaming/SKILL.md |  27 +++++--
 .agents/skills/youtube-live/SKILL.md     |  20 ++++--
 .gitignore                               |   5 ++
 apps/radio/station.liq                   |   9 ++-
 scripts/linux/setup_radio_node.sh        | 116 +++++++++++++++++++++++++------
 5 files changed, 143 insertions(+), 34 deletions(-)
```

### Significant Behavior by File

- **`.agents/skills/ffmpeg-streaming/SKILL.md`**: Updated logging, stderr suppression, and sanitization standards for streaming pipelines.
- **`.agents/skills/youtube-live/SKILL.md`**: Added trust boundary documentation, `hidepid=2` host prerequisite, and systemd drop-in guidance.
- **`.gitignore`**: Narrowed exclusions to strictly target generated video assets (`/apps/radio/assets/generated/`), `stream.env`, and radio runtimes without blanket ignores.
- **`apps/radio/station.liq`**: Implemented conditional Harbor output (`output.harbor`) on `127.0.0.1:8000/radio.wav` controlled by `RADIO_OUTPUT_MODE`.
- **`scripts/linux/setup_radio_node.sh`**: Installs `20-harbor.conf` drop-in to `/etc/systemd/system/astrazit-radio.service.d/`, creates restricted runtime secret template `/opt/astrazit-radio/config/stream.env` (mode `0600`) if not already present, installs `astrazit-stream.service` without auto-enablement, and validates host `/proc` mount options (`check_host_proc_isolation`).
- **`apps/radio/stream.sh`**: Core muxing and publishing script. Implements strict parameter checking, zero implicit config sourcing, stderr suppression in YouTube mode, and safe exit reporting.
- **`apps/radio/systemd/astrazit-radio.service.d/20-harbor.conf`**: Drop-in overriding `RADIO_OUTPUT_MODE=harbor` while preserving base service file from RADIO-002 intact.
- **`apps/radio/systemd/astrazit-stream.service`**: Systemd unit running `stream.sh` as `astrazit`, with `ProtectSystem=full`, `ProtectHome=true`, `PrivateTmp=true`, and auto-restart policy (`RestartSec=5s`).
- **`scripts/linux/generate_visual_loop.sh`**: Generates a test or production 720p30 H.264 loop conforming to YouTube Live specifications.
- **`scripts/linux/verify_youtube_stream.sh`**: Automated verification test runner covering 10 concrete stages from syntax to muxing, process isolation check, and gated live test.
- **`docs/architecture/YOUTUBE_VIDEO_STREAM.md`**: Architectural document covering data flow, security model, and failure recovery.
- **`tasks/RADIO-003.md`**: Operational status, ticket tracking, and verification matrix.
- **`tests/test_radio_youtube_stream.py`**: 12 automated unit tests covering drop-ins, secret redaction, config isolation, loop parameters, and `/proc` isolation logic.

---

## Previous Independent Findings & Current Resolution

| # | Finding | Previous Codex Status | Current Code Resolution Claim | Verification Status |
| :- | :--- | :--- | :--- | :--- |
| **1** | Production config could override Stage-A file mode | FAIL | Sourcing of `/opt/astrazit-radio/config/stream.env` removed from `stream.sh` and `verify_youtube_stream.sh`. Production systemd relies on `EnvironmentFile`. Tests explicitly pass environment. | **PENDING INDEPENDENT RE-VERIFICATION** |
| **2** | FFmpeg stderr could expose RTMPS key in journal | FAIL | Added `set +x` guards. In YouTube mode, FFmpeg stdout/stderr are redirected to `/dev/null` (`>/dev/null 2>&1`), exit code is checked, and only sanitized status is output. | **PENDING INDEPENDENT RE-VERIFICATION** |
| **3** | `ProtectProc` security claim was incorrect | FAIL | Documented that `ProtectProc` protects the unit internally, not host-wide. Added `check_host_proc_isolation` to `setup_radio_node.sh` to enforce `hidepid=2` before enabling the stream service. | **PENDING INDEPENDENT RE-VERIFICATION** |
| **4** | Production radio service remained dummy instead of Harbor | FAIL | Preserved `RADIO_OUTPUT_MODE=dummy` in base unit; created drop-in `20-harbor.conf` overriding to Harbor mode. Installed by setup script. | **PENDING INDEPENDENT RE-VERIFICATION** |
| **5** | Docs overstated verification/ignore coverage | FAIL | Narrowed `.gitignore` rules. Removed brittle test count assertions. Accurately documented automated Stage-A vs manual/external Stage-B gates. | **PENDING INDEPENDENT RE-VERIFICATION** |

---

## Validation Commands

Reviewers can execute the following validation commands directly:

1. **Focused RADIO-003 Test Suite**:
   ```powershell
   .\.venv\Scripts\python -m unittest tests.test_radio_youtube_stream -v
   ```
2. **Full Regression Test Suite (RADIO-001 / RADIO-002 / RADIO-003)**:
   ```powershell
   .\.venv\Scripts\python -m unittest discover tests
   ```
3. **Python Bytecode Compilation**:
   ```powershell
   .\.venv\Scripts\python -m compileall -q .
   ```
4. **POSIX/Bash Syntax Verification**:
   ```powershell
   bash -n apps/radio/stream.sh scripts/linux/setup_radio_node.sh scripts/linux/generate_visual_loop.sh scripts/linux/verify_youtube_stream.sh
   ```
5. **Whitespace & Git Hygiene**:
   ```powershell
   git diff --check
   git diff --cached --check
   ```
6. **Schema Invariance**:
   ```powershell
   git diff --exit-code 0ac39fc -- packages/schemas
   ```
7. **Working Tree Cleanliness**:
   ```powershell
   git status --short
   ```

---

## Existing Evidence

### Historical Stage-A VPS Evidence (Tested on Ubuntu 24.04.5 LTS, Liquidsoap 2.2.4, FFmpeg 6.1.1):
- Generated H.264 1280x720 30fps visual loop: **PASS**
- Staged `station.liq` Harbor HTTP loopback endpoint: **PASS**
- Local FFmpeg audio/video muxing: **PASS**
- H.264 4 Mbps CBR / AAC 44.1kHz stereo audio: **PASS**
- Visual loop boundary continuity: **PASS**
- Transient Harbor outage and reconnect: **PASS**
- Automated verifier exit code 0: **PASS**
- `systemd-analyze verify`: **PASS**

### Fresh Corrected Stage-A VPS Evidence (Ubuntu 24.04.5 LTS, kernel 6.8.0-139, systemd 255):
- Verified persistent host `/proc` isolation: `hidepid=invisible` (`hidepid=2`): **PASS**
- Empirical unprivileged cross-user `/proc` masking: **PASS**
- Toolchain validation (Liquidsoap 2.2.4, FFmpeg/ffprobe 6.1.1): **PASS**
- Harbor HTTP loopback readiness (`127.0.0.1:8000/radio.wav`): **PASS**
- 1280x720 30fps visual loop generation and boundary continuity (750 frames): **PASS**
- Local muxing (H.264 CBR 4Mbps, AAC 128kbps, -20.8 dB audio): **PASS**
- Transient Harbor interruption and reconnect recovery: **PASS**
- Complete cgroup process termination on stop (no orphan FFmpeg): **PASS**
- Complete cgroup process termination on restart: **PASS**
- STREAM_KEY fail-closed runtime validation before launch: **PASS**
- Automated verifier `verify_youtube_stream.sh` exit code 0: **PASS**

### Focused Post-T3 Activation Validation Evidence (Ubuntu 24.04.5 LTS):
- Isolated behavioral test harness executed 8 representative configurations: **PASS**
- Zero publisher enablement attempted across empty, quoted, whitespace, duplicate, and non-empty keys: **PASS**
- Zero publisher start attempted: **PASS**
- Systemd `daemon-reload` observed: **PASS**
- Final Codex T3 re-review verdict: **PASS (Previous P1 Resolved, Release-blocking findings: None)**

---

## External Gates Status

1. **Host `/proc` Isolation (GATE-01 / GATE-04)**: **PASSED** (Persisted in `/etc/fstab` with `hidepid=2`).
2. **Fresh Stage-A VPS Retest**: **PASSED** (All 10 verification steps and cgroup lifecycle passed).
3. **Focused Activation-Only Host Validation**: **PASSED** (Isolated harness and static audit verified zero auto-enablement).
4. **Final T3 Release Gate (Codex)**: **PASSED** (Release-blocking findings: NONE).
5. **Human Approval / Commit Gate**: **READY** (Awaiting human approval to commit to git).
6. **Private/Unlisted YouTube Stage-B Test (GATE-02 / GATE-09)**: Post-commit gate; supply valid `STREAM_KEY` via runtime secret and verify 30–60 minute private broadcast ingest health in YouTube Live Studio.
7. **Production Deployment & Extended Soak (24h/72h)**: Post-commit gate; explicit operator service enablement and soak verification.

---

## Specialist Review Questions

- **Claude (Docs, Specifications, Invariant Consistency)**:
  - Do `docs/architecture/YOUTUBE_VIDEO_STREAM.md` and `tasks/RADIO-003.md` completely align with the actual code in `stream.sh`, `station.liq`, and systemd drop-ins?
  - Are all acceptance criteria accurately described as automated vs pending external human gates?
  - Are trust boundaries and security claims factually stated without over-promising?
- **DeepSeek (Bash Correctness, POSIX Standards, Subprocess Safety)**:
  - Are there any edge cases in `apps/radio/stream.sh` or `scripts/linux/setup_radio_node.sh` regarding variable quoting, error exit trapping, or environment variable precedence?
  - Does the YouTube stderr suppression (`>/dev/null 2>&1`) completely eliminate leakage across all failure modes (e.g., DNS failure, TLS handshake error, network timeout)?
  - Does `check_host_proc_isolation` correctly parse complex `/proc` mount options across different Linux distributions?
- **Grok (Adversarial Operations, Recovery, Blindspots)**:
  - What happens if FFmpeg encounters an unexpected SIGPIPE or Harbor disconnection while streaming to YouTube? Does systemd auto-restart smoothly or enter crash-loop backoff?
  - Are there covert secret leakage paths (e.g., temporary core dumps, crash reports, crash telemetry) not addressed by standard stderr suppression?
  - Does the systemd drop-in pattern introduce any race condition during package upgrades or reload?
- **Codex (Final Release Gate)**:
  - Only evaluates unresolved high-risk invariants after specialist triage to determine if `feat/RADIO-003-youtube-video-stream` is ready for commit and gated staging.
