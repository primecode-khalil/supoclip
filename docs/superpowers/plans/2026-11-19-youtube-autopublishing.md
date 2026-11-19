# YouTube Automatic Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execute natively unless the owner chooses delegation; follow the session's agent permissions.

**Goal:** Connect a YouTube channel once and reliably publish new eligible live clips through a visible, paced queue.

**Architecture:** Extend the existing social provider/service/repository and recording pipeline. Add private durable transfer checkpoints and destination policies; keep existing post statuses and provider adapters compatible. Do not rebase onto current upstream main.

**Tech Stack:** Python/FastAPI, PostgreSQL, SQLAlchemy, ARQ/Redis, existing requests-based Google adapter, Next.js/TypeScript, pytest/Vitest/Playwright.

**Spec:** [YouTube automatic publishing design](../specs/2026-11-19-youtube-autopublishing.md).

## Global Constraints

- Preserve the fork's AGPL baseline; do not import post-license-change upstream code in this feature.
- Keep the Linux single-script installer and dashboard configuration path.
- Keep social credentials and resumable session URLs encrypted; never expose them in API JSON, logs, screenshots, or errors.
- Default automatic publishing to disabled, visibility to private, and backfill to disabled.
- For a newly created rule default to score >= 75, at most 3 posts per destination per day, and at least 60 minutes between uploads; these are adjustable engineering defaults, not performance claims.
- Preserve existing saved policies and caps until the owner explicitly opts into a new publishing rule.
- Accept only verified, playable 9:16 outputs with audio and duration > 0 and <= 180 seconds for this automatic Shorts workflow.
- Do not make an extra LLM call mandatory for posting; use existing hook/transcript metadata as the fallback.
- Never automatically start a second video upload when the first upload's outcome remains unknown.
- Deleting a library item cancels its unstarted publication and does not delete an already uploaded YouTube video.
- Pausing publishing, reaching its limits, or failing a social API call must not stop capture.
- No public test post or activation of a real publishing rule without an explicit owner action.

## Review Focus

1. Crash between session creation and persistence must not send bytes before the checkpoint commits (Task 2).
2. Changed render bytes or Unicode metadata must never be silently resumed/truncated incorrectly (Tasks 1 and 2).
3. Two sources and duplicate workers targeting one account must share reservations, including across DST boundaries (Task 4).
4. Pause, library deletion and account revocation racing a claimed upload must stop unstarted work and reconcile accepted bytes (Tasks 3 and 4).
5. A lost completion response must not become a second public post, even after a deploy (Tasks 2, 3 and 6).

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

### Task 4: Shared destination rules, pacing and live-source integration

**Files:** Create `backend/src/services/social_publication_policy.py`,
`backend/src/repositories/social_publication_policy_repository.py`,
`backend/src/migrations/sql/20261119_0002_social_publication_policies.sql`,
`backend/tests/integration/test_social_publication_pacing.py`; modify
`backend/src/recording/automation_schema.py`, `backend/src/recording/runner.py`,
`backend/src/api/routes/social.py`, `backend/src/services/social_service.py`,
`backend/src/repositories/social_repository.py`, `init.sql`, Prisma schema and
matching migration, and recording publication/idempotency tests.

**Interfaces:** Owner-scoped `GET/PUT /social/accounts/{account_id}/automation`
returns/accepts enabled, privacy, audience/category/disclosure, daily_limit,
min_interval_minutes, timezone, min_score; enabled_at is server-owned. Add
`reserve_publication_slot(db: AsyncSession, post_id: str, now: datetime) ->
datetime | None`: lock the destination, return its next eligible UTC slot or None
when blocked, and idempotently reuse an existing reservation. All manual/automatic
YouTube uploads pass the same admission check. Store bounded quota deferrals by
project separately from destination caps. Implement timezone day bounds with
`zoneinfo`; no fixed 24-hour assumption across DST.

- [ ] Write real-DB concurrent tests: two sources share three daily slots, sixty-minute spacing, duplicate claims reuse one slot, manual posts count, restart does not reset usage, and DST/day rollover follows the configured timezone. Add eligibility tests for score 74/75, playable 9:16 with audio and duration bounds, and no old-clip backfill on enable/re-enable.
- [ ] Add pause/deletion/quota tests asserting capture continues, unstarted jobs stop, existing overlap/tombstone protection remains, rejected media sends no API request, and saved policies retain their old cap until explicit opt-in.
- [ ] Run `cd backend && .venv/bin/pytest tests/integration/test_social_publication_pacing.py tests/integration/test_recording_publication_limit.py tests/integration/test_recording_post_idempotency.py -q`; confirm failures for the new behavior.
- [ ] Implement policies, transactional reservations and a stable logical-post deduplication key per immutable clip/render and destination; keep recording source-range overlap reservations. Add an independent publishing-enabled check before any new bytes. Create policy defaults only when the owner opts in; no migration silently activates posting or changes saved limits.
- [ ] Repeat these tests and Task 3 lifecycle tests; require no double slots/uploads or capture stop at a posting cap. Commit as `feat(social): pace automatic YouTube publishing per channel`.

### Task 5: Dashboard controls and publication history

**Files:** Modify `frontend/src/app/settings/social/page.tsx`,
`frontend/src/components/scheduled-posts.tsx`,
`frontend/src/components/recording/policy-form.tsx`,
`frontend/src/lib/social.ts`, `frontend/src/components/youtube-setup.tsx`;
create `frontend/src/components/youtube-automation.tsx`, corresponding Vitest
tests and `frontend/e2e/youtube-autopublishing.spec.ts`; update the repository's
localized messages where those screens use translations.

**Interfaces:** Use Tasks 1, 3 and 4 APIs. Show destination identity, explicit
private/public choice, separate enable/pause, score/caps/spacing/timezone,
next upload, safe upload progress, processing, quota/reconnect/attention reasons
and final video link. A private test action calls existing manual post creation
with privacy fixed to private; it never toggles automatic posting.

- [ ] Add component/browser assertions for disconnected setup, private test progress, public opt-in, pause without stopping recording, future-only enable explanation, rejected save preserving the form, reconnect and unknown-outcome copy. Assert all stages remain readable at 320px and keyboard focus survives refresh.
- [ ] Run targeted Vitest and browser tests against mocked provider traffic; confirm missing controls/stages fail.
- [ ] Build the controls using existing UI components and API proxy, keeping transfer internals private. Distinguish Ready (private) from Published. Do not promise remote deletion for a library item.
- [ ] Run `make check`, frontend targeted tests and `pnpm exec playwright test e2e/youtube-autopublishing.spec.ts` in the configured test environment. Capture demo-data screenshot and short workflow video for the eventual PR. Commit as `feat(social): manage YouTube automation from the dashboard`.

### Task 6: Release rehearsal and private end-to-end proof

**Files:** Update `docs/configuration.md`, `docs/app-guide.md`, `CHANGELOG.md`, and
extend the existing Linux installer documentation with Google setup and recovery.
Use the existing deployment scripts and final-image security checks.

- [ ] Run all changed backend suites with a dedicated PostgreSQL/Redis setup, the full frontend test suite, `make check`, changelog tests, and targeted browser workflows. Report unrelated baseline failures separately; do not call a failed full suite green.
- [ ] Build fresh final images with committed dependency locks and patched image pins; require zero failing critical findings. Rehearse both additive migrations and restoration of the previous application version against a disposable database.
- [ ] Prove an upload interrupted by worker restart recovers the same session/video, a lost final response does not start another insert, quota deferral resumes, and a duplicate queue message cannot send a second video. Confirm dashboard reasons and capture independence.
- [ ] Review the combined diff, release notes and demo visual proof. Before a production restart, check/drain queued or processing tasks and ongoing ARQ jobs; record rollback source/images and verify the live changelog after rollout.
- [ ] When the owner completes OAuth consent and explicitly requests the private test, upload one approved clip. Verify the connected destination, finished processing, actual private visibility, captions, A/V sync and returned URL. Keep public automation off until explicit owner activation.
- [ ] Commit documentation/evidence references as `docs(social): document YouTube setup and verified rollout`. Report verified behavior and remaining external setup accurately; do not claim 100% autonomy before the recovery/private test gates pass.

## Self-review

The design's setup, media/metadata validation, private checkpoint storage,
resumable recovery, processing/visibility, pacing, future-only activation,
deletion/pause behavior and deployment proof map respectively to Tasks 1–6.
The five review-focus conditions each have explicit tests above. Interfaces share
one orchestration entrypoint and one destination reservation function; existing
provider/post APIs remain compatible. The maintenance backport and external
Google consent/public activation remain explicit dependencies, not completed work.
