# YouTube Automatic Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execute natively unless the owner chooses delegation; follow the session's agent permissions.

**Goal:** Review captioned clips one at a time, approve or reject them, and publish approved Shorts using configurable native YouTube schedules.

**Architecture:** Extend the existing social provider/service/repository and recording pipeline. Add private durable transfer checkpoints and destination policies; keep existing post statuses and provider adapters compatible. Do not rebase onto current upstream main.

**Tech Stack:** Python/FastAPI, PostgreSQL, SQLAlchemy, ARQ/Redis, existing requests-based Google adapter, Next.js/TypeScript, pytest/Vitest/Playwright.

**Spec:** [YouTube automatic publishing design](../specs/2026-11-19-youtube-autopublishing.md).

## Global Constraints

- Preserve the fork's AGPL baseline and the Linux installer/dashboard path.
- Keep credentials and resumable session URLs encrypted and out of public JSON, logs, screenshots and errors.
- Default new destination policies to review mode; no clip is uploaded or publicly scheduled until approved.
- Default the posting interval to 360 minutes; also support weekly local posting times and a per-video custom time.
- Preserve existing approved reservations when the posting pattern changes; apply the new pattern to subsequent approvals.
- Interpret weekly posting times in the selected IANA timezone, handle DST, and reserve each destination/time at most once.
- Reject past or too-near publication times; if processing misses a slot, move the approved clip to the next free slot in its approved pattern.
- Upload scheduled clips privately, verify processing and channel identity, then set and verify YouTube's native publishAt.
- Never automatically start a second video upload when the first outcome is unknown; reuse the durable session or video ID.
- Approve and Reject require the signed owner's session; recording workers may add review candidates but cannot forge manual approval.
- Reject and Undo do not delete library clips or recordings.
- Freeze the render the owner approved; a changed preview version must be reviewed again.
- Validate an approved Short as playable 9:16 video with audio, duration > 0 and <= 180 seconds.
- No extra LLM call is mandatory for review, metadata or scheduling.
- Pause intake/uploading independently of recording. Already confirmed YouTube schedules continue on YouTube unless explicitly cancelled.
- Cancel a native schedule on YouTube before reporting it cancelled; failed cancellation must remain visible as still needing action.
- Deleting a library item warns about linked pending/private YouTube uploads, cancels unstarted work and requests verified remote deletion; keep external video/history receipts.
- Bound review intake to 200 pending items per destination and unattended approval to nine unpublished items; excess clips remain in the library.
- No real public upload/schedule, account connection, or automatic-approval activation without the corresponding explicit owner action.


## Review Focus

1. Lost replies or worker restarts must reuse the same upload/video and approval receipt (Tasks 2, 5, 7).
2. A preview changed after loading cannot be approved as if it were the same render (Task 4).
3. Two simultaneous approvals and DST transitions must not assign conflicting slots (Task 4).
4. A late upload must never send a past publishAt or publish immediately off-pattern (Task 5).
5. Cancellation/deletion must not report success while a native YouTube schedule remains active (Tasks 5, 7).

## File boundaries

Keep account/OAuth handling in `social_service.py` and HTTP provider details in
`social/youtube.py`. Add `social/youtube_upload.py` for protocol types/operations,
`services/youtube_publish_service.py` for async orchestration, a private
`repositories/youtube_upload_repository.py` for checkpoints, and
`services/social_publication_policy.py` for slot/rule decisions. The recorder only
selects eligible clips and requests a post; it must not manage Google sessions.

## Maintenance dependency

The [upstream audit](../../research/2026-11-19-upstream-update-audit.md) recommends a
separate selected-backport branch from `35c383c`. Prioritize durable task keys and
database/export fixes. Preserve initial recording metadata when resolving the
conflicts and run both sets of regressions. Finish/review that maintenance change
before applying this plan on top, or explicitly retain `35c383c` as the execution
baseline. A full main rebase is not a prerequisite for the feature.

### Task 1: Guided YouTube setup and valid upload metadata

**Files:** Modify `backend/src/social/youtube.py`, `backend/src/social/base.py`,
`backend/src/services/social_service.py`, `backend/src/api/routes/social.py`,
`frontend/src/app/settings/social/page.tsx`, `frontend/src/lib/social.ts`;
create `backend/src/social/youtube_metadata.py`,
`frontend/src/components/youtube-setup.tsx`; extend
`backend/tests/unit/test_social_runtime_settings.py`,
`backend/tests/unit/test_social_providers.py`; create
`backend/tests/unit/test_youtube_metadata.py` and
`frontend/src/components/youtube-setup.test.tsx`.

**Interfaces:** Add `build_youtube_metadata(request: PublishRequest) -> dict` in
`youtube_metadata.py`. Add `provider_options: dict[str, Any]` with an empty default
to `PublishRequest`, carrying `category_id`, `made_for_kids`, and optional
`contains_synthetic_media`. Add owner-authenticated `GET /social/youtube/setup`
returning `configured`, `redirect_uri`, `connections`, `refresh_access_available`
and safe setup hints; no credential values.

- [ ] Write metadata tests asserting explicit private visibility, a 100-character title limit, a 5,000-byte UTF-8 description limit without broken Unicode, selected audience/category/disclosure, and deterministic fallback when AI metadata is absent. Add setup authorization and secret-omission assertions plus installer/self-host access coverage.
- [ ] Run `cd backend && .venv/bin/pytest tests/unit/test_youtube_metadata.py tests/unit/test_social_providers.py tests/unit/test_social_runtime_settings.py -q`; confirm new assertions fail for missing behavior.
- [ ] Implement metadata normalization and setup response using the existing encrypted runtime settings and signed OAuth routes. Reuse `channels.list(mine=true)` identity, validate the granted scopes/refresh availability, and show the exact callback and Testing-mode explanation. Keep public activation disabled.
- [ ] Run the same backend command and `cd frontend && pnpm exec vitest run src/components/youtube-setup.test.tsx`; require passing tests. Commit as `feat(social): guide YouTube connection and validate upload metadata`.

### Task 2: Private resumable transfer records and protocol recovery

**Files:** Create `backend/src/social/youtube_upload.py`,
`backend/src/repositories/youtube_upload_repository.py`,
`backend/src/services/youtube_publish_service.py`,
`backend/src/migrations/sql/20261119_0001_youtube_uploads.sql`,
`backend/tests/unit/test_youtube_upload.py`,
`backend/tests/integration/test_youtube_upload_recovery.py`; modify
`backend/src/social/youtube.py`, `init.sql`, `frontend/prisma/schema.prisma`, and
add the matching Prisma migration following repository conventions.

**Interfaces:** In `youtube_upload.py`, define `UploadProgress(confirmed_bytes:
int, video_id: str | None)` and methods `start_upload(access_token: str, metadata:
dict, size_bytes: int) -> str`, `probe_upload(access_token: str, session_uri: str,
size_bytes: int) -> UploadProgress`, `send_upload(access_token: str, session_uri:
str, file_path: str, offset: int) -> UploadProgress`. Use the existing HTTP session
and bounded timeouts. The orchestration entrypoint is
`YouTubePublishService.advance(post_id: str) -> dict[str, Any]`.

**Storage:** One current upload record per social post: encrypted session URI,
SHA-256, file size, immutable metadata JSON, confirmed offset, video ID, stage,
retry/poll time, owner, timestamps, lease token/expiry. Store video ID separately
before processing polling. Private repository access must not reuse public post
serialization. Claim and update with the same lease token; no DB transaction spans
HTTP or media reads. Use the existing runtime encryption helpers.

- [ ] Add protocol tests for 308 with/without Range, zero-byte status probes, final success, partial acceptance, 401 refresh, 5xx/backoff and expired session. Add DB tests asserting session persistence precedes the first byte, a second worker cannot advance a live lease, stale lease writes are fenced, changed SHA cannot resume, and session URLs never reach JSON/errors/logs.
- [ ] Run `cd backend && .venv/bin/pytest tests/unit/test_youtube_upload.py tests/integration/test_youtube_upload_recovery.py -q` against a dedicated test database; confirm the missing implementation fails.
- [ ] Implement durable advance using Task 1 metadata. Transfer the file without arbitrary tiny chunks; after interruption probe and continue from Google-confirmed bytes. Hash/verify the immutable media before resume. If completion cannot be established, retain Needs attention and never initialize a second video automatically.
- [ ] Repeat tests, including simulated process death after session commit and after the last byte. Require one logical upload and a recovered ID or explicit unknown outcome. Commit as `feat(youtube): persist and resume video uploads`.

### Task 3: Processing, visibility and safe worker reconciliation

**Files:** Modify `backend/src/services/youtube_publish_service.py`,
`backend/src/social/youtube.py`, `backend/src/services/social_service.py`,
`backend/src/repositories/social_repository.py`, `backend/src/workers/tasks.py`,
`backend/src/workers/cron_worker.py`, `frontend/src/lib/social.ts`;
create `backend/tests/integration/test_youtube_publication_lifecycle.py`.

**Interfaces:** Add `YouTubeProvider.fetch_video_status(access_token: str,
video_id: str) -> dict[str, Any]`, using owner-authorized `videos.list` for
`status,processingDetails`. `advance` from Task 2 owns transfer/processing stages;
`SocialService.publish_post` delegates YouTube posts to it without changing other
providers. Return safe `stage`, `confirmed_bytes`, `total_bytes`,
`next_attempt_at`, `reason_code`, and actual visibility through the existing API.
Keep `pending_handle` opaque; raw session URLs never go there.

- [ ] Write lifecycle tests: upload acceptance stays `publishing`; successful processing plus matching privacy becomes `published` with Ready (private) or Published display; processing rejection and mismatched visibility remain truthful; empty/not-yet-visible list responses poll within a bound; a saved video ID is never uploaded again. Cover disconnect, delete and pause at both pre-byte and post-acceptance boundaries.
- [ ] Run `cd backend && .venv/bin/pytest tests/integration/test_youtube_publication_lifecycle.py tests/unit/test_social_service.py -q`; confirm new failures.
- [ ] Implement bounded processing polling and recovery dispatch through the existing workers. Separate quota wait, channel upload limit, retryable failure, reauth and unknown outcome. Refresh access with the actual token expiry. Reconcile accepted uploads after cancellation requests instead of claiming they were removed.
- [ ] Re-run tests plus existing social publishing integration tests; require no provider regressions or duplicate initialization. Commit as `fix(youtube): verify processing and publication outcomes`.

### Task 4: Review decisions and posting patterns

**Files:** Create `backend/src/services/social_publication_policy.py`,
`backend/src/repositories/social_publication_policy_repository.py`,
`backend/src/services/social_review_service.py`,
`backend/src/repositories/social_review_repository.py`,
`backend/src/migrations/sql/20261119_0002_social_publication_policies.sql`,
`backend/tests/integration/test_social_publication_pacing.py`,
`backend/tests/integration/test_social_review.py`,
`backend/tests/unit/test_social_publication_policy.py`; modify social routes/service/repository,
recording runner, media cleanup reference handling, init SQL and matching Prisma schema/migration.

**Interfaces:** Owner-scoped `GET/PUT /social/accounts/{account_id}/automation` with
`mode: review|automatic`, enabled intake, paused uploads, timezone, min_score,
category/audience/disclosure and `schedule: {kind: interval|weekly, interval_minutes,
anchor_at, weekdays, times}`. New policies use review and 360 minutes. Add
`GET /social/review?account_id=...`, `POST /social/review/import`,
`POST /social/review/candidates`, and signed-session-only
`POST /social/review/{id}/approve|reject|undo`. Approve consumes an expected
render version and optional edited metadata/custom local time; it returns the
same item/post/reservation on retries. Add
`reserve_publication_slot(db: AsyncSession, review_id: str, now: datetime) -> datetime`.

- [ ] Write failing real-DB tests for defaults/ownership, approve/reject/undo, repeated and concurrent decisions, stale preview, stable post/slot receipts and deletion tombstones. Assert rejection and pending review enqueue no uploads.
- [ ] Write interval, weekly, custom-time, DST (23/25-hour days), simultaneous approval and policy-edit tests with literal expected UTC times. Add real ffmpeg fixtures for vertical/audio/duration validation at approval.
- [ ] Run the new unit/integration files with `--no-cov`; observe missing behavior before implementation.
- [ ] Implement private review snapshots, account-locked reservations, 15-minute lead, upload pause, future-only automatic intake and explicit library import. Freeze approved media and persist idempotent decisions/posts. Review is default; automatic mode requires prior private proof and an explicit save.
- [ ] Route new-mode live candidates to review and complete the recording window after durable handoff. Keep legacy source rules until adoption, overlap reservations and history tombstones. Bound pending review to 200 and unattended approved items to nine per destination.
- [ ] Run review/pattern, existing recording limit/idempotency/history and social tests. Commit `feat(social): review clips and reserve configurable publication slots`.

### Task 5: Native YouTube schedules and cancellation

**Files:** Modify `social/youtube.py`, `social/youtube_metadata.py`,
`services/youtube_publish_service.py`, social service/repository, private upload
repository/schema, `workers/job_queue.py`, `workers/cron_worker.py`, `workers/tasks.py`,
clip/task deletion integration, and add native scheduling/cancellation integration tests.

**Interfaces:** `YouTubeProvider.update_video_status(access_token: str, video_id:
str, status: dict) -> dict`; request `youtube.force-ssl` for schedule management.
Private upload state adds desired/confirmed native publish time, schedule-request
and cancellation flags; safe stages include scheduling, youtube_scheduled and
cancelling. Approved native posts upload immediately with private visibility,
independent of their future reserved public time.

- [ ] Write failing tests proving private upload/processing precede schedule creation, returned/native status is verified, lost update responses reuse one video, overdue slots move forward, and confirmed schedules publish while the app was offline.
- [ ] Add cancellation, revoke/reconnect, library deletion and already-public race tests; assert no cancelled label while publishAt still exists and no second upload on any retry.
- [ ] Implement status updates preserving other mutable status fields; reconcile before repeating an update. Atomically persist scheduled/published/cancelled truth. Reconcile existing IDs without needing deleted local media.
- [ ] Dispatch YouTube network jobs through the existing API-host cron worker queue; recover queued/due jobs from DB with bounded shared project/bucket quota deferrals. Avoid holding transactions during network/media I/O.
- [ ] Run native schedule/cancellation, durable upload, all social and recording deletion regressions. Commit `feat(youtube): manage verified native publication schedules`.

### Task 6: Sequential review dashboard

**Files:** Create `frontend/src/app/publishing/page.tsx`, focused review/player,
pattern editor and queue components/tests, and `frontend/e2e/youtube-autopublishing.spec.ts`;
modify app navigation, social settings/setup, safe client types and existing scheduling UI.

**Interfaces:** Use Tasks 4–5 APIs. Show one actual rendered vertical clip, editable
metadata, destination and proposed local slot. Approve & schedule and Reject
advance on success; Later does not reject; Undo restores rejected review. Keyboard
A/R ignores typing, repeated events and in-flight decisions. Queue shows app work
versus confirmed YouTube scheduling, actual video links, reasons, cancel and
custom reschedule controls. Pattern changes apply to future approvals.

- [ ] Write failing component/browser tests for sequential decisions, double-clicks, edit/typing shortcuts, undo, API errors preserving state, pattern/timezone saves and native queue/cancellation states.
- [ ] Build the page with existing components and signed API proxies, including connection guidance and explicit import of existing clips. Keep automatic mode off by default and show public schedule time on the approval action.
- [ ] Run targeted Vitest, `make check` and Playwright workflows at desktop/320px. Capture demo-data screenshot and short workflow video for the PR. Commit `feat(social): add a one-by-one Shorts review studio`.

### Task 7: Release rehearsal and private proof

**Files:** Update configuration/app/installer docs and root changelog; use existing
production deploy and image security scripts.

- [ ] Run all changed backend suites with dedicated PostgreSQL/Redis, full backend/frontend checks, changelog tests and targeted browser workflows. Report any baseline failures accurately.
- [ ] Rehearse schema changes and previous-app restoration against a disposable database. Build fresh final images with committed locks/base pins and pass critical image scans.
- [ ] Prove restart/lost reply recovery and no duplicate upload or schedule; test late slots, quota, paused intake/uploads and cancellation with accepted media.
- [ ] Obtain one fresh whole-branch review as required by executing-plans; fix important findings with reproducing tests, review release evidence and collect rulings.
- [ ] Drain active application/ARQ jobs before a later VPS restart, retain source/image rollback points and verify health/live changelog. Do not connect an account or create a real public schedule without owner action.
- [ ] Once the owner completes consent and explicitly approves a private test or a scheduled clip, verify actual channel, processing, privacy/schedule, captions and A/V playback. Until then report external setup/test gates as pending rather than claiming live YouTube proof.
- [ ] Commit documentation/evidence references, push/link the PR and report verified behavior, remaining setup and any deferred limitations.

### Task 8: Synchronized source deletion (execute before Task 7 rollout)

**Files:** YouTube provider/native orchestration, social repository/impact API,
clip/task deletion guard, library and generation confirmation dialogs, shared
warning component and backend/component/browser regressions.

- [ ] Reproduce missing warning/acknowledgement, permanent remote deletion, lost delete reply, queued/no-ID cancellation, concurrent orphan and published-during-delete cases.
- [ ] Add owner-scoped deletion-impact preview. Require explicit acknowledgement before source DELETE affects pending YouTube uploads. Show affected copies in generation/clip/bulk dialogs.
- [ ] Persist remote-delete intent with library deletion; infer it for orphaned native uploads to cover approval races. Delete the existing ID and verify absence before terminal Deleted state. Keep receipts and distinguish ordinary schedule cancellation.
- [ ] Verify owner isolation, real delete entry points, retained-state errors and UI warnings. Run focused backend/frontend suites, make check and browser flows; commit before final images, scans and deployment.

## Self-review

Tasks 1–3 remain the completed foundation. The owner's review-first steering
supersedes the old direct-auto-post pacing proposal before Task 4 implementation.
The review/decision, cadence, immutable media, native private-then-schedule,
recovery/cancellation, dashboard and deployment requirements map to Tasks 4–7.
Review Focus conditions have explicit tests in their owning tasks. Real consent
and real public scheduling remain explicit owner actions, not completed work.
