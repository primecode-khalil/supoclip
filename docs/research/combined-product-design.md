# Combining SupoClip and py-autovod without losing their features

Research date: **15 November 2026**. This is a source-backed product/integration design, not an implemented merge or a claim of tested runtime reliability.

## Decision

**Yes: combine the repositories into one product, using SupoClip as the application foundation and porting py-autovod's capabilities into explicit recording, archive, transcription and analysis modules.** Preserve all implemented user-facing capabilities through shared contracts and selectable processing providers. Keep the existing UI, editorial workflows, editor, account system, API/MCP, storage and publisher.

This is broader than a live-chunk REST bridge. It includes full VOD archives, archive conversion/export, local-file CLI processing, channel-specific settings, alternative ASR and ranking strategies, and original-aspect/fit-padded outputs. These should remain available alongside polished short clips.

Source presence does not establish that every advertised provider, configuration or feature combination works. Some shipped settings are unused, some features are rollout-gated, and the two repositories have different assumptions about media identity, timing and ownership. The merge should make those distinctions explicit.

Audited revisions:

- **SupoClip:** [`e42e93b02873d29e2000a6a8235c10e23f8c99c9`](https://github.com/FujiwaraChoki/supoclip/commit/e42e93b02873d29e2000a6a8235c10e23f8c99c9).
- **py-autovod:** [`424f49815aba773c85cc8a7851ac52c6554dfa96`](https://github.com/0jc1/py-autovod/commit/424f49815aba773c85cc8a7851ac52c6554dfa96).

The implementation inventories are [SupoClip SC-01–SC-10](supoclip-feature-inventory.md) and [py-autovod AV-01–AV-20](py-autovod-feature-inventory.md). The latter traces every shipped INI setting and all 13 source modules. [The contract audit](merge-contracts-audit.md) records exact format, lifecycle and dependency boundaries. This document maps those findings into a proposed merged product.

An accompanying [architecture diagram](merge-architecture.html) summarizes the product and its archive/editorial branches.

## 1. What the deeper audit adds

SupoClip is substantially more than a renderer: it has five editorial workflows, automatic framing variants, non-destructive Clip Studio, AI editing, B-roll, server/browser exports, sharing, multi-account scheduling, performance-informed ranking, MCP/OAuth, account management and operational storage/recovery code. Replacing it with a new minimal UI would discard much of the useful feature set.

py-autovod contributes working channel monitoring, full-recording capture/remux/re-encode, local retention, rclone transfer, faster-whisper including batching, audio-enriched candidate selection, standalone file tools and INI-based per-channel configuration. Preserving only Streamlink capture would lose useful functionality.

Four integration findings materially change the design:

1. **Full archives need a first-class representation.** SupoClip's current task path accepts completed sources, limits default source length to 5,400 seconds even when self-hosted, and limits uploads to 4 GB. An eight-hour archive is not just another ordinary uploaded clip task. [Duration configuration](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/config.py#L106), [effective self-host limits](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/billing_service.py#L198-L203).
2. **A saved edit is not necessarily the published file.** Current social-post creation records a generated clip's file path; it does not select a Clip Studio export/document. At claim time the repository also replaces that path with the clip's current render for a new upload. A common publishable-artifact contract should support generated clips, final edited exports and full VODs, with claim/retry logic updated together. [Current post creation](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/social_service.py#L447-L535), [claim-time resolution](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/repositories/social_repository.py#L624-L663).
3. **One unchanged Python environment is already incompatible with the committed lock.** SupoClip's lock pins NumPy 2.4.4; py-autovod declares `numpy<2.4`. That proves a lock change or environment separation is needed, not that a combined dependency solve is impossible. [SupoClip lock](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/uv.lock), [AutoVOD requirements](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/pyproject.toml#L17-L37).
4. **Timing compatibility is central to feature preservation.** py-autovod's ASR produces segment seconds without requesting word timestamps. SupoClip uses word timing plus source-range maps to reconstruct edited sources and captions. The adapter must preserve both; JSON field renaming alone is insufficient. [AutoVOD transcription](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/transcription.py#L188-L233), [SupoClip source maps](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/clip_source_map.py).

## 2. Feature-preservation map

“Keep” means retain the existing implementation and compatibility surface. “Adapt” means preserve the behavior through the merged contracts; it does not promise byte-identical output or existing defects. Provider credentials, rollout flags and platform eligibility still apply.

### SupoClip: keep the application feature set

| Inventory | Capabilities to retain | Merge action |
|---|---|---|
| SC-01 | YouTube imports, Twitch/Kick VODs and clips, local upload, direct object-storage upload, processing modes and creation defaults | Keep current import paths; add recorded assets as an additional source adapter. |
| SC-02a–e | Highlights, ordered series, topic extraction, recap, trailer, instructions and advanced controls | Keep all planners and workflow-specific duration/assembly rules. Recorded sessions may feed any supported completed-source workflow. |
| SC-03 | AssemblyAI, local Whisper, YouTube captions, multiple LLM providers, ranked reserve candidates, visual suitability checks, pause/filler cleanup | Add faster-whisper and audio enrichment through provider contracts; preserve existing behavior and switches. |
| SC-04 | Automatic vertical/fit/pan/split/original framing; speaker/reaction/interview/content-aware layouts; seven caption templates; custom fonts, hook titles and caption placement | Reuse render paths and source maps. Add the simple padded Shorts rendition as a preset. |
| SC-05 | Clip Studio drafts, precise timeline/caption edits, transforms/effects/audio controls, undo/recovery/JSON backups; legacy trim/split/merge/regeneration APIs | Keep versioned edit documents and legacy routes. Prepare clean source media from recorded assets, not caption-burned outputs. |
| SC-06 | Natural-language AI editing, allowances and provider choices; Pexels search/suggestions/placement and generation-time B-roll | Keep AI worker and B-roll mapping; make availability explicit per profile. |
| SC-07 | Task library, search/filter/grouping, SSE progress, cancellation/resume, public shares, ZIP, preset/batch exports and browser/server rendering | Add channel/session/archive views without replacing the task/editor/library functionality. |
| SC-08 | Multi-account OAuth, scheduling, privacy/copy/hashtags, status/retry/cancel, platform metrics and feedback into highlights/topic ranking | Extend posting to immutable output artifacts; keep existing provider behavior. Add Facebook separately. |
| SC-09 | Authentication, account deletion, API keys, signed requests, MCP transports/OAuth/18 tools; hosted billing, entitlements, creator/referral/Apple billing hooks | Retain interfaces; add channel/session/archive REST and CLI commands. New MCP tools are explicit additional work. |
| SC-10 | Preferences/localization/theme/tours, email/support/admin/runtime settings; PostgreSQL/ARQ, local/S3 storage, remote workers, replication/caches/health/logging | Preserve application services; extend health and tracing with channel/session/asset IDs. |

Inventory sources and implementation boundaries are linked per feature in [the SupoClip inventory](supoclip-feature-inventory.md). For example, generation supports custom fonts while Studio currently substitutes unsupported fonts; keeping existing behavior does not establish complete parity between export engines.

### py-autovod: bring its features into that application

| Inventory | Capability to preserve | Merged owner and changes |
|---|---|---|
| AV-01, AV-13 | `autovod`, single-channel operation, help/version, local-file processing, URL download tool | A supported CLI over the same services/API; preserve useful command aliases and remove import-time work. |
| AV-02 | `.env`, global config and streamer INIs | Versioned recording/processing/archive profiles plus an INI importer and effective-settings preview. |
| AV-03–AV-05 | Multi-channel monitoring, source/quality selection, custom recorder flags, metadata and recording identity | Channel/session service and supervised capture worker; normalize identities, retain partial captures, sanitize output names. |
| AV-06 | Start/stop and shutdown behavior | Explicit supervisor lifecycle, heartbeat/lease and interruption recovery; replace process-global daemons. |
| AV-07 | Full-VOD remux, optional codec/CRF/preset re-encoding | Archive-rendition jobs; validate completion and preserve the original until all dependents permit deletion. |
| AV-08 | Whisper/faster-whisper, model/device/language, CPU fallback, GPU batching | ASR provider adapter with word timing and capability reporting. Keep GPU dependencies out of capture-only images. |
| AV-09 | RMS/zero-crossing/spectral features, intensity, segment grouping, enhanced-transcript JSON | Versioned audio-feature artifact attached to the transcript; correct amplitude normalization and validate grouping. |
| AV-10 | Audio-enriched OpenRouter ranking, configurable model/temperature/token budget, batched candidates | A selectable analysis strategy with bounded concurrency, validated candidates and provenance. |
| AV-11 | Top-N scores/factors/platform recommendations, JSON artifacts, clean original-aspect clips | Candidate records and downloadable analysis artifacts; common rendering path with captions off/original aspect. |
| AV-12 | Additional 1080×1920 fit/pad Shorts output while keeping landscape output | A second rendition of the same clip, with its own success/failure state. |
| AV-14 | Full-recording YouTube upload and rclone export | Full-VOD publication adapter plus an archive-transfer provider. Prefer OAuth/account tracking; retain an explicit `youtubeuploader` compatibility adapter if existing binary/credential setups must continue working. |
| AV-15 | Upload retry/restore behavior | Durable archive/publication jobs with recorded attempts, handles, reconciliation and retention dependencies. |
| AV-16 | Keep/delete locally, keep on upload failure | Artifact-aware retention policies covering originals, archives, intermediates, clips and retry inputs. |
| AV-17 | CLI progress and logs | Shared structured job/session events, rendered as terminal progress and UI status. |
| AV-18 | Configuration-only/advertised features | Explicit backlog, not claimed working coverage; see section 7. |
| AV-19–AV-20 | Headless operation, installation and useful existing tests | Locked worker images/CLI package and migrated regression contracts. A minimal standalone deployment is a separate packaging choice. |

Every AV ID is covered above; detailed option-level behavior is in [the AutoVOD inventory](py-autovod-feature-inventory.md). Preserve the feature intent while correcting ignored options, unreliable cleanup and ambiguous statuses.

## 3. One product, with several workflows

The merged application should expose these independently selectable modes:

1. **Import and edit:** existing SupoClip completed-video workflows, unchanged.
2. **Record and archive:** monitor channels, keep full recordings, optionally remux/re-encode and transfer via rclone or publish a full VOD. AI is optional.
3. **Record then create:** after a recording/session ends, run one or more existing editorial workflows using the chosen ASR/ranking providers.
4. **Record, archive and clip near-live:** capture short finalized segments, assemble analysis windows, generate/review/publish clips during recording, and finalize the full archive afterward. This requires new window/timeline code.
5. **Headless automation:** CLI/API/MCP access to supported actions, backed by the same durable state. The existing MCP does not automatically gain new tools merely because REST gains endpoints.

Archives must not wait for successful AI analysis, and capture must not wait for rendering or uploading. Failed clipping should leave a usable archive; failed archive transfer should leave an eligible local retry input. A session's workflow settings should be snapshotted into a recipe so later preference changes do not silently alter work already queued.

## 4. Proposed source, artifact and job model

Extend the current task/source/clip/editor/social models rather than replacing their public identities. Names below describe proposed records, not tables already present:

```text
OwnedChannel → RecordingSession → CapturedSegment / SourceAsset
                                     │
                      ┌──────────────┴───────────────┐
                      ↓                              ↓
               ArchiveRendition                 AnalysisWindow
                      │                              ↓
                      ↓                       TranscriptArtifact
             ArchiveTransferJob                      ↓
                                            CandidateSet / WorkflowPlan
                                                     ↓
                                              Existing Task / Clip
                                                     ↓
                                          EditDocument / RenderArtifact

PublishJob → immutable RenderArtifact or ArchiveRendition
```

Each source asset needs an owner association, session ID, immutable revision/content identity, storage reference, actual duration, selected audio track, codec information and timing provenance. Sessions associate a broadcast/channel with segments and known capture gaps. A full archive may initially be a manifest of retained segments; a concatenated downloadable file is another rendition.

SupoClip's existing source-type constraint accepts `youtube`, `video_url`, `twitch` and `kick`; adding live sessions or DLive requires deliberate model/admission work. Ownership currently follows existing task access paths; newly introduced channel/session records need explicit ownership checks. Do not pass arbitrary recorder paths directly into the public task API. Use a trusted recorded-asset registration adapter that validates the durable media reference and intended owner. [Current model/contracts](merge-contracts-audit.md)

### Preserve both timelines

Store recording/session time separately from each file's media time. Maintain piecewise mappings across actual captured spans and gaps; ad skips/disconnects can make one constant wall-clock offset inaccurate. A candidate identifies ordered source spans, not just a filename plus two numbers.

Existing SupoClip source maps already preserve discontiguous ranges and actual output offsets, including reordering and crossfades. Retain those editor/render semantics. Add a preceding session-to-source mapping for captured media; never overwrite the editor map with a chunk offset.

### Extend publication once, for three output types

Support **generated clip**, **finished Studio export**, and **full-VOD archive** through an immutable asset/revision reference. Keep existing `task_id`/`clip_id` API compatibility by resolving them to the artifact internally. The published bytes should match the selected export revision; later editing should not change a scheduled post silently.

The legacy clip-post route can retain its current “latest generated render at dispatch” behavior as a documented compatibility policy. The new artifact route should pin the selected revision. If both policies are exposed, the UI must identify which one the scheduled post uses; preserving an old API must not silently redefine its media-selection semantics. A legacy external `youtubeuploader` adapter also needs an explicit unknown-outcome policy because that subprocess does not supply the native provider's durable upload handles.

Rclone is a storage transfer, not a social platform. Keep its jobs and results distinct from social metrics. Full-VOD performance should not be blended indiscriminately into short-clip ranking feedback.

## 5. Provider contracts that preserve alternatives

### Transcription and audio enrichment

The canonical result must retain transcript text, utterance/segment timing, **word timing**, optional speaker identity, detected language and provider/model metadata. Normalize timing units explicitly: faster-whisper returns seconds while SupoClip's word cache uses milliseconds. Preserve raw word confidence when available; absent diarization must remain absent, not invented.

Expose capabilities such as word timing, speaker labels, language support, offline operation and batching. Faster-whisper word timing alone does not supply diarization equivalent to AssemblyAI. Existing speaker-dependent layouts should use a documented fallback or an optional diarization step when the selected provider lacks labels.

Audio enrichment should be independently reusable across ASR providers. Request the renderer-selected audio track for ASR and features, and persist its identity. Keep the enhanced JSON downloadable for compatibility, while storing a versioned durable transcript/features artifact. SupoClip's current automatic sidecars are `.source_map.json` and `.transcript_cache.json`; AutoVOD's enhanced JSON is not automatically replicated by that mechanism. [Transcription/storage details](merge-contracts-audit.md)

### Candidate selection

Keep SupoClip selection as the default and offer AutoVOD audio-enriched ranking as another strategy. An optional combined strategy may augment SupoClip with calibrated audio features; superiority is unmeasured and requires comparison on labeled streams.

Validate candidate timestamps, bounds, duration, ordered spans, source coverage and schema before rendering. Keep raw score/scale/reasoning/provider as provenance. AutoVOD's 1–10 score is not equivalent to SupoClip's relevance score plus 0–100 virality components. Do not fabricate the missing component breakdown or assume a multiplication makes scores calibrated.

Top-N selection, score thresholds, clean output and padded Shorts should become independent processing/output choices. A failed rendition should not incorrectly mark every output failed or complete.

### Cache and retry identity

Include immutable media revision, selected audio track, transcript schema/provider/model options and audio-extractor version in relevant stage keys. Analysis needs its own strategy/model/workflow/version identity. Preserve SupoClip's existing frozen-plan retry behavior: changing a recipe should produce an explicit new run/regeneration rather than modifying completed outputs during resume.

The current task checkpoint stores timed transcript data and can restore sidecars. Reuse it. A future live-source adapter must not use only the broadcaster's stable channel URL as input identity for changing media. [Checkpoint input key](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/repositories/task_checkpoint_repository.py#L13-L25)

## 6. Runtime layout and reliability changes

Use one repository, UI, API, database and release version, with separately locked worker environments:

```text
frontend/                  existing SupoClip UI; add Channels / Sessions / Archives
backend/                   existing API/services/models/editor/social
  src/recording/           refactored AutoVOD capture and session coordination
  src/archives/            archive renditions, rclone transfers, retention
  src/providers/          transcription/ranking adapters (proposed package boundary)
workers/capture/           Streamlink/FFmpeg; optional browser dependencies
workers/transcription/     faster-whisper/Torch/audio dependencies as required
cli/                       supported headless commands and INI migration
mcp/                       retain current tools; extend deliberately
```

These paths are a proposed organization. Existing working module paths and APIs should remain compatible during incremental migration.

Long-lived recorder processes need a capture supervisor with a per-channel lease/heartbeat; do not place a multi-hour daemon inside an ordinary video job timeout. Share one job/state model, with isolated execution capacity for capture coordination, ASR, rendering, archive transfer and publishing. Current fast/balanced/quality modes do **not** route to dedicated worker pools: the job helper explicitly uses the default queue. [Queue routing](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/workers/job_queue.py#L81-L89)

Persist intended work before dispatch, dispatch idempotently, record attempts and reconcile on restart. Separate retryable/transient failures from terminal failures and unknown publication outcomes. SupoClip's ARQ `max_tries=3` is not proof of automatic stage recovery: its task service marks many failures `error`, and the exclusive-run guard skips error tasks until the resume path resets their state. Preserve manual resume while designing automatic policy explicitly. [Failure handling](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/services/task_service.py#L995-L1041), [task guard](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/repositories/task_run_guard.py#L33-L43)

Keep processing inputs until all dependent edits/exports/transfers/retries permit deletion. Raising upload/duration limits alone does not solve full-archive memory, storage, timeout or editor-source reconstruction requirements. Prefer segment/session representation with bounded analysis windows, and retain completed-source import for existing workflows.

## 7. Settings and missing features

Import existing INIs into validated profiles. AutoVOD streamer files currently replace `default.ini`; they are not overlays. First preserve each channel's effective settings, then offer explicit inheritance. Report ignored settings in the migration preview rather than silently claiming they worked. Treat credentials as secret references and restrict recorder/transfer options to the deployment's supported capabilities.

The following require **new implementation**, not merging two existing implementations:

- Rolling live windows, overlap/event deduplication and chat/audio-triggered extraction.
- Chat log archival/chat-velocity collection and LLaVA-style visual-event ranking.
- Facebook publishing.
- AutoVOD's configured duration/split controls, YouTube metadata/playlist templates, rclone rename/extension and several cleanup options that are unused today.
- A general full-source manual clipping timeline, if desired; current Studio begins with a generated clip/source range.
- Caption translation/dubbing, music/voiceover/stickers or collaborative project folders.

Other important boundaries: AutoVOD's Shorts code **fits and pads**, rather than face-cropping; SupoClip exposes transition-list APIs but disables standalone generation transitions; Studio/browser/server/custom-font behavior has existing differences. The native iOS application source is outside these repositories. Preserve the server integration hooks without promising ownership of that separate app.

“All features available in one product” does not mean every ASR provider supplies every speaker feature, every output destination accepts full VODs, every platform allows unattended public posts, or the complete stack retains the deployment footprint of a standalone CLI. Capability-aware UI/validation is part of the merge.

## 8. Concrete implementation sequence

1. **Freeze the baseline and preserve regressions.** Keep the full SupoClip product, both inventories and useful AutoVOD tests; record platform/environment dependencies. Establish a clean supported build before changing the pipeline.
2. **Introduce owned sessions, assets and artifacts.** Add channel profiles, immutable media references, session timeline/gaps, archive records and publishable exports. Extend migrations and retain old API/clip IDs.
3. **Port batch/archive capabilities.** Namespaced recorder, full-recording remux/re-encode, rclone, retention and CLI/INI import. Complete one record→archive→transcribe→workflow→edit→publish flow before rolling processing.
4. **Add ASR/ranking alternatives.** Faster-whisper word timing, calibrated optional audio features, candidate validation and durable sidecars/cache identities. Check speaker-layout fallback and local execution choices.
5. **Expose integrated UI and outputs.** Channels, recording/session health, archive actions, effective profiles and selection of the actual edited export for publishing. Preserve localization, accessibility and all current task/editor paths.
6. **Add near-live mode.** Short finalized segments, window materialization, source maps, bounded queue/disk policies and overlapping-event deduplication. Finalize the full archive independently.
7. **Extend destinations and harden.** Facebook provider, any additional MCP tools, controlled destination tests and fault-injection pilot. Platform approval remains outside code-merging guarantees.

The full feature-preserving scope is larger than the earlier 4–7-week single-operator pilot. Re-estimate after the baseline build and first vertical slice; do not use the small REST-bridge estimate as a commitment for the complete union of features.

## 9. What would demonstrate success

No regression suite or live workflow was executed in this audit. Existing test code and CI were inspected: SupoClip has backend/database/editor/workflow/social tests, frontend unit/browser tests and MCP tests; AutoVOD has useful mocked command/configuration/upload tests. Their presence is evidence of testable seams, not proof that a merged build passes.

Acceptance should trace **every SC and AV inventory entry** to a retained behavior, adapter test or explicitly labeled new-work item. In addition to the existing suites, verify:

- One recording produces a retained full archive, a clean landscape clip, a padded Shorts rendition and a captioned/edited clip; each has independent status and durable identity.
- Whisper/faster-whisper/hosted ASR produce valid common transcripts; word timing remains aligned after chunk offsets, pause cuts, reordered spans and B-roll edits.
- All five editorial workflows and legacy edit/export/API/MCP paths still work with imported and recorded sources.
- A final Studio export, not an older generated clip, is the artifact selected for a scheduled post.
- Both complete-recording and near-live modes survive restarts/disconnects; every finalized segment/job is accounted for and actual source gaps remain visible.
- An eight-hour source can be archived and processed without accidentally hitting the old 90-minute source/4-GB upload assumptions or losing editor source coverage.
- Slow rendering, full disks, expired credentials, lost upload responses and rclone failure do not stop unrelated capture or cause blind duplicate posts.
- Retention does not delete an original needed for an edit, transfer or retry; restored legacy jobs are not duplicated.
- Profile import reports ignored INI settings and preserves working settings; CLI help/version has no upload/worker side effects.

Use a controlled 48–72-hour fault-injection pilot as an initial gate, then longer operational evidence. Hardware throughput, platform delivery continuity and subjective highlight quality still require measurements.

## 10. Licensing and maintenance

Keep SupoClip's AGPL obligations and preserve AutoVOD's MIT copyright/license notices for imported code. Source provenance should identify the imported revision and upstream modules. The combined product can use isolated workers for maintainability and dependency control; that organization is not a claim of a licensing exemption. The earlier [feasibility study](feasibility-study.md) covers publishing/account and content-rights constraints.

**Recommended outcome:** a SupoClip-based product with integrated channel recording, complete archives, alternate local ASR/audio analysis, CLI automation and archive destinations, while preserving the complete SupoClip editorial/editor/publishing surface. This covers the implemented feature union through a deliberate refactor; genuinely missing features remain visible development work.
