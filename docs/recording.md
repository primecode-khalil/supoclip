# Recording registry and session ledger

The backend stores owned Twitch, Kick and YouTube channels and recording-session reports in PostgreSQL. This foundation **does not start, stop, supervise, or verify a capture process**. Setting a session to `recording` records the caller's report; it is not evidence that SupoClip captured anything. There is no recorder, Streamlink integration, recording UI, media upload, retention job, or automatic clipping in this slice.

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

`name` contains 1–120 printable characters after trimming spaces. `enabled` defaults to `true` and is a stored preference for a future supervisor. `quality` defaults to `best`; it accepts comma-separated stream names such as `1080p60,720p,best`. Each name begins with an ASCII letter or digit and then contains letters, digits, underscores or hyphens. No spaces, flags, paths or command syntax are accepted; the whole field is limited to 255 characters. Quality names are syntax-validated and do not imply availability for a particular stream.

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

Repeating the current status succeeds without changing timestamps. Invalid transitions return `409`. The first transition to `recording` sets `started_at` once; resuming after interruption preserves it. Entering a terminal state sets `ended_at` once. A session that fails or is cancelled before recording has no `started_at`. Session identity and settings snapshots cannot be edited.

Session responses include `id`, `channel_id`, `external_id`, `status`, `settings_snapshot`, `started_at`, `ended_at`, `created_at` and `updated_at`. The snapshot contains the channel's validated `platform`, `handle`, `url`, `name`, `quality` and `enabled` at registration. Responses contain no local file paths or credentials.

Both list APIs accept `limit` (1–100, default 50) and `offset` (nonnegative, default 0), ordered newest first by creation time and ID. `total` counts matching records before pagination. Validation errors return `422`; unauthenticated calls use the existing authentication errors. OpenAPI at `/docs` describes the request and response contracts.

## Persistence and development

The additive `20261116_0001_recording_foundation.sql` migration runs during backend database initialization. Root `init.sql`, SQLAlchemy models and Prisma models describe the same tables. PostgreSQL enforces per-owner channel uniqueness, per-channel external IDs, valid status/timestamp combinations and a partial unique index allowing one active (`created`, `recording`, `interrupted`) session per channel. Row locks serialize registration and lifecycle updates. Account deletion cascades through owned channels and sessions.

Prisma does not represent the partial index or CHECK constraints; retain the SQL migration when changing these tables. No additional configuration or dependencies are required.

Run focused tests using a dedicated disposable PostgreSQL database:

```bash
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/TEST_DB \
  .venv/bin/pytest tests/unit/test_recording_validation.py tests/integration/test_recording.py --no-cov
```
