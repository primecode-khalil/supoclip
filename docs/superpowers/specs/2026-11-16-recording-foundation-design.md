# Recording foundation

This is the first implementation slice of the SupoClip fork authorized in the conversation, using the agreed SupoClip-native architecture. The broader source-backed design is captured in `2026-11-16-product-design.md`; its research links refer to the companion research workspace.

## Approach

Extend the existing FastAPI/authentication/PostgreSQL/service/repository architecture. Keep all clipping/editor/publishing paths. Do not adopt a detached live fork wholesale: the audited live prototype has ownership, durability and retention defects. Reuse ideas only with current contracts and meaningful tests.

## Deliverable

An authenticated backend API for owned channels and durable recording-session bookkeeping. This is a usable registry/ledger for the next capture supervisor, not an endpoint that starts recording. It must not claim a capture process or automatic clipping exists.

- Platforms: Twitch, Kick and YouTube; platform and normalized handle identify a channel per owner.
- Channel create/list/get/update APIs under `/recording/channels`. Name, enabled state and quality are editable; platform/identity are immutable in this slice. Quality defaults to `best`, supports simple comma-separated Streamlink fallback names, and cannot be interpreted as flags or a command.
- Accept bare handles (an optional leading `@` for YouTube), not arbitrary URLs. Normalize whitespace/case and reject path/query/control characters and empty/oversized input. Allow Unicode letters/numbers in YouTube handles; use conservative platform-specific validation for Twitch/Kick. Derive canonical public URLs from the fixed platform host.
- Store an owned recording session against a channel via `POST /recording/channels/{channel_id}/sessions`, with required caller-provided `external_id` (1–255 printable characters) to make registration replay-safe per channel. Replaying registration returns the same session and does not overwrite its lifecycle or initial settings snapshot.
- A channel may have at most one active session (`created`, `recording`, `interrupted`) under concurrent requests; enforce this in PostgreSQL.
- List sessions per channel and get/update a session through owned API routes. States: `created`, `recording`, `interrupted`, `completed`, `failed`, `cancelled`. Allowed transitions: created→recording/failed/cancelled; recording→interrupted/completed/failed/cancelled; interrupted→recording/failed/cancelled. Same-state replay succeeds. Completed/failed/cancelled cannot reopen. First recording transition sets started_at once; terminal transition sets ended_at. Updates must be atomic under concurrency.
- Snapshot the validated channel settings at session creation, preserving an immutable session identity. Do not accept a user_id, raw filesystem path, arbitrary worker flags, or secrets in request bodies.
- Missing and another owner's channels/sessions both return 404; unauthenticated requests fail using existing authentication. Reuse signed sessions and API-key resolution.
- Channel identities and session external IDs must have database uniqueness constraints; expected conflicts become 409 rather than 500. Validate bodies strictly and use bounded pagination for lists.

## Explicit boundaries

No recorder process, Streamlink dependency, UI, automatic upload, filesystem deletion, remote URL fetch, or changes to rendering in this slice. Start/stop process controls belong to the supervisor slice. Docs must state that session status reports are bookkeeping, not evidence that this API started or verified capture.

## Acceptance

Real PostgreSQL-backed integration tests prove owner isolation, canonical identity uniqueness, repeated registration, one active session even with races, immutable snapshots, valid/invalid transitions and timestamps. Validation tests cover malformed URLs/handles/quality and strict request bodies. Existing authentication, health and task read tests remain green. Migrations are additive/idempotent and account deletion cascades new owned records. No existing task/source ID changes.
