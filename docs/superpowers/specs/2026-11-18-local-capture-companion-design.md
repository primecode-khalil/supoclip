# Local capture companion

Status: superseded. The operator selected a private Mac proxy instead of local capture/upload. See the home-proxy implementation plan; this document records the discarded alternative and is not the shipped feature.

## Intent

Make the verified local YouTube capture route usable from the existing recording dashboard without a VPN, SSH configuration, or giving a companion access to the server database. Keep AI processing, editing and publication on the VPS.

## Evidence and limits

A pinned yt-dlp build containing upstream commit ee2559128c7ddc471de5aeaa584a9a4ae6836ec3 captured 15 seconds of the selected live YouTube broadcast on the operator's Mac, with H.264 video at 854x480 and AAC audio, without account cookies or a VPN. The VPS still received a bot challenge with a temporary PO-token provider. This establishes a workable local capture path, not sustained reliability or maximum available resolution.

## Approaches

1. Recommended: a local companion captures and uploads finished media. The existing VPS pipeline renders and optionally publishes it. This follows the successful capture test and avoids routing unrelated traffic or exporting browser sessions.
2. A local HTTP proxy forwards VPS capture traffic. This requires consistent routing for the downloader, its browser helper and media requests, and still depends on the local machine. It adds complexity without removing the home bandwidth requirement.
3. Server-only cookies and playback tokens. These remain optional adapters; the anonymous token test did not resolve the VPS challenge. Account cookies can expire, may not fix IP challenges and carry account-restriction risk. They cannot be presented as a guaranteed solution.

## User experience

The recording dashboard adds a Capture devices section with Add this computer, device status, last seen, queued bytes, capture status and Disconnect. Each channel selects Server or a paired capture device. Existing channels retain their current capture location until explicitly changed.

Initial Mac setup: download the companion, open it, use a short-lived pairing code, and approve the named device in the authenticated dashboard. Channels and policy then come from the dashboard. Dependencies install in a private companion directory; the installer does not overwrite system Python or the operator's yt-dlp. A packaged and signed app is the desired distribution; an unsigned build or Terminal installer must be clearly identified rather than advertised as one-click. The first release provides an installer and a pairing wizard, with instructions for any OS prompts that cannot be automated.

The companion offers start at login, pause and disconnect. While actively capturing, it prevents idle sleep if the operator enables that option; closing a laptop lid can still interrupt capture. The web dashboard does not require an open browser tab. A disconnected device displays Waiting for device, rather than Monitoring channel.

## Capture and efficiency

Use pinned yt-dlp and its supported JavaScript runtime for YouTube discovery and FFmpeg stream copy for separate video/audio capture. Reuse the existing segment-finalization and overlap-window behavior where practical. Do not hardcode provider format IDs; select compatible audio/video dynamically with a configurable resolution ceiling.

Capture each original segment once and upload it once. Assemble overlapping processing windows on the VPS so overlap does not duplicate home uploads. Home traffic includes the stream download and an equivalent upload to the VPS. At 4 Mb/s, each direction uses approximately 1.8 GB/hour before overhead. The home uplink must sustain the selected bitrate; the dashboard exposes backlog and a lower-quality option. Local CPU cost should be mostly copying, muxing and hashing, not encoding.

## Authentication and transport

Create dedicated, revocable device credentials, scoped to the owning account and explicitly assigned channels. Store credential hashes on the server and the local credential in macOS Keychain. Pairing codes expire, are single use and rate limited, and require authenticated owner approval. Never distribute BACKEND_AUTH_SECRET, database credentials or personal API keys to a companion.

All communication is outbound HTTPS. No router changes, public local listener or SSH tunnel is required. Upload finalized segments through bounded, resumable transfers with checksums and server-issued upload identities; do not assume existing POST /upload provides resumability. Server limits cover duration, bytes, account quota, backlog and assigned-channel ownership. File paths and arbitrary commands never come from a device request.

## Server integration and recovery

Add a capture-device registry, owner-authorized pairing APIs, device-scoped job/heartbeat APIs and durable segment receipt APIs. Device uploads land in the existing recording media volume; validate media, identity and digest before registering them through the native recording repositories. Keep task creation, AI keys and social publication in the existing server pipeline.

Separate capture ownership from server processing ownership. The current pipeline renews the same lease used by capture; a companion must not acquire that pipeline lease. Retain a server-side processing lease so accepted work continues when a device disconnects, and introduce a separate fenced capture assignment and device upload capability. Only one capture holder may own a channel. Devices never create AI jobs or publications. Accepted immutable receipts survive reconnects. Stable session/epoch/sequence identities and server acknowledgements prevent duplicate segment admission, AI jobs and publication after a lost response. Revocation stops new requests and submissions; already accepted processing follows the channel policy.

The server reserves bounded segment identities while a capture lease is valid. The companion stops capturing when it cannot renew ownership. A segment finalized within its reserved capture interval can finish uploading for up to 24 hours after unexpected lease expiry, provided the device remains authorized and assignment has not changed. Reassignment, pause and revocation invalidate unredeemed reservations; retain affected local files with an explicit manual-recovery action. Unreserved stale segments are never automatically admitted. Reject conflicting receipts and overlapping replacement coverage rather than silently creating duplicate jobs.

The device retains media until a durable server acknowledgement, retries with backoff, recovers after restart, and enforces a local disk budget. If disk or backlog limits are reached, stop capture and expose the reason without silently deleting unacknowledged media. A stopped device cannot be transparently replaced by server capture after a YouTube access block. Any fallback must be explicit and preserve ownership fencing.

## Builder decisions

- Start with 1 MiB upload parts and a server-validated offset. Part retransmission is idempotent; a conflicting digest/offset is rejected. Store durable upload state and atomically finalize after size, full SHA-256 and media validation. Acknowledgement means durable bytes plus an immutable segment receipt, not successful AI processing. Server window registration and task binding are separately recoverable. Device byte uploads use the dedicated upload gateway when configured; do not send binary parts through the frontend recording JSON proxy.
- Default local spool limit is 10 GiB, with a 5 GiB free-space floor and explicit dashboard controls. Delete acknowledged local segments after one hour; never automatically delete unacknowledged segments to make space. Expire incomplete server uploads after 24 hours with a visible receipt state. Server recording retention continues to follow existing processing/archive rules.
- First installer targets macOS 13+ on Apple Silicon and Intel, with pinned dependencies, verified artifact digests and no system package replacement. Updates are explicit and atomic with rollback, and cannot replace a running capture. The initial installer is unsigned and must disclose required OS approval; a signed/notarized app requires a separately provisioned signing identity.
- A stream signature or resolution change starts a new capture epoch. Never concatenate incompatible segments into one window.
- Sustained acceptance means at least 30 minutes of capture, including a network interruption, an upload retry and companion restart, followed by one completed captioned vertical clip on the VPS. A short live sample alone is insufficient for acceptance.

## Scope

First release: Mac companion, Linux-hosted server support, device pairing and revocation, channel assignment, stream-copy capture, recoverable uploads and dashboard visibility. Review-only clip generation is the default for acceptance testing. Existing publication policies remain explicit.

Not included: guaranteed YouTube challenge bypass, account-cookie access by default, Windows packaging, automatic VPN purchasing, or changing public posting policy. Direct broadcast URL support is a separate addition to the current handle-only channel registry and must not be implied by device pairing.

## Acceptance

- Pair and revoke from the dashboard; reject cross-account and unassigned-channel requests.
- Run a sustained real capture with video and audio, observe queued and acknowledged media, and generate a captioned vertical clip through the existing VPS pipeline.
- Interrupt upload and restart the device; resume without duplicate accepted media or tasks.
- Expire ownership, change assignment, pause and revoke during capture; reject stale submissions.
- Reach disk/backlog limits; preserve unacknowledged files and show an actionable status.
- Verify no account cookies, API keys or server-wide secrets leave their intended machine.
- Test the real installer on a clean Mac environment, disclose signing/OS prompts, and capture dashboard setup evidence.
- Run relevant backend/frontend/deployment checks, image security gates and live changelog verification before reporting a release.

## References

- https://github.com/yt-dlp/yt-dlp/pull/18051
- https://github.com/yt-dlp/yt-dlp/wiki/EJS
- https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
- https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies
