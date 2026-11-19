# YouTube review and native scheduling design

Status: in implementation. Revised 2026-11-19 following the owner's request to
watch clips one at a time and approve or reject them before scheduling.
The AGPL backports, OAuth setup, metadata validation, durable upload and basic
processing checks are already implemented on the feature branch. Production has
not been changed by this feature.

## Main workflow

Connect YouTube, choose a posting pattern, then open Publishing → Review. Watch
one captioned vertical clip at a time. Approve reserves the next slot and queues
its upload; Reject keeps the clip in the library and offers Undo. Advance to the
next clip after each decision. Display the exact destination and proposed local
publication time before approval. Title and description can be edited before
approval. No repeated confirmation modal is needed: Approve & schedule is the
explicit authorization for that clip.

Review-first is the default for new YouTube connections. Optional automatic
approval is an advanced, explicit opt-in for future clips, available only after a
verified private upload. Existing source configurations are retained until their
owner adopts the new destination policy. Explicitly importing existing library
clips into review does not upload them and does not enable automatic approval.

## Global requirements

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
- Deleting a library item cancels its unstarted work and requests cancellation of any attached future native schedule; keep external video/history receipts.
- Bound review intake to 200 pending items per destination and unattended approval to nine unpublished items; excess clips remain in the library.
- No real public upload/schedule, account connection, or automatic-approval activation without the corresponding explicit owner action.

## Patterns and slot allocation

A policy contains review/automatic mode, enabled intake, upload pause, timezone,
minimum score, category/audience/disclosure and a schedule. Interval mode uses an
anchor and elapsed minutes (default six hours). Weekly mode uses a nonempty set
of weekdays and unique local HH:MM times. Custom one-off publication times may be
chosen at approval. Default upload/processing lead time is 15 minutes.

Allocate under a destination lock and persist the reservation before returning
approval. Double clicks/retries reuse the same reservation and post. A late upload
uses the next free future slot instead of sending a past publishAt, which Google
would publish immediately. On DST transitions skip nonexistent weekly local times
and use the first occurrence of an ambiguous local time, once. Existing reservations
and confirmed native schedules are not silently rearranged by policy edits.

## Private uploads and native publication

Reuse the existing social posts and the private youtube_uploads checkpoints.
Approval binds review ID, immutable render/version/hash, final public intent and
a reserved publication time. Upload bytes with private visibility only. Once
processing succeeds, use videos.update to set private visibility plus a future
publishAt, preserving the video's other mutable status settings. Confirm the
returned/read-back schedule before showing Scheduled on YouTube. At the due time,
poll the existing ID and report Published only when actually public. YouTube can
publish a confirmed schedule while the VPS is offline.

Request youtube.force-ssl alongside the current upload/read permissions so the app
can create, change and remove native schedules. Explain reconnection for older
grants. Distinguish the separate Google upload bucket from general API quota;
shared quota deferrals must not retry every clip at once. Use the existing API-host
cron worker queue for network jobs and recover queued/due jobs from PostgreSQL.

Cancellation is a durable request. If the video remains private, remove publishAt
on YouTube and verify its absence before marking cancelled. If already public,
report that truth and the video link; do not claim it was prevented. A lost status
update response is reconciled against the same video ID, never by re-uploading.

## Review UI

A dedicated Publishing page has Review, Queue and History views. Review shows a
large vertical player, source/title, editable title/description, target account,
next time and Approve & schedule / Reject / Later controls. A and R shortcuts are
ignored while typing and while a decision is in flight. Reject offers Undo. The
queue shows upload/processing/native scheduling progress, reserved times, actual
YouTube links, quota/reconnect/attention reasons, and cancellation/rescheduling.
The schedule editor supports interval hours, weekly days/times and timezone.

The first private test can be the first manually approved clip: it is processed
and verified privately before its already-approved future public schedule is set.
Automatic approval remains unavailable until that private proof exists. Review
never enables unreviewed posting as a side effect.

## Compatibility and storage

New-mode recording windows complete when review/publication work is durably handed
off, so a publishing backlog does not pause capture or keep original chunks forever.
Keep existing source overlap reservations and deleted-history tombstones. Review
candidates and approved posts protect their snapshot media until normal retention
or a user decision releases it; they do not duplicate the video bytes. Rejected
clips stay available under the existing library retention policy.

## Acceptance

Prove owner isolation; repeated approve/reject; stale preview; two reviewers and
two live sources; pattern/DST/day-boundary reservations; private upload before any
schedule; recovery after lost upload and lost schedule replies; late processing;
queue pause; quota/backoff; cancellation/reconnect/deletion races; and a restart
without duplicate videos. Verify the UI at desktop and 320px with demo data.
Build final images with committed locks/base pins, scan them, drain active jobs
before deployment, verify the live changelog, and keep public posting off until
an owner-approved test is available.

## Primary sources checked 2026-11-19

- [Resumable protocol](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol)
- [Video resource / publishAt](https://developers.google.com/youtube/data/reference/rest/v3/videos): publishAt requires a private, never-published video; a past value publishes immediately.
- [videos.update](https://developers.google.com/youtube/data/reference/rest/v3/videos/update): update scope and status-part replacement/removal behavior; preserve other mutable fields.
- [videos.insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert)
- [Quota](https://developers.google.com/youtube/data/guides/quota_and_compliance_audits) and [revision history](https://developers.google.com/youtube/data/revision_history): current upload bucket and November private-only restriction change.
- [OAuth web flow](https://developers.google.com/identity/protocols/oauth2/web-server), [token lifetime](https://developers.google.com/identity/protocols/oauth2), [verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)
- [Shorts duration/aspect](https://support.google.com/youtube/answer/15424877)
