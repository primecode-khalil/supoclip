# Recording History Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Clear window history while retaining recordings, and clear attached history on library deletion.
**Architecture:** Existing PostgreSQL JSON metadata holds a durable clear receipt. Owner-scoped bulk API and library-deletion transaction share the visibility invariant; recovery retains the original row.
**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL, Next.js, existing Radix AlertDialog.
**Spec:** `docs/superpowers/specs/2026-11-19-recording-history-design.md`.

## Global Constraints
- Keep captured recordings and duplicate-prevention receipts; preserve lockfiles and base images.
- Clear failed or finished work only; active work continues.
- No permission flow beyond the existing owner confirmation.

## Review Focus
- Cross-owner requests return 404 and signed-out requests 401.
- Cleared windows never return through recovery, stale writes, or pagination.
- Active work and other channels remain unchanged.
- Task deletion rolls back both visibility and deletion together on failure.
- UI cancellation and failed requests preserve the visible list.

### Task 1: Durable history and library cleanup
- [x] Add failing integration tests for failed/finished bulk cleanup, ownership, replay/backlog/stale writes and transactional task deletion.
- [x] Run red, then implement `AutomationStore.clear_history(user_id, channel_id, scope)` and metadata filtering in lists/backlog/work selection; guard cleared writes/retries.
- [x] Add owner-scoped DELETE route and task-deletion transaction hook; verify focused recording/deletion suites.

### Task 2: Dashboard controls
- [x] Add failing component/proxy tests for confirmation, cancel, errors, and authenticated DELETE forwarding.
- [x] Implement Clear failed/Clear all finished confirmation and refresh with the existing dialog/buttons.
- [x] Run frontend tests, lint/typecheck, changelog checks and browser workflow; capture demo proof.

### Task 3: Release and current cleanup
- [ ] Add release notes/API documentation and inspect the complete diff.
- [ ] Build locked images and pass their security gates, then deploy with backup and drained workers.
- [ ] Clear only Speed's failed entries through the owner-scoped API; verify unchanged recording inventory, counts, recovery stability, health and public changelog.
- [ ] Publish source and demo proof, update PR, stop owned test resources, and hand back.
