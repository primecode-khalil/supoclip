# YouTube automatic publishing design

Status: proposed; researched against fork `35c383c` and upstream `09690e0` on
2026-11-19. No upload or public post has been made for this planning task.

## Outcome and first release

An owner connects a YouTube channel in the dashboard, chooses which live sources
may publish there, and enables automatic publishing. New eligible captioned
vertical clips then enter a paced, durable queue. The dashboard explains progress,
shows the resulting video link, and offers a separate publishing pause switch.
Recording continues while publishing is paused or quota is exhausted.

Start with YouTube only. Reuse the native account connections, encrypted tokens,
social posts, ARQ workers and recording overlap reservations. Keep provider
interfaces compatible with the existing Instagram and TikTok adapters. Facebook
and further provider-specific setup belong to later releases.

## Existing behavior and gaps

The app already supports OAuth, refresh/revoke, manual posts, scheduling,
multi-account selection, post history, basic metrics and score-filtered live
publication. Its YouTube adapter initiates a resumable upload but keeps the
session URL in memory, sends the file, and immediately reports it published.
An ambiguous response currently stops automatic retry; preserve that protection.

At planning time the deployed instance has no configured YouTube OAuth application
and no active YouTube connection. Adding Google app credentials and completing
owner consent are setup steps, not a need to rewrite authentication. The callback
uses the app's public origin plus `/api/social/callback/youtube`.

## Global requirements

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

## Dashboard and setup

Extend Settings → Social with a YouTube setup checklist: Google app credentials
configured, exact callback URL, account connected, confirmed channel name/avatar,
refresh access available, private test completed, and automatic rule enabled.
Reuse the existing encrypted admin settings for app credentials. Never ask for a
YouTube password or cookies; publishing uses Google OAuth directly from the VPS.

Explain Google's Testing-mode token lifetime and direct the owner to the consent
screen's production setting for unattended use. Show verification/user-cap limits
when applicable rather than promise that every self-hosted app needs the same
verification process. Validate the actual redirect URI in Google setup; use a
stable owner-controlled domain if verification requires domain ownership.

The owner chooses destination, explicit privacy, audience, category, optional
synthetic-content disclosure, score threshold, daily limit, spacing and timezone.
An enable timestamp admits future clips only. Changing the target destination
does not silently move queued posts. A disabled rule sends no new uploads.
Manual posts remain available and count toward destination pacing.

## Durable upload and truthful completion

Add a private upload-attempt record linked to the existing social post. It stores
an encrypted session URI, immutable media hash/size and metadata snapshot,
confirmed byte offset, upload stage, external video ID and bounded retry/poll
times. A persisted transfer lease fences concurrent workers. Commit the session
before sending bytes; a crash before that point may abandon an empty session but
must not lead to a duplicate video. Network I/O runs without an open database
transaction. Decrypt the session URI only for provider calls.

Use YouTube's resumable protocol with whole-file transfer where possible, then
status probes and confirmed-offset continuation after interruption. A 308 response
means incomplete, not published. Bind retries to the exact file hash and metadata;
do not resume changed bytes in an old session. Once a video ID is known, retry only
processing/status checks. If an expired or lost session cannot establish whether
a video was accepted, show Needs attention rather than upload it again.

Poll owner-authorized video processing and upload status, then verify actual
privacy. A processed private video is Ready (private); a processed public video
is Published. A processing rejection or unexpected privacy is visible and does
not trigger another upload. Do not promise exactly-once external effects when
Google has accepted bytes but cannot return a recoverable outcome.

## Queue policy and failure behavior

Use an owner-scoped destination policy shared by sources targeting the same
connected channel. Reserve slots transactionally, count manual and automated
uploads once, and use PostgreSQL time. Evaluate the owner's timezone for daily
limits with DST-aware boundaries; never reset a cap because a worker restarted.
Retain source-range overlap reservations and request tombstones. Duplicate ARQ
delivery or recorder recovery must refer to the same logical post.

App caps and Google project quota are distinct. Quota exhaustion delays new upload
initialization for the project; channel upload limits affect the destination;
transient failures back off; revoked consent requests reconnection. Paused or
deleted sources stop unstarted work. Once upload bytes have been accepted, pause
and deletion cannot reliably retract that action: continue reconciliation and
show the actual result. Do not claim a remote video was removed.

Keep existing coarse post statuses for API compatibility and add a safe stage:
queued, waiting_for_slot, uploading, processing, ready, waiting_for_quota,
reconnect_required, needs_attention. Expose stage, confirmed-byte progress,
next_attempt_at and a readable reason; exclude private transfer checkpoints.

## Acceptance and rollout

First deliverable: guided setup and one owner-requested private upload whose
channel, finished processing, actual privacy, captions and A/V playback are
verified. Public activation is a later explicit dashboard action. Test a worker
restart mid-transfer, lost final response, duplicate queue delivery, quota wait,
token revocation, deletion and pause races, two sources sharing one destination,
and day-boundary pacing before claiming unattended readiness.

No new API charge is needed for fallback metadata. The feature should display its
own upload attempts/limits, not an invented authoritative Google quota balance.

## Official references checked 2026-11-19

- [Revision history](https://developers.google.com/youtube/data/revision_history): the November 2 update removes the old API-project-verification private-only upload restriction. Do not repeat the older blanket rule; still set explicit privacy.
- [Quota and compliance](https://developers.google.com/youtube/data/guides/quota_and_compliance_audits): current default separate upload allowance is 100 `videos.insert` calls/day; verify the project's actual quota rather than using old per-upload quota assumptions.
- [Resumable upload protocol](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol): persist the session, probe progress and resume from confirmed bytes.
- [OAuth web server flow](https://developers.google.com/identity/protocols/oauth2/web-server) and [token lifetime](https://developers.google.com/identity/protocols/oauth2): offline refresh access; external Testing-mode refresh tokens with YouTube scopes expire after seven days.
- [Sensitive-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification): verification requirements and personal-use exceptions are separate from upload privacy.
- [Video resource](https://developers.google.com/youtube/data/reference/rest/v3/videos), [insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert), and [list](https://developers.google.com/youtube/data/reference/rest/v3/videos/list): metadata byte limits, audience/privacy fields, processing and upload status.
- [Three-minute Shorts](https://support.google.com/youtube/answer/15424877): current duration/aspect eligibility. A `#Shorts` hashtag alone does not validate the media.
