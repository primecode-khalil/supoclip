# SupoClip + py-autovod: integration-contract audit

Audited 2026-11-15 from supplied source snapshots: SupoClip **`e42e93b02873d29e2000a6a8235c10e23f8c99c9`** and py-autovod **`424f49815aba773c85cc8a7851ac52c6554dfa96`**. This is source inspection, including committed dependency metadata; no combined dependency resolution, deployment, capture, or upload was performed. **Current** describes inspected behavior; **proposed** describes changes required for one product.

The merge is feasible, but sharing files between the existing pipelines would lose behavior and introduce ambiguity. Keep SupoClip's task/review/editor/social surfaces; integrate recording, archival, local ASR and acoustic ranking behind explicit contracts. One product can use separate capture, CPU/GPU and publishing worker images.

## 1. Transcript timing, identity and speakers

**Current:** py-autovod's `transcribe_with_features()` emits a JSON array of `{start, end, text, audio_features}` in **seconds**. It groups consecutive ASR segments until `clip_duration`, averaging their features and discarding their individual boundaries. Neither engine requests word timestamps; the saved result has no word IDs, speaker labels, word confidence or language metadata. Its `batched` option batches faster-whisper inference, independently of ranking's `chunk_size`. [Transcription and grouping][p-transcript]

SupoClip's transcript cache is version 2: `words`, `utterances`, `text`, `language_code`; words contain `text/start/end/confidence/speaker` with times in **milliseconds**. AssemblyAI preserves diarization; the existing Whisper adapter assigns `speaker=None`. Editor `Word` and `Segment` instead use **seconds**, require unique IDs, and live on the prepared clip's timeline. Initial word IDs are `word-{i}`, scoped to that editor draft; neither current transcript format supplies durable session-wide word identity. [Cache serialization][s-cache], [Whisper adapter][s-transcript], [editor models][s-document], [editor preparation][s-editor]

**Proposed:** request word timestamps from both local engines, preserve raw segments, and derive acoustic/ranking windows separately. Add immutable transcript revision and stable word/utterance IDs; preserve nullable confidence and speaker identity without fabricating certainty. Namespace diarization labels by ASR run and reconcile overlapping windows before treating two `Speaker A` labels as one session speaker. A local provider without diarization can retain captions but cannot reproduce AssemblyAI-driven active-speaker framing. [Speaker consumer][s-speaker]

Do not feed already-normalized cache dictionaries through `_whisper_result_to_transcript_data()`: it assumes Whisper input, rewrites speakers, and scales **float** word times but treats integer word times as milliseconds. An adapter emitting integer seconds could therefore acquire a 1,000-fold error. Conversion must depend on an explicit unit, never Python numeric type. [Conversion implementation][s-transcript]

## 2. Acoustic evidence, candidates and scores

**Current:** py-autovod computes RMS from unnormalized integer PCM cast to float, classifies volume using `0.1/0.3`, and averages features equally across segments rather than by duration. Its prompt requests 30% audio/70% content weighting; this is an LLM instruction, not a numerical scoring function. `parse_clip_data()` checks six keys only: `name/start/end/score/factors/platforms`. It does not validate numeric types, finite times, source coverage, ordering or score range. Later sorting and `score >= min_score` assume appropriate types. [Features][p-features], [ranking/parser/extraction][p-ranking]

SupoClip validates relevance in `0..1`, virality total in `0..100`, and four component scores in `0..25`; `_validate_segments()` grounds text and bounds against transcript lines and repairs/rejects unsuitable durations. Those checks depend on SupoClip's formatted transcript representation. [Typed scores][s-ai-models], [candidate validation][s-ai-validation]

**Proposed:** retain py-autovod's original `1..10` score with provider/model/prompt provenance; a displayed conversion must be labelled and must not invent SupoClip's component scores. Route every provider's candidates through shared numeric, coverage, duration and transcript-grounding validation before rendering. Preserve `factors` as reasoning and `platforms` as advisory metadata, never publication authorization. Version acoustic extraction, normalize samples consistently, record sample rate/channel/normalization, and recalibrate thresholds before claiming improved selections. Keep acoustic windows in original source time even when editorial cleanup removes pauses or filler words.

## 3. Rendering and media references

**Current:** py-autovod creates the original-aspect clip plus an optional 1080×1920 black-padded variant. `extract_clip()` returns only the original path and can report success when shorts conversion fails. Filenames derive from sanitized titles; identical titles can overwrite outputs, while `top_clips_one.json` is reused within a recording directory. SupoClip supports `vertical`, `vertical_fit`, `vertical_pan`, `vertical_split`, `original`, captions, reframing and editable assets. Importing a py-autovod MP4 as the sole clip record would discard the second rendition and its failure state. [Extraction][p-extract], [output formats][s-common]

SupoClip source maps store **ordered** source ranges and output offsets; ranges can be repeated/reordered for a teaser and offsets can overlap for fades. `resolve_render_ranges()` may snap sentence edges, extend an ending, remove material and cap duration. Its pairs identify positions within one source, not a multi-file live session or capture discontinuity. A sorted union of ranges would therefore change existing edits. [Source-map contract][s-map], [range resolution][s-ranges]

**Proposed:** preserve raw recording, remux, optional archive encode, clean clip and each rendered rendition as distinct immutable assets. Represent a timeline as ordered references to media revisions with explicit input ranges, output offsets and transitions. Maintain two mappings: session/capture time → recorded media, then recorded media → edited output. Record missing capture intervals separately from silence; sentence extension and pause cleanup must not cross an unavailable interval or mistake absent footage for an intentional editorial cut. Preserve existing `source_map` behavior through an adapter.

`MediaStorage` already distinguishes durable `s3://` references from leased local files and signs URLs after access checks; URLs are delivery handles, not identities. Its automatic sidecars are only `.source_map.json` and `.transcript_cache.json`, so py-autovod's `.enhanced_transcription.json` is not automatically durable. Its cleanup reference index knows clips/tasks/uploads and active publishing, not recording sessions, manifests or archive dependencies. Extend persistence and reference accounting before putting captured assets under its cleanup policy. [Storage][s-storage], [cleanup][s-cleanup]

Full-VOD processing needs a separate master/archive path rather than clip rendering. Default `MAX_VIDEO_DURATION=5400` also governs self-host upload admission through `BillingService`, and the worker checks duration again; self-host mode alone does not remove that 90-minute default. Larger recordings need explicit configurable limits and/or session segmentation. [Configuration][s-config], [self-host limits][s-billing], [worker duration guard][s-video-guard]

## 4. Ownership and configuration

**Current:** SupoClip `Task` owns `user_id`; `Source` has no owner and permits only `youtube/video_url/twitch/kick`. Upload ownership is enforced through upload records and S3 owner prefixes, with authenticated API-key/session entry points. A channel URL or arbitrary recorder path cannot substitute for that ownership chain. DLive/Rumble enum entries cannot simply become new `Source.type` values. [Models][s-models], [task creation][s-create], [authentication][s-auth]

py-autovod `_load_configuration()` chooses the streamer's INI **or** `default.ini`; it does not merge missing channel fields with defaults. Some behavior is channel-specific, but `_process_single_file()` reads clip count/shorts from global `config`; ASR and ranker settings are globals loaded at import. Thus a per-streamer `shorts_format` entry is not the value used by that processing function. [Channel settings][p-monitor], [global processing settings][p-processor]

**Proposed:** add owned `Channel`, `RecordingSession` and `MediaAsset` records, with explicit server defaults → user preferences → channel overrides → request overrides, then validate and snapshot effective settings for each job. Preserve ASR engine/model/language/device/batch, ranking provider, capture quality/flags, render assets/options, archive encoding, destinations and retention independently. Store credential references rather than secrets in job payloads. Keep streamer/platform IDs separate from display names and filesystem paths. CLI/API requests inherit the authenticated owner; capture workers receive scoped assignments rather than accepting user-supplied owner claims.

## 5. Full VOD, archive and social publishing

**Current:** py-autovod's processor submits the converted/re-encoded **whole recording** to its uploader. `upload_youtube()` supplies only `-filename`; configured title/description/visibility/playlist do not reach that call. `upload_rclone()` copies the existing basename to a remote/directory; configured filename/file extension do not rename or remux it. Preserve implemented upload/archive behavior while distinguishing these unused configuration promises. [Uploader dispatch][p-uploader], [processor dispatch][p-processor]

SupoClip's social API requires `task_id/clip_id/social_account_id`. `create_post()` verifies task/account ownership; `_resolve_publish_media()` rejects missing `clip_id`. More subtly, `SocialRepository.claim_post()` **replaces `source_file_path` with the clip's current render** when claiming a new upload. Merely adding a full-VOD path to `social_posts` would be overwritten or rejected. The API also has no editor-document/export-artifact selector: it publishes `generated_clips.file_path`, so the generalized subject should support a chosen final studio export too. [Social service][s-social], [claim implementation][s-claim]

**Proposed:** generalize the publish subject to an owned artifact/rendition, retaining optional task/clip lineage. Extend API, caption generation, repository claims, media delivery, metrics snapshots and deletion/cancellation logic together. Preserve pending-upload handles and unknown-outcome handling. Define whether scheduling follows the latest render or an immutable selected revision; SupoClip currently follows the latest render at claim. Archive transfers are separate jobs with destination/receipt/checksum state, not fake social posts. Long-VOD YouTube metadata and playlist support are extensions, not current functionality. Connecting social accounts remains session-authenticated; existing API keys may publish through already-connected accounts. [Social routes][s-social-routes]

## 6. Checkpoint and failure semantics

**Current:** SupoClip already stores timed transcript data in DB checkpoints, restores missing sidecars, invalidates plans after re-transcription, and commits completed clip positions for resume. However, its checkpoint key covers URL/type/mode/clip length/ASR provider/language/Whisper model, not immutable media revision or acoustic/ranking implementation. A recurring channel URL is unsafe as session identity. [Checkpoint key][s-checkpoint], [timing restoration][s-video-checkpoint], [completed positions][s-task-positions]

An ordinary processing failure sets task status to `error`; `exclusive_task_run` skips `error/completed/cancelled`. Therefore ARQ's three tries do not establish three actual processing attempts: a later attempt encountering `error` is skipped until resume resets state. Capture reconnection, stage retry and user cancellation require separate states. Video/editor/social jobs currently share `supoclip_tasks`; the named fast queue is not selected by `enqueue_processing_job()`. [Failure status][s-task-failure], [run guard][s-run-guard], [queue routing][s-queue]

**Proposed:** introduce durable stage jobs with input revision/fingerprint, dependency IDs, attempt/heartbeat/lease, retry classification, terminal result and output asset IDs. Persist dispatch intent transactionally and reconcile it to queue delivery; that outbox is proposed, not already supplied by ARQ. Include transcript, feature, selection and renderer revisions in appropriate fingerprints. Append near-live candidates by stable ID; positional `completed_positions` alone is unsuitable when a growing plan is re-ranked. Reference-count session/clip/archive/publish dependencies before retention permits deletion. py-autovod currently may delete original/converted recordings even after permanent upload failure when both save flags are false; migrate that behavior into an explicit retention policy. [Uploader deletion policy][p-retention]

## 7. Proposed canonical contracts

These are new contracts, not existing repository models.

| Contract | Required fields/invariants |
|---|---|
| `SessionManifest` | `id, owner_id, channel_id, external_stream_id?, settings_revision, started_at_utc, state`; segment sequence, media revision, timebase/PTS mapping, coverage and explicit gaps. |
| `TranscriptRevision` | `id, media_revision, provider/model/config_hash, language, timing_unit=ms, words[{id,start,end,text,confidence?,speaker_id?}], utterances`; finite valid intervals and explicit diarization capability. |
| `AcousticWindow` | `id, transcript/media_revision, source_interval, extractor_version, sample_rate, channel, normalization, rms/zcr/centroid`; validity flags and aggregation method. |
| `Candidate` | `id, session_id, ordered source spans, transcript_revision, text, title, reasoning, scores[{name,value,scale,provider}], evidence_window_ids, validation_result`; no ungrounded ranges. |
| `RenderSpec/Artifact` | `input revisions, ordered ranges/output offsets/fades, cleanup policy, layout/caption/font/B-roll references, dimensions/codecs`; one asset/status per variant, durable storage reference, hash, size, duration. |
| `DeliveryJob` | `owner_id, artifact_revision, kind=social/archive, account_or_remote_ref, metadata, schedule, attempts, provider_handle/receipt, outcome`; explicit publication/retention dependency. |

Extend SupoClip `Source/Task/GeneratedClip`, `TaskService`, `VideoService`, `ClipEditingMixin`, editor preparation, `MediaStorage`, checkpoint/cleanup/social repositories and social service around these contracts. Refactor py-autovod `StreamMonitor.download_video/run`, `Processor`, `transcribe_with_features`, `rank_clips_chunk/parse_clip_data` and uploader functions into injected adapters with explicit startup/shutdown. Importing `processor` currently starts its singleton processing thread; those lifecycle effects must not enter the API process. [Processor lifecycle][p-processor]

## 8. Proposed end-to-end session sequence

1. Authenticate owner; create channel/session and freeze effective configuration. Capture owns reconnects and numbered finalized media segments; validate each file, publish durable media/manifest state, and record gaps before dispatch.
2. **Batch:** after recording ends, finalize coverage and independently queue raw archive, remux and optional encode. Run selected ASR once; preserve timed transcript plus acoustic windows. Select, validate and deduplicate candidates; expose all existing SupoClip workflows against the same transcript.
3. **Near-live:** finalize shorter segments, assemble overlapping analysis windows across adjacent files, wait for necessary post-event coverage and translate local timestamps through the manifest. Deduplicate overlap words/candidates. Never re-rank completed outputs by changing positional identity. Capture continues when downstream work fails.
4. Render requested variants through shared specifications; retain every variant's status. Review/edit/export through SupoClip with correct source mappings. Deliver clips and full VODs independently; commit archive receipts and social handles before releasing their dependencies.
5. Retention considers queued/running retries, editing, archives and delayed publication. Show backlog, missing coverage and failed stages separately. Define session metering explicitly so overlapping near-live analysis windows do not accidentally charge repeated footage as unrelated full-source tasks.
6. Preserve `autovod --name` and file-processing CLI intents as authenticated clients of the same session/job services. Provide wait/status/retry/archive commands with durable IDs and meaningful exit codes; avoid a second independent CLI processing/uploader state machine. [Existing CLI intents][p-cli]

## 9. Dependency evidence and remaining verification

There is one demonstrated **existing-lock mismatch**: SupoClip locks `numpy==2.4.4`, while py-autovod declares `numpy<2.4`. Adding the unchanged package to SupoClip's frozen environment requires re-resolution or isolation. This does **not** prove no compatible joint solution exists. SupoClip's Python ≥3.11 satisfies py-autovod's ≥3.10. py-autovod has no committed lock, so Torch/torchaudio/torchvision/CUDA incompatibility is unproven; do not present it as established. Preserve separate worker images if helpful and generate/test platform-specific combined locks before consolidation. [SupoClip manifest][s-project], [committed NumPy resolution][s-numpy], [py-autovod manifest][p-project]

Acceptance must exercise integer/fractional timing, null/overlapping speakers, source gaps, repeated/reordered ranges, multiple renditions, duplicate titles, ASR revision changes, restart at every stage, archive failure, full-VOD ownership and scheduled publication after an edit. These are proposed checks; this audit establishes integration requirements, not runtime reliability or quality.

[p-transcript]: https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/transcription.py#L143-L255
[p-features]: https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/transcription.py#L71-L109
[p-ranking]: https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/gen_clip.py#L48-L171
[p-extract]: https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/gen_clip.py#L215-L330
[p-monitor]: https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/stream_monitor.py#L34-L56
[p-processor]: https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/processor.py
[p-uploader]: https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/uploader.py#L22-L80
[p-retention]: https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/uploader.py#L276-L302
[p-cli]: https://github.com/0jc1/py-autovod/tree/424f49815aba773c85cc8a7851ac52c6554dfa96/src
[p-project]: https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/pyproject.toml
[s-transcript]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/media/transcription.py#L208-L245
[s-cache]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/media/transcription.py#L450-L538
[s-document]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/editor_document.py#L31-L54
[s-editor]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/editor_service.py#L842-L885
[s-speaker]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/media/speaker_framing.py#L150-L172
[s-ai-models]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/ai.py#L162-L272
[s-ai-validation]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/ai.py#L1530-L1615
[s-common]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/media/common.py#L63-L65
[s-map]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/clip_source_map.py#L16-L174
[s-ranges]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/media/render_ranges.py#L61-L159
[s-storage]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/media_storage.py#L1-L230
[s-cleanup]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/workers/media_cleanup.py#L40-L148
[s-config]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/config.py#L106-L114
[s-billing]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/billing_service.py#L198-L244
[s-video-guard]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/video_service.py#L1493-L1500
[s-models]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/models.py#L158-L285
[s-create]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/task_service.py#L345-L432
[s-auth]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/auth_headers.py#L111-L136
[s-social]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/social_service.py#L447-L725
[s-claim]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/repositories/social_repository.py#L624-L663
[s-social-routes]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/api/routes/social.py#L1-L248
[s-checkpoint]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/repositories/task_checkpoint_repository.py#L12-L56
[s-video-checkpoint]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/video_service.py#L1520-L1556
[s-task-positions]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/task_service.py#L745-L781
[s-task-failure]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/task_service.py#L995-L1041
[s-run-guard]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/repositories/task_run_guard.py#L33-L43
[s-queue]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/workers/job_queue.py#L81-L89
[s-project]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/pyproject.toml
[s-numpy]: https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/uv.lock#L2677-L2679
