# Review and schedule YouTube Shorts

Open **Publishing** in the dashboard. Watch one finished, captioned vertical clip
at a time, edit its title/description, then choose **Approve & schedule**, **Reject**,
or **Later**. Approval authorizes a future public YouTube publication. Rejection
keeps the video in your library; Undo returns it to review. Later changes only the
local review order. A/R shortcuts work outside text fields.

## Connect once

1. Enable YouTube Data API v3 in your Google project. Create a Web OAuth client.
2. Register the exact callback shown in Settings → Social → YouTube setup. Save
   the client ID and client secret in encrypted Admin server settings.
3. Connect your YouTube channel and complete Google's consent screen. The app
   requests upload, read, and `youtube.force-ssl` permissions to manage schedules.
   Reconnect older grants when prompted. A YouTube password/cookies are not used.
4. For unattended use, configure the consent app for Production. External Testing
   grants normally expire after seven days. Google's consent/verification and
   quota requirements still apply; follow the current Google console guidance.

The first manually approved clip uploads privately and must finish processing
before its approved public schedule is set. A separate private test can also be
sent from the library. Check captions, framing and A/V playback on that real
processed video. A completed private transfer is not the same as public posting.

## Choose a posting pattern

**Posting pattern** defaults to one slot every six hours. Choose another interval
and first slot, or select weekly days and local 24-hour times such as
`09:00, 15:00, 21:00`. Weekly times use the selected IANA timezone. Interval anchor
input is labelled with your device time; the proposed publication slot is shown
in the destination timezone. Weekly clock changes skip nonexistent local times
and use the first repeated time once.

Approvals reserve destination slots serially, so simultaneous decisions cannot
reserve the same time. Already approved reservations remain when the pattern is
edited. Each clip can also use a custom local time. Allow at least 15 minutes;
if uploading/processing misses a slot, the app moves it to the next available
future slot in its approved pattern. The Queue shows the actual confirmed time.

Choose the channel's category, made-for-kids declaration, synthetic-media
setting and minimum live score in the same form. Review requires playable 9:16
video with audio, at most three minutes. YouTube makes the final Shorts
classification; a hashtag alone does not establish eligibility.

## Add clips

New YouTube connections use review mode. Select that destination in a live
channel's settings to add qualifying future live clips. Capture and clipping
continue after the durable review handoff. Existing source posting rules remain
until you save a destination policy or explicitly import library clips into the
new workflow. **Import latest library clips** adds up to 20 existing clips for
review without starting uploads. Reimporting does not recreate rejected items.

Pending review is bounded to 200 items per destination. Extra clips remain in the
library. Advanced automatic approval is off by default and requires an explicitly
saved opt-in, current permissions, and prior verified private processing. It
applies to future qualifying live clips, with at most nine unpublished automatic
approvals per channel. Review never enables it implicitly.

## What Queue means

- Queued/uploading/processing: the app is preparing the privately uploaded video.
- Scheduled on YouTube: Google confirmed private visibility plus `publishAt`.
  YouTube can publish while the VPS is offline.
- Published: Google's status confirms the existing video is public.
- Quota wait: the same checkpoint waits. Google upload and general API buckets
  have separate shared project delays; the app does not create another video.
- Needs attention/reconnection: use the existing video link and retry saved work.
  An unknown upload outcome is never automatically replaced with a second upload.

Pause intake and uploads independently in Posting pattern. Recording continues.
Already confirmed YouTube schedules keep publishing until explicitly cancelled.
An approved render is frozen: editing the library clip does not replace the
reviewed bytes. This feature requires no additional LLM call.

**Cancel schedule** is a durable request. The app removes `publishAt` and checks
Google before showing Cancelled. A connection failure leaves cancellation visibly
pending; the original schedule may still publish, so use YouTube Studio if urgent.
If the video already went public, the app reports that truth and keeps its link.
It does not automatically delete or privatize an already public video.

Deleting a library clip cancels unstarted work and requests cancellation of its
future native schedule. External IDs/history receipts remain for reconciliation.
Native schedule history cannot be deleted before cancellation is confirmed.

## Operations and rollback

Publishing uses the existing API-host `supoclip_cron` queue. PostgreSQL stores
review receipts, slot reservations, encrypted resumable checkpoints and accepted
video IDs; Redis jobs can be reconstructed from due database work. Keep the cron
worker healthy and the runtime encryption key stable. Native schedules are polled
near their due time rather than polling every future video continuously.

Schema changes are additive and mirrored in backend SQL and Prisma migrations.
Drain active tasks/ARQ jobs, back up the database and retain previous image IDs
before restarting. Preserve committed dependency locks and patched base pins;
scan freshly built final images. Confirm `/health`, frontend health, all workers,
and the live `/changelog` after release.

Before rolling back after real approvals, stop new approvals and reconcile or
cancel pending schedules, or manage them in Studio. Older images do not understand
native schedule management; restoring an image or database never cancels a
confirmed external schedule. Keep external receipts and avoid running old social
workers against native rows. The initial release makes no real upload until the
owner connects and explicitly approves a clip.

Sources: [videos.update](https://developers.google.com/youtube/data/reference/rest/v3/videos/update),
[publishAt](https://developers.google.com/youtube/data/reference/rest/v3/videos),
[resumable uploads](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol),
[OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
[quota](https://developers.google.com/youtube/data/guides/quota_and_compliance_audits),
[Shorts](https://support.google.com/youtube/answer/15424877).
