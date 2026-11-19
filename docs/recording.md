# Recording registry and session ledger

The backend stores owned Twitch, Kick and YouTube channels, sessions, automation policies and immutable processing windows in PostgreSQL. A separate recording supervisor captures streams and feeds SupoClip's existing vertical clipping and caption pipeline. The `/recording` web dashboard configures channels and displays capture and processing progress. See [Linux installation and unattended operation](vps-autonomy.md).

The manual session-report API below remains available to integrations. Setting its status to `recording` is a caller's report; supervised capture also requires an enabled automation policy and a live worker lease.

Authenticate with the existing signed session headers, `Authorization: Bearer sk_...`, or `x-api-key`. Ownership comes from authentication. Missing records and another owner's records both return `404`. Requests reject unknown fields, including `user_id`, filesystem paths, worker flags and timestamps.

## Channels

| Method | Route | Behavior |
| --- | --- | --- |
| POST | `/recording/channels` | Create an owned channel; `201`, or `409` for a duplicate identity |
| GET | `/recording/channels` | Return `{channels, total}` for the authenticated owner |
| GET | `/recording/channels/{id}` | Read an owned channel |
| PATCH | `/recording/channels/{id}` | Update name, enabled state or quality |

Example create body:

```json
{"platform":"twitch","handle":"demo_channel","name":"Demo channel","enabled":true,"quality":"720p,best"}
```

`platform` is `twitch`, `kick`, or `youtube`. Supply a bare handle, with an optional leading `@` for YouTube. Surrounding spaces and case are normalized; URLs, paths, query strings, control characters and empty handles are rejected. Twitch accepts 3–25 ASCII letters, digits or underscores; Kick accepts 3–25 ASCII letters, digits, underscores or hyphens and cannot begin with a hyphen. YouTube accepts 3–30 Unicode letters/numbers with interior dots, underscores or hyphens. Canonical public URLs use fixed platform hosts. Identity is unique per owner and cannot be edited.

`name` contains 1–120 printable characters after trimming spaces. `enabled` defaults to `true` and must be enabled alongside the separate automation policy for capture. `quality` defaults to `best`; it accepts comma-separated stream names such as `1080p60,720p,best`. Each name begins with an ASCII letter or digit and then contains letters, digits, underscores or hyphens. No spaces, flags, paths or command syntax are accepted; the whole field is limited to 255 characters. Quality names are syntax-validated and do not imply availability for a particular stream.

PATCH accepts only `name`, `enabled` and `quality`; supply at least one, with no null values. Channel responses include `id`, `platform`, `handle`, `url`, the three settings, `created_at` and `updated_at`.

## Sessions

| Method | Route | Behavior |
| --- | --- | --- |
| POST | `/recording/channels/{id}/sessions` | Register an external session identity |
| GET | `/recording/channels/{id}/sessions` | Return `{sessions, total}` for the owned channel |
| GET | `/recording/sessions/{id}` | Read an owned session |
| PATCH | `/recording/sessions/{id}` | Report a lifecycle status |

Register using `{"external_id":"broadcast-2026-11-16-01"}`. The caller must supply a stable external ID containing 1–255 printable characters. IDs are exact, case-sensitive and unique within a channel. Registration returns `201` for a new session and `200` for a replay. A replay always returns the original session, including its current lifecycle and initial settings snapshot, even after termination or channel edits. A new identity conflicts with an active session (`409`). These rules apply under concurrent requests and across API processes.

New sessions start in `created`. Report status with a body such as `{"status":"recording"}`:

| Current status | Allowed next status |
| --- | --- |
| `created` | `recording`, `failed`, `cancelled` |
| `recording` | `interrupted`, `completed`, `failed`, `cancelled` |
| `interrupted` | `recording`, `failed`, `cancelled` |
| `completed`, `failed`, `cancelled` | No different status |

Repeating the current status succeeds without changing timestamps. Invalid transitions return `409`. The first transition to `recording` sets `started_at` once; resuming after interruption preserves it. Entering a terminal state sets `ended_at` once. Lifecycle timestamps use PostgreSQL's clock after locking the session, so differing API-host clocks do not break database ordering constraints. A session that fails or is cancelled before recording has no `started_at`. Session identity and settings snapshots cannot be edited.

Session responses include `id`, `channel_id`, `external_id`, `status`, `settings_snapshot`, `started_at`, `ended_at`, `created_at` and `updated_at`. The snapshot contains the channel's validated `platform`, `handle`, `url`, `name`, `quality` and `enabled` at registration. Responses contain no local file paths or credentials.

Both list APIs accept `limit` (1–100, default 50) and `offset` (nonnegative, default 0), ordered newest first by creation time and ID. `total` counts matching records before pagination. Validation errors return `422`; unauthenticated calls use the existing authentication errors. OpenAPI at `/docs` describes the request and response contracts.

## Persistence and development

The additive `20261116_0001_recording_foundation.sql` migration runs during backend database initialization. Root `init.sql`, SQLAlchemy models and Prisma models describe the same tables. PostgreSQL enforces per-owner channel uniqueness, per-channel external IDs, valid status/timestamp combinations and a partial unique index allowing one active (`created`, `recording`, `interrupted`) session per channel. Row locks serialize registration and lifecycle updates. Account deletion cascades through owned channels and sessions.

Prisma does not represent the partial index or CHECK constraints; retain the SQL migration when changing these tables. The registry itself needs no capture dependencies. The supervisor additionally requires the locked Streamlink dependency, FFmpeg/ffprobe, persistent `CAPTURE_ROOT`, and server authentication configuration.

Run focused tests using a dedicated disposable PostgreSQL database:

```bash
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/TEST_DB \
  .venv/bin/pytest tests/unit/test_recording_validation.py tests/integration/test_recording.py --no-cov
```


## Automation and progress API

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/recording/channels/{id}/automation` | Return strict policy and worker lease/heartbeat/error status |
| PUT | `/recording/channels/{id}/automation` | Replace the owned channel policy |
| GET | `/recording/channels/{id}/windows` | Paginated processing windows, native task IDs, attempts and errors |
| DELETE | `/recording/channels/{id}/windows?scope=failed` | Clear failed history; `scope=finished` clears failed and completed entries, returning `{cleared}` |
| POST | `/recording/channels/{id}/windows/{window_id}/retry` | Explicitly reopen blocked work while preserving upload/render/publication receipts |

All routes use the same owner isolation and authentication as the registry. Policy defaults are disabled, 600-second segments, 60-second overlap, balanced processing, default captions, automatic clip length, score threshold 75, at most three clips per window, ten posts per UTC day, no destinations, private visibility, archives disabled and seven-day retention. Unknown fields are rejected. Connected destination IDs must be active and owned by the same user. Instagram requires explicit public visibility; autonomous TikTok and Facebook publication are unavailable. API policy replacement preserves no omitted custom settings: send the complete desired policy.

`runtime.leased` means a supervisor monitors the channel, including when it is offline. It does not alone establish that media is being received. An enabled channel's active session and its finalized windows provide capture/processing evidence. The dashboard polls these APIs and follows the native task progress endpoint.

The supervisor checks live/offline/unknown probe results, captures into closed MKV segments, validates CSV-finalized media with ffprobe and SHA-256, and creates MP4 windows with measured overlap where stream-copy compatibility permits. If remuxing fails, it preserves the verified original as the native input and records a preparation warning. A capture restart creates a new epoch; unavailable time is never silently concatenated across epochs.

One database-clock lease per channel carries a fencing generation. Runtime writes require that generation to remain live. A renewal failure cancels processing and stops only that worker's children. Slow upload/archive work runs separately from capture's disk/backlog monitoring. PostgreSQL and persistent media survive process/container restarts; partial inputs are retained, never treated as finished work. Completed epochs are removed only after retention, finalized-file coverage, completed dependencies and any required archive acknowledgment.

Window stages are `pending`, `submitting`, `processing`, `publishing`, `completed` and `blocked`. Transient failures use a bounded retry budget and backoff; render retries preserve native processing checkpoints. When the UTC-day submission allowance is exhausted, extra rendered clips remain in the library instead of creating an unbounded publication backlog. Already-submitted posts keep their receipts and are monitored until settled, so the daily limit alone does not stop capture. Explicit owner retries open a fresh budget while keeping cumulative attempt history and immutable source/policy identity. A deleted task or uncertain external publication is blocked for review rather than silently recreated.

Each native upload/task/post uses a stable request key. Explicit keyed upload task requests remain replayable after terminal status, while unkeyed interactive requests keep the original short deduplication window. Keyed social post creation stores its request receipt in the same database transaction as the post; replays return that post, differing intent returns409, and deleted history leaves a tombstone returning410. The native publisher remains responsible for remote upload handles and uncertain outcomes. Per-account source-range reservations suppress the same event in adjacent windows within one capture epoch; this is temporal overlap deduplication, not semantic similarity detection.

### Clearing history

Live channels offers **Clear failed** and **Clear all finished**, with a confirmation. Both act on the entire owned channel, including entries outside the current page. Active upload, clipping and publishing work continues. Clearing removes entries from activity/counts and the capture backlog without deleting captured media, library clips or external posts. The recording retention policy and disk reserve still apply.

A cleared window keeps a durable metadata receipt and its original source identity, upload binding and publication receipts. Recovery cannot rediscover it as new work, and stale worker writes or retries cannot reopen it. Deleting a library generation clears its attached recording activity in the same transaction before its task binding disappears. Recorder-created tasks also store owner/source-validated window provenance on initial insertion, covering a crash before the recorder saves its binding. Existing orphaned entries can be removed with the history controls. Cleared history has no undo action.
