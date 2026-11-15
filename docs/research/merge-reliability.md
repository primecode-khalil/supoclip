# Reliability of a feature-preserving merge

Assessed 15 November 2026 against the same pinned source revisions as [the feasibility study](feasibility-study.md). This addresses the clarified goal: one product containing useful features from both repositories. No combined build, runtime benchmark or reliability test has been performed.

## Assessment

**The feature combination is viable. Its unattended reliability is unproven, and the inspected code contains recovery defects that should be fixed before relying on it.** Combining the code does not automatically combine its reliability. A production-minded merge is an integration and recovery refactor, not simply a repository rearrangement.

SupoClip is the stronger foundation for the merged product's UI, authentication, database, job orchestration, rendering, review and social publishing. Preserve py-autovod's unique behavior as integrated capabilities:

- Channel monitoring and livestream recording.
- Full VOD storage, remuxing and optional re-encoding, alongside short clips.
- Archive export through rclone.
- CPU/CUDA faster-whisper, including its optional batched inference path.
- Audio features supplied to highlight selection, after correcting/calibrating them.

Alternative ASR and ranking implementations should remain selectable. A source should have one authoritative transcript/candidate schema, and each requested workflow should explicitly select its providers. There is no need to transcribe or publish everything through both existing pipelines.

## Concrete merge risks

**Recording recovery:** py-autovod skips processing partial recordings after a nonzero recorder exit, discards recorder stderr, and sleeps between recording attempts. A merged recorder must preserve usable finalized media, expose gaps and reconnect independently of downstream processing. [Recorder source](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/stream_monitor.py#L110-L179)

**Work recovery:** its processing queue is memory-only; its upload snapshots omit in-flight work. The inspected conversion path also ignores FFmpeg's exit status. Transfer this lifecycle to durable database records plus dispatch/reconciliation through the existing ARQ infrastructure. A database and Redis alone do not prove reliable delivery: persisting intent, retry policy and restart reconciliation are required. [Processor source](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/processor.py), [uploader source](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/uploader.py#L315-L366)

**Transcript compatibility:** py-autovod currently emits segment start/end/text/features and does not request word timestamps. SupoClip uses word timing for captions. Its faster-whisper capability needs an adapter that requests and preserves word timing, rather than forwarding its existing JSON unchanged. [Transcription source](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/transcription.py#L188-L233)

**Import/process behavior:** py-autovod loads global INI settings and instantiates processing/upload singletons during import. Importing those modules into an API process can start unintended work. Refactor explicit startup/shutdown and configuration injection, or initially isolate those workers. A merged repository can still build separate worker images. Python/Torch/CUDA dependency compatibility has not been resolved or tested. [Processor initialization](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/processor.py), [settings](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/settings.py)

**Highlight quality:** audio features are genuinely passed to the LLM. However, the RMS calculation uses unnormalized PCM samples with thresholds of 0.1 and 0.3. That scale mismatch likely makes the volume labels unhelpful; the effect on selections is unmeasured. The advertised 30/70 audio/text weighting is an LLM prompt instruction, not a calibrated numerical scoring function. No visual-event analysis pipeline was found. [Audio features](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/transcription.py#L71-L109), [ranking prompt](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/gen_clip.py#L48-L99)

**Shared resources and retention:** use one authoritative job/data model with separate worker capacity for capture coordination, ASR, rendering, archive transfers and publishing. SupoClip currently allows video and social jobs in the same worker queue; long renders can consume publication capacity. Delete originals only after dependent jobs and the chosen retention policy permit it. Full-VOD YouTube publishing also requires extending the current clip-specific social-post contract. [Worker configuration](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/workers/tasks.py#L335-L377), [post contract](https://github.com/FujiwaraChoki/supoclip/blob/e42e93b02873d29e2000a6a8235c10e23f8c99c9/backend/src/api/routes/social.py#L212-L248)

## Reliability gates for the merged product

Start with complete-recording workflows, which avoid near-live window assembly. Add near-live workflows after common schemas and recovery are established. The product can expose both modes while using the same library, review and publishing interfaces.

Before unattended operation, run a proposed 48–72-hour pilot with forced process/container restarts, recorder disconnects, failed FFmpeg jobs, low disk space, slow rendering, failed archive transfer and ambiguous publishing responses. Require:

1. Every finalized captured segment remains accounted for after restart, and source gaps are explicit.
2. Queued work survives restart and interrupted jobs have a defined recovery outcome.
3. Successful destination posts are reconciled before retry, preventing blind duplicate uploads.
4. Capture continues during downstream failures; backlog and disk use remain bounded.
5. Originals remain available while needed for clips, archives or retries.
6. Separate quality review establishes usable highlights, word timing and gaming composition.

These are proposed acceptance conditions, not achieved results or proof of a long-term uptime percentage. External stream delivery, social API access and subjective highlight quality remain separate constraints after internal recovery is hardened.
