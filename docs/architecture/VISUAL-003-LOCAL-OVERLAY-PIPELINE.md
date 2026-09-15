# VISUAL-003: Local Dynamic Now-Playing Overlay Pipeline Architecture

## 1. System Context & Overview

The VISUAL-003 subsystem implements the local dynamic Now Playing lower-third overlay pipeline for AstraZit Radio (`apps/radio`).
It is designed to composite clean, readable track and station metadata over the visual loop master in real time without causing broadcast halts or pipeline crashes.

> [!IMPORTANT]
> **LOCAL VALIDATION STATUS ONLY**
> This architecture has been implemented, tested, and validated strictly in local development environments.
> **NOT YET PRODUCTION INTEGRATED.**
> Local Windows resource benchmarks are NOT VPS capacity claims. Production execution remains governed by Linux VPS and systemd deployment standards under ADR-008.

---

## 2. Pipeline Architecture

The overlay pipeline operates across seven decoupled stages:

$$\text{Metadata Event} \longrightarrow \text{Sanitizer / Normalizer} \longrightarrow \text{Deterministic Renderer} \longrightarrow \text{Atomic LKG Writer} \longrightarrow \text{Transition Controller} \longrightarrow \text{image2pipe Feeder} \longrightarrow \text{Continuous FFmpeg Process}$$

```
+---------------------------------------------------------------------------------------+
|                                    EVENT LAYER                                        |
|  Untrusted Metadata (Title, Artist, Program, Profile)                                 |
+------------------------------------------+--------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                                  SANITIZER & NORMALIZER                               |
|  - Enforces Layout A contract (Frozen under VISUAL-002B)                              |
|  - Replaces forbidden sentinels (null, None, unknown, stack traces, audio filenames)  |
|  - C0/C1 control code stripping, whitespace normalization, Unicode NFC                |
|  - Missing/empty fallback: Title -> "ASTRAZIT RADIO", Program -> "ASTRAZIT RADIO"     |
+------------------------------------------+--------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                                DETERMINISTIC RENDERER                                 |
|  - Layout A (Minimal Lower Third): 385x88 RGBA PNG, Artwork OFF                       |
|  - Usable title width: 345px, measurement-based binary search truncation with "..."   |
|  - Position on 1280x720 canvas: X = 380, Y = 554                                      |
|  - Pixel & byte deterministic PNG rendering                                           |
+------------------------------------------+--------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                                 ATOMIC LKG WRITER                                     |
|  - Atomic write: scratch file in target dir -> flush/fsync -> validate -> os.replace   |
|  - Preserves Last-Known-Good (LKG) on write failure or corrupted candidate            |
|  - Cleans temporary artifacts; validates dimensions (385x88) and format (RGBA PNG)   |
+------------------------------------------+--------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                             BOUNDED TRANSITION CONTROLLER                             |
|  - Thread-safe state machine: IDLE -> VISIBLE -> FADING_OUT -> SWAP -> FADING_IN      |
|  - Fade duration: 1.5s fade out -> invisible swap (opacity 0.0) -> 1.5s fade in       |
|  - Bounded pending slot (queue depth <= 1): coalesces bursts                          |
|  - Rule: Latest VALID metadata wins (invalid updates rejected, never supersede valid) |
+------------------------------------------+--------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                                IMAGE2PIPE LIVE RELOAD                                 |
|  - Feeds PNG frames into FFmpeg stdin via pipe:0                                      |
|  - Single continuous FFmpeg process multiplexes visual master + overlay in real time  |
|  - Fail-open: overlay failures never interrupt video background or crash FFmpeg       |
+---------------------------------------------------------------------------------------+
```

---

## 3. Specifications & Frozen Contracts

| Parameter | Specification |
| :--- | :--- |
| **Design Contract** | Layout A (Minimal Lower Third) |
| **Artwork Mode** | OFF (Frozen under VISUAL-002B) |
| **Overlay Dimensions** | 385 x 88 pixels |
| **Compositing Position** | X = 380, Y = 554 (on 1280x720 16:9 canvas) |
| **Color Model** | RGBA 32-bit (translucent glass container `rgba(10, 12, 18, 175)`) |
| **Fade Dynamics** | 1.5s linear fade-out, exact 0.0 invisible swap, 1.5s linear fade-in |
| **Pending Queue** | Bounded 1-slot pending state with coalescing |
| **Update Arbitration** | Latest VALID metadata wins; malformed updates are rejected |
| **Fail-Open Contract** | On error, retain last-known-good overlay; background continues unbroken |

---

## 4. Failure Isolation & Durability Properties

1. **Deterministic Containment**: Renderer exceptions, malformed input types, or broken file reads are caught at the controller boundary. The worker thread continues running.
2. **LKG Preservation**: If a candidate image cannot be rendered or fails post-write validation, the destination PNG remains unmodified and retains the last-known-good frame.
3. **Atomic Commit Point**: Disk writes occur to a temporary file (`tmp_ovr_*.png`) in the same target directory before being atomically swapped into place via `os.replace`.
4. **Durability Semantics**: Full sync (`sync_to_disk=True`) ensures OS flush via `os.fsync` for durable disk checkpoints, while animation frames can bypass `fsync` to eliminate disk I/O bottlenecks during live streaming.
5. **Process Stability**: Proven across multi-failure test runs (malformed JSON, corrupted candidates, renderer faults, bursts) that the FFmpeg process maintains a single continuous PID with 0 restarts.

---

## 5. Governance & Review Gate

- **Implementation Gate**: VISUAL-003 (R1 through R4) is complete locally.
- **Next Phase**: Independent architectural review and human gatekeeping prior to any staging or production integration.
- **Prohibitions**: No changes to production services, `stream.sh`, Liquidsoap configuration, or remote deployment scripts have been made or permitted during VISUAL-003.
