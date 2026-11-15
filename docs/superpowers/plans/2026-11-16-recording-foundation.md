# Recording Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax.

**Goal:** Add owned channels and durable recording-session bookkeeping to the existing SupoClip backend.

**Architecture:** Existing FastAPI routes resolve signed sessions/API keys; a recording service validates inputs and coordinates an owned repository. PostgreSQL enforces identities and one active session per channel. This slice does not start capture.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy/asyncpg, PostgreSQL, existing frozen uv environment and pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-recording-foundation-design.md`.

## Global Constraints

- Preserve existing clipping, editor, publishing, account/authentication and worker behavior.
- Use the existing authentication resolver; derive ownership from the authenticated principal only.
- Follow AGENTS.md; run meaningful tests before claiming functionality.
- Additive schema; record sessions in PostgreSQL, not process-local dictionaries or scratch files.
- No capture subprocess, external fetch, publishing or UI in this slice.
- Keep committed dependency locks unchanged.

## Review Focus

- Cross-owner IDs must be indistinguishable from missing records.
- Concurrent duplicate registrations must not create multiple active sessions.
- A registration replay must not reset a completed session or mutate its snapshot.
- Interrupted/terminal transitions must preserve timestamps and reject invalid reopenings.
- Handles and quality must reject command/path inputs and unsupported request fields.

### Task 1: Recording registry and ledger

**Files:** create `backend/src/recording/` validation/contracts; create `backend/src/repositories/recording_repository.py`, `backend/src/services/recording_service.py`, `backend/src/api/routes/recording.py`; extend `backend/src/models.py`, additive migration in `backend/src/migrations/sql/`, `backend/src/main.py`; synchronize other schema representations where the repository requires them. Add `backend/tests/unit/test_recording_validation.py` and `backend/tests/integration/test_recording.py`.

**Interfaces:** owned `/recording/channels` create/list/get/update; channel-scoped session create/list; owned `/recording/sessions/{id}` get/status update. Exact shapes and invariants come from the spec. The future capture supervisor consumes these persisted records rather than a new independent queue.

- [x] Write validation and authenticated PostgreSQL-backed tests for the acceptance requirements, including the five review-focus cases.
- [x] Run the tests and record expected missing-feature failures before implementation. Use a disposable database, never an existing user database.
- [x] Implement the smallest service/repository/schema/router changes satisfying those tests. Use database transactions/constraints for race safety, not per-process locks.
- [x] Run the focused tests to green, then relevant existing auth/health/task regressions.
- [x] Document endpoints and bookkeeping-only behavior in `docs/recording.md` and update the API/docs index. Add the required changelog entry when the review URL exists.
- [ ] Review the whole diff, fix material findings, commit and push the feature branch. Create a draft PR within the user's fork, never against upstream.

## Follow-on slices

Capture supervisor and finalized segment persistence; archive/retention jobs; ASR/audio adapters selected from the fork audit; channel/session UI; near-live windows; artifact-based publishing and Facebook. These remain explicit future work rather than stubbed controls in this slice.
