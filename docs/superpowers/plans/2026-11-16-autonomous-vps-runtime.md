# Autonomous VPS Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Run enabled live channels through durable capture, captioned vertical clipping, archives and configured social publishing on a VPS.

**Architecture:** A separate recorder supervisor coordinates PostgreSQL-fenced channel leases and persistent media. It feeds native authenticated upload/task APIs and existing social workers; the database ledger reconciles restarts and ambiguous requests.

**Tech Stack:** Python asyncio, SQLAlchemy/PostgreSQL, FastAPI, Streamlink, FFmpeg, existing ARQ/Redis and Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-16-autonomous-vps-runtime.md`

## Global Constraints

- Automation is opt-in per channel; empty destinations mean no publication.
- Capture media lives under persistent `CAPTURE_ROOT`, not `TEMP_DIR`.
- Runtime writes require a live fenced lease using database time.
- Preserve existing authentication, native processing/publishing contracts and dependency locks.
- Never treat network errors as definitive offline or delete pending originals.

## Review Focus

- Lease expires during a slow external request: preserve receipts and reconcile; stale worker cannot acknowledge work.
- Upload succeeds before a crash: replay must resolve the same upload and native task.
- Platform accepts a post but its response is lost: block repeated submission until reconciled.
- A partial segment or restarted encoder resets timestamps: process closed entries only and start a new epoch.
- Disk pressure or archive failure: stop capture and retain unfinished media.

### Task 1: Durable automation ledger

**Files:** `backend/src/recording/automation_{models,schema,store}.py`, `backend/src/api/routes/recording_automation.py`, migration `20261116_0002_recording_automation.sql`, matching unit/integration tests. Root integrates model imports, fresh schema and Prisma.

**Interfaces:** `AutomationPolicy`; `AutomationStore(db)` with owner-scoped get/put policy, enabled channel listing, acquire/renew/release lease, fenced session lifecycle, immutable window registration, pending listing and mutable work updates. Lease contains channel_id, holder, fence and expires_at.

- [x] Write failing tests for cross-owner access, invalid destinations, expiry/fence loss and replayed media identity.
- [x] Implement schema, strict policy API and database-clock lease transactions.
- [x] Verify against dedicated PostgreSQL and existing recording/auth tests.

### Task 2: Supervised capture

**Files:** `backend/src/recording/capture.py`, `backend/tests/unit/test_recording_capture.py`, synthetic media test.

**Interfaces:** `probe_channel(url)->ProbeResult` with LIVE/OFFLINE/UNKNOWN; `CaptureProcess(directory,url,quality,segment_seconds,stall_seconds)` with start/poll/stop, running/stalled; closed segments expose path, sequence, actual start/end, checksum and size.

- [x] Write failing tests for incomplete CSV, unsafe paths, replayed rows, unknown probe failures and safe termination.
- [x] Implement safe Streamlink/FFmpeg subprocesses, finalized-segment validation and bounded shutdown.
- [x] Verify real synthetic FFmpeg recording and restart safety.

### Task 3: Autonomous pipeline and supervisor

**Files:** `backend/src/recording/pipeline.py`, `backend/src/workers/recording_supervisor.py`, focused pipeline tests; minimal native API changes only if needed for durable reconciliation.

**Interfaces:** Pipeline consumes a leased channel, immutable window and signed native API client; outputs persisted upload/task/post receipts. Supervisor owns lease heartbeat, channel polling, capture lifecycle, window preparation, retries, archives and safe retention.

- [x] Write failing tests for immutable windows, overlap filtering, crash reconciliation, external uncertainty and caps.
- [x] Implement stable upload keys, native task lookup/resume, owned account posting and blocked uncertainty state.
- [x] Integrate capture with fenced ledger, disk guard and restart reconciliation.
- [x] Verify synthetic capture-to-window and HTTP pipeline behavior without real provider calls.

### Task 4: VPS deployment

**Files:** `deploy/vps/*`, `docs/vps-autonomy.md`, locked runtime dependencies and root docs/changelog.

**Interfaces:** Recorder command `python -m src.workers.recording_supervisor`, shared backend image and persistent capture volume; `RECORDING_API_URL`, server-owned `RECORDING_ARCHIVE_REMOTE`.

- [x] Build production Compose, environment validation and backup/restore runbook using existing image versions.
- [x] Validate Compose and scripts; install locked Streamlink/runtime dependencies.
- [x] Complete regression/image verification and prepare the fork and updated draft PR for delivery.


### Task 5: Browser setup and monitoring (user scope clarification)

- [x] Implement /recording with owner-scoped proxy, channel policies, capture/lease status, native progress and blocked-work retry.
- [x] Add protected first-owner token entry and encrypted social app settings.
- [x] Validate desktop/mobile interactions, privacy consent and error states in the running Next.js app; preserve demo screenshots/video.
