# Live clipping and social publishing: feasibility study

**Research date: 15 November 2026. Verdict: technically feasible, with a conditional publishing strategy.**

The deeper source audit and feature-preserving scope are now documented in [the combined product design](combined-product-design.md), with inventories for both repositories and exact integration contracts. Use that design for the full merged product; this earlier study remains the background feasibility/publishing assessment.

The intended goal is a **merged product preserving useful capabilities from both repositories**. Use SupoClip's UI, API and persistent job infrastructure as the foundation; integrate py-autovod's recording, archive export, faster-whisper and audio-analysis capabilities as modules/workers. The earlier capture-adapter recommendation describes the smallest initial integration, not the full feature-preserving scope. See [the merge reliability assessment](merge-reliability.md) for the revised emphasis.

The proposal identifies a useful separation: capture live media, then select and render highlights. However, it overstates the readiness of the bridge, py-autovod's live-processing behavior, capture continuity, and unattended TikTok publishing. A merged product needs explicit ownership of transcription, rendering, job state and publishing, with alternative implementations exposed as selectable providers.

This is a static source and official-documentation assessment. No live capture, dependency installation, rendering benchmark, OAuth connection, deployment, or publishing test was performed. Engineering estimates below are planning judgments, not measured delivery commitments.

## 1. Evidence and scope

Repository snapshots inspected:

- SupoClip: [`e42e93b02873d29e2000a6a8235c10e23f8c99c9`](https://github.com/FujiwaraChoki/supoclip/tree/e42e93b02873d29e2000a6a8235c10e23f8c99c9).
- py-autovod: [`424f49815aba773c85cc8a7851ac52c6554dfa96`](https://github.com/0jc1/py-autovod/tree/424f49815aba773c85cc8a7851ac52c6554dfa96).

Detailed, source-linked companion audits: [SupoClip](supoclip-source-audit.md), [py-autovod](py-autovod-source-audit.md), [TikTok/Meta publishing](social-publishing-research.md). Platform rules can change independently of either repository.

The initial scope assumed here is one operator, one or a few authorized streamers, existing SupoClip UI, and short vertical clips. A service onboarding unrelated customers adds substantial account-isolation, review, support, and compliance work.

## 2. Corrections to the proposal

| Proposal | Verified finding and consequence |
|---|---|
| Both are Python, so the bridge is straightforward | REST interoperability is useful, but completion signals, media timing, retries, ownership, quotas and quality dominate the integration effort. Their Python environments should remain separate. |
| py-autovod supplies live rolling chunks | It waits for the recording process to exit before enqueueing conversion/transcription/clipping. Its uploader queues the full converted recording, not generated clips. A rolling producer must be added or replaced. |
| py-autovod has a ready single-container deployment | The inspected Dockerfile describes itself as temporary/nonworking and references a missing `requirements.txt`. Do not base a delivery estimate on its image working unchanged. |
| Call `/upload`, then `/start-with-progress` | Current SupoClip uses multipart `/upload` with field **`video`**, returning **`video_path`**; create work with **`POST /tasks/`**. `/start-with-progress` is absent from the current backend. |
| SupoClip provides social publishing | Confirmed for YouTube, TikTok and Instagram, with persisted posts, ARQ execution and scheduling. Facebook is absent and requires a provider plus account/OAuth integration. |
| Every chunk can be submitted with defaults | SupoClip defaults to 20 media uploads/user/day, one active video-processing job/user, and four jobs per ARQ worker. Continuous ingest needs explicit configuration and throughput tests. |
| The FFmpeg one-liner avoids ad gaps/frame loss | Segmentation cannot recover missing source media. Streamlink's Twitch ad filtering pauses output and creates discontinuities. Reconnect supervision and gap accounting are required. |
| RMS or speech density reliably filters uninteresting footage | These are cheap signals, not highlight classifiers. Quiet gameplay can contain important action; loud game audio can be irrelevant. Use them for ranking and evaluate missed highlights before hard rejection. |
| A 90-second trigger eliminates boundary cuts completely | Only if a retained buffer and assembler supply media across file boundaries. Trigger lag, missing post-event footage, long context and untriggered events still matter. |

Repository evidence and exact source locations are in the two source audits. Twitch behavior is explicitly described in [Streamlink's official documentation](https://streamlink.github.io/cli/plugins/twitch.html#embedded-ads).

## 3. Recommended architecture

```text
Authorized live source
  → supervised recorder
  → short finalized segments + timeline/gap manifest
  → window assembler + inexpensive candidate ranking
  → durable submission ledger
  → SupoClip upload/task API
  → selection + rendering + clip review
  → SupoClip's existing scheduled publishing queue
       ├─ YouTube
       ├─ Instagram professional account
       ├─ Facebook Page [new provider]
       └─ TikTok [approved flow, or draft/manual fallback]
```

**Keep one owner for each expensive stage.** Disable py-autovod's own ASR, highlight rendering and uploader if reusing its recorder. Otherwise media is transcribed twice, outputs compete, and retries can publish duplicates. A small new capture adapter avoids py-autovod's unused dependencies and packaging repairs; retain py-autovod only if its channel monitoring/archive behavior is valuable enough to justify modification. This is an engineering recommendation based on the audited lifecycle.

### Capture, windows and timing

Use short finalized segments, for example approximately 10–30 seconds, to retain a rolling history. Assemble 5–10-minute analysis windows with context overlap. Those intervals are starting choices to benchmark, not guaranteed optimal settings. Event-triggered extraction can use the same history once chat/audio triggers exist.

Segment-copy cuts follow source keyframes, so requested durations are approximate. Record actual media timestamps, channel/session identity, wall-clock mapping and known gaps. With reset timestamps, filenames alone cannot reconstruct a global event timeline. Consume finalized files through a manifest/close signal and validate them; file creation is insufficient. Plain MP4 finalization is vulnerable to an abrupt process stop. FFmpeg documents passing inner MP4 faststart settings through `-segment_format_options movflags=+faststart`. [FFmpeg muxer documentation](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment)

A ten-minute batch introduces approximately 0–10 minutes of collection delay, averaging about five minutes for uniformly distributed events, **before** ASR, selection, rendering and platform processing. If an event at 09:55 needs footage from the next finalized ten-minute file, that footage may not become available until 20:00. Smaller source segments allow an assembler to fetch post-context promptly without submitting every segment for AI processing.

Do not promise zero-loss capture. Reconnect both pipe processes, preserve stderr, handle partial files and codec changes, distinguish a stalled source from an ended stream, and retain session-specific filenames. If you control the broadcaster, evaluate an authorized direct feed or local recording to reduce dependence on viewer-side stream delivery.

### SupoClip integration contract

The current conceptual request sequence is:

```text
POST /upload
  Authorization: Bearer sk_...
  Idempotency-Key: <stable-session-and-window-key>
  multipart field: video
  response.video_path = upload://...

POST /tasks/
  Authorization: Bearer sk_...
  JSON includes: {"source": {"url": "<response.video_path>"}}
  response includes task_id / job_id

GET /tasks/{task_id}/progress
  SSE progress; also reconcile persisted task and clip state after reconnect

GET /tasks/{task_id}
GET /tasks/{task_id}/clips
GET /tasks/{task_id}/clips/{clip_id}/file?download=true

POST /social/posts
  JSON includes: task_id, clip_id, social_account_id
  Optional: title, caption, hashtags, privacy_level, scheduled_for
```

Persist the upload reference and task ID before proceeding. Retrieve the task's clips using the current task/clip routes, and use authenticated file access for the operator. Exact options and retrieval paths are documented in [the source audit](supoclip-source-audit.md); pin the revision and check the deployed OpenAPI schema before implementation. This is a contract sketch, not an executed integration script.

Bootstrapping API keys involves authenticated frontend/account setup and verified email; the self-host documentation requires SES for verification links. Replace the example authentication/encryption secrets. Social publishing defaults off and needs provider app credentials, callback configuration, encryption settings, and provider-accessible media delivery where required. The current Instagram provider uses Instagram Login and a fetchable video URL; newer API upload options would require implementation changes. Optional AI social-caption generation separately uses Anthropic, even if highlight selection uses a different provider. [Current API documentation](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/docs/api-reference.md), [social provider audit](supoclip-source-audit.md)

### Reliable processing and publishing

Reuse SupoClip's existing post database and ARQ publisher. Add ingestion-specific durable state and reconcile ambiguous upload/task submissions. Use global event intervals and content similarity to deduplicate clips from overlapping windows. Maintain a separate result for every clip/account/platform; one platform failure must not cause successful destinations to be submitted again.

Uploads can succeed remotely while the response is lost. Save provider upload/post IDs and reconcile status before retrying; do not assume universal exactly-once publishing. Refresh/revocation handling, processing failures, quota backoff, expiration of unpublished media containers, operator retry and a publishing pause control belong in acceptance testing.

## 4. Auto-upload versus public publishing

| Destination | Feasibility | Required distinction |
|---|---|---|
| **YouTube / Shorts** | Good first target; native SupoClip provider exists | OAuth authorization for the destination channel, explicit metadata/privacy settings, resumable upload and processing checks. Shorts use the regular video upload API. |
| **Instagram Reels** | Feasible for professional Business/Creator accounts; native provider exists | Account/login path, correct publishing permissions, media-container creation and completion before publishing. Customer onboarding requires the appropriate reviewed access. Personal accounts are unsupported. |
| **Facebook Reels** | Feasible for Pages; new integration required | Page OAuth/token and posting rights, upload/status/finish flow. This API does not publish Reels to personal profiles. |
| **TikTok** | Conditional; do not promise fully unattended private-tool public posting | Direct Post scope approval and audit, supported product/use case and creator control. Draft upload still requires the user to finish posting in TikTok. |

### YouTube: current documentation differs from older guidance

The current `videos.insert` reference and **2 November 2026** revision entry say uploads from unverified API projects are no longer forced private. The current default quota includes **100 video-insert calls/day in a separate bucket**, plus other quotas. Audit is required to request increased allocation; Google OAuth verification and API-policy obligations remain separate concerns. Check the actual Cloud project allocation. [Upload reference](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert), [revision history](https://developers.google.com/youtube/data/revision_history), [quota/audits](https://developers.google.com/youtube/data/guides/quota_and_compliance_audits)

Use resumable uploads and persist the upload-session URI. OAuth external apps left in Testing generally receive seven-day refresh tokens, so a short pilot is not proof of durable connectivity. [Resumable upload protocol](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol), [OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)

Let users control titles, descriptions, visibility and which platforms receive each clip. Square/vertical uploads up to three minutes can qualify as Shorts; a 30–60-second vertical export is a conservative starting profile, not a platform-wide maximum. [Required upload controls](https://developers.google.com/youtube/terms/required-minimum-functionality#uploading-videos), [Shorts classification](https://support.google.com/youtube/answer/15424877)

### TikTok is a product gate

TikTok's guidelines exclude uploader utilities limited to accounts managed by the developer/team and require creator controls/express consent. Therefore, a headless own-account clip publisher is a poor Direct Post approval premise. Unaudited Direct Post stays private; the `video.upload` flow instead creates an inbox draft. These are not interchangeable milestones. An approved creator-facing product or a provider explicitly supporting this use case may be viable, but must be confirmed rather than assumed. [Sharing guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines), [Direct Post reference](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post), [draft upload reference](https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video)

### Meta account and production access

Instagram professional accounts and Facebook Pages support asynchronous upload/process/publish flows. Public-file delivery is one route; supported resumable-upload routes depend on the login setup. Facebook's documented Reels cap is 30/rolling 24h/Page. Instagram documentation currently conflicts on 50 versus 100 posts/24h; query the account's returned publishing-limit configuration. [Instagram publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing), [Instagram quota reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit), [Facebook Reels](https://developers.facebook.com/documentation/video-api/guides/reels-publishing)

Own-asset testing and permission to onboard customers are different. Standard/Advanced Access, App Review, Business Verification and app production configuration depend on the chosen setup. Verify a published result outside the developer/app-role session; a test-visible post is insufficient. [Instagram review](https://developers.facebook.com/documentation/instagram-platform/app-review), [Meta app modes](https://developers.facebook.com/documentation/development/build-and-test/app-modes)

## 5. Gaming quality is the other major uncertainty

The fact that a renderer detects faces does not establish good gaming composition. A full-height face crop can obscure the gameplay moment, and an in-game character can confuse a face detector. Start with a per-streamer fixed facecam/gameplay split, a gameplay-first fallback and caption safe areas; compare with automatic cropping. Test cutscenes, camera layout changes, missing facecams, HUD readability and rapid motion.

Similarly, transcript-only ranking misses visual action and can select excited commentary without its setup/payoff. Use speech, sound, optional chat velocity and sampled visual evidence as complementary signals. Disable unrelated B-roll for the gaming pilot. Provide language/game terminology context and inspect caption errors. A model's highlight/virality score is a ranking feature, not evidence of audience performance.

Build a small human-labeled set of representative stream hours. Measure event recall, usable clips/hour, review rejection rate, duplicate rate, crop/caption defects, processing latency and processing cost. Validate cheap prefilters against the **missed** events, not only the clips they retained. No inspected code establishes those quality metrics for the proposed workload.

## 6. Capacity and costs

Illustrative workload: one streamer, **8 hours/day × 30 days = 240 captured hours/month**.

- Ten-minute non-overlapping windows produce **48 submissions/day**, or 1,440/month if every window is submitted. This exceeds the default SupoClip 20-upload daily allowance. Configure the cap deliberately; filtering before upload reduces it. Overlap adds work.
- At a total input bitrate of **6 Mb/s**, raw capture is about **2.7 GB/hour**, **21.6 GB/day**, or **648 GB/month** before copies, temporary renders, output clips and backups. A seven-day raw retention policy is about 151 GB; a ring buffer materially reduces storage needs.
- With one active processing job/user, sustained full-window processing must average below the ten-minute arrival interval to avoid growing backlog. Capture must remain independent of slow rendering. Measure the full processing path on the actual host.
- Hosted ASR makes a GPU optional for transcription. Local Whisper shifts cost to compute and operations; it does not make processing free. The inspected final renderer uses CPU `libx264`, so installing CUDA does not automatically accelerate final video encoding. Start the pilot on a machine with adequate CPU, RAM and SSD, then choose capacity from measured throughput. Do not infer worker hardware sufficiency from Docker starting successfully. [Encoder source](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/media/ffmpeg.py#L310-L335)

Current AssemblyAI base prerecorded rates are **$0.15/hour Universal-2** or **$0.21/hour Universal-3.5 Pro**. That implies **$36–$50.40/month** for 240 processed hours, or **$9–$12.60** if a validated prefilter sends 25% of captured time. These figures exclude overlap/retries, add-ons, applicable channel billing, LLMs, hosting, storage and egress; verify the model the integration actually selects. [AssemblyAI pricing](https://www.assemblyai.com/pricing)

In particular, the inspected SupoClip ASR code enables speaker labels. At the listed $0.02/hour diarization add-on, that adds $4.80 for 240 hours: approximately **$55.20/month for Pro plus diarization**, before any further charges. [ASR request source](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/media/transcription.py#L358-L373), [AssemblyAI add-ons](https://www.assemblyai.com/pricing)

For a concrete LLM arithmetic example, Gemini 3 Flash Preview is currently listed at $0.50/million text-input tokens and $3/million output tokens including thinking. An assumed monthly workload of 20M input + 2M billed output tokens would be **$16**; this is an illustration, not an estimate of SupoClip's token consumption. Log actual usage and maintain a tested model/provider configuration rather than depend indefinitely on a preview name. [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3-flash-preview)

An honest all-in budget needs a measured render benchmark, selected host/GPU, retention policy, provider model and posting volume. The verified ASR subtotal is affordable at this scale; it is not an all-in service quote.

## 7. Effort and validation path

Planning estimates for one experienced engineer using the existing UI:

| Milestone | Indicative engineering effort | Evidence required |
|---|---|---|
| Controlled feasibility demo | 3–5 working days | One authorized live source, finalized windows, successful current API flow, acceptable rendered clips, authorized YouTube test |
| Reliable single-operator pilot with YouTube/Instagram/Facebook | About 4–7 weeks total | Supervised capture, retention/backpressure, replayable ledger, Facebook provider, review/scheduling, refresh/retry recovery, quality checks and sustained load test |
| Multi-customer product | Roughly 8–12+ weeks total, highly scope-dependent | Secure account isolation, onboarding, approval-compliant controls, operations/support and platform reviews |

These ranges exclude external approval waiting time and do not guarantee TikTok acceptance. Reassess them after the controlled demo; source compatibility and real account eligibility are untested.

Recommended sequence:

1. Prove the source, SupoClip bootstrapping, exact API contract, facecam layout and one-channel throughput. Test private/unlisted YouTube output deliberately.
2. Validate actual public publishing capability on each intended destination, using authorized controlled content and approved access. Start TikTok use-case/access validation early.
3. Add reliable capture/window assembly and integration recovery. Run an eight-hour capture with simulated disconnects and process restarts; inspect actual media gaps and backlog.
4. Add Facebook and complete Instagram setup. Keep review before publishing while measuring quality; automatic publishing remains destination-specific and must fit each approved flow.
5. Expand only after comparing retained/missed events and verifying duplicate prevention. Keep TikTok draft/manual completion if Direct Post is not appropriate or approved.

## 8. Licensing and content rights

SupoClip is AGPL-3.0; py-autovod is MIT. Private operation does not by itself require publishing every surrounding component. However, the proposal's claim that source duties arise **only** when offering a hosted service to external users is too narrow: AGPL section 13 addresses modified software used through remote network interaction, while distribution has separate obligations. Commercial use is possible subject to the license. A separate REST service is a useful engineering boundary, not an automatic legal exemption. Rendered video is not automatically AGPL-licensed merely because the tool created it. [AGPL text](https://www.gnu.org/licenses/agpl-3.0.txt), [GNU licensing FAQ](https://www.gnu.org/licenses/gpl-faq.html), [py-autovod license](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/LICENSE)

For streamer clips, establish permission for capture, edits and republication; publishing-account OAuth and permission to reuse the underlying stream are different. Game footage, in-stream music and reused-content monetization are further considerations. Automatic cropping/captions do not establish permission or monetization eligibility. [YouTube gaming content](https://support.google.com/youtube/answer/138161), [YouTube monetization policy](https://support.google.com/youtube/answer/1311392)

**Recommendation:** proceed with a bounded proof of concept around SupoClip and a capture adapter. Target YouTube first, then Instagram professional accounts and Facebook Pages. Keep TikTok conditional on an accepted publishing flow. The project is feasible; a guaranteed hands-off four-platform publisher is not established by the two repositories.
