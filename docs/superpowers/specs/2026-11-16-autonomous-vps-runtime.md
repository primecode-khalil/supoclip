# Autonomous VPS runtime

The fork will monitor explicitly enabled Twitch, Kick and YouTube channels, record finalized media segments, submit overlapping windows to SupoClip's existing captioned vertical rendering pipeline, retain originals, and enqueue selected clips through the existing social publisher. This extends the accepted combined-product design; it does not replace the editor, workflows, authentication or publishing adapters.

## Runtime contract

- One PostgreSQL lease per channel, fenced by a monotonically increasing generation and database-clock expiry. Stale processes cannot update work. Losing a lease stops owned capture children.
- Automation is opt-in per channel. Strict owner-scoped policies select segment duration (default 600 seconds), overlap (60 seconds), caption template, quality, score threshold, posting limits and connected destination accounts. Empty destinations mean no publication.
- `CAPTURE_ROOT` is persistent storage, separate from scratch `TEMP_DIR`. Closed CSV segment entries, ffprobe validation, checksums and atomic window creation establish readiness. Never process a file still being written.
- Probe outcomes distinguish live, offline and unknown. Network errors preserve originals and trigger bounded backoff. Process restarts start a new capture epoch; absolute segment positions and provenance are persisted rather than inferred from moving-window timestamps.
- A durable window ledger records immutable media identity, upload reference, native task ID, attempts, retry time and publication receipts. Upload/task retries reconcile existing work before creating another job. Ambiguous publication outcomes block duplicate submissions.
- Build windows from finalized contiguous segments, retaining an overlap from the preceding segment where available. Do not concatenate across capture epochs. Filter clips confined to the repeated overlap and deduplicate overlapping candidates within a window.
- Native task admission, word-level captions, rendering, editor and social OAuth remain authoritative. A trusted supervisor signs requests as the database channel owner with the server authentication secret. No owner-supplied command flags, arbitrary source URLs or credential fields.
- Originals are preserved locally until retention and completed dependencies permit deletion. Optional server-configured rclone copies originals off the VPS; a failed copy is retryable and prevents cleanup. Retention must never delete pending/blocked work. Disk pressure stops new capture before data loss.
- Unattended processing automatically retries transient failures with bounded exponential delays. Authentication/policy failures and ambiguous external effects are visible and blocked for operator action. Native render failures use existing resume behavior with a bounded retry budget.

## Dashboard and installation

The user clarified that no VPS or channel information is needed during development. A single Linux script installs the stack; browser setup claims the first owner, configures encrypted AI/OAuth app credentials, connects social accounts and manages channels. The dashboard shows lease health separately from recording evidence, native render progress, session/window history, policies and explicit retries. AMD64 and ARM64 Docker hosts are supported; unsupported architectures fail early.

## Deployment and verification

One VPS runs the web app, backend, native video/cron workers, recording supervisor, PostgreSQL, Redis and TLS proxy. Databases are private; persistent volumes and bounded logs survive restarts. Deployment includes environment validation, health checks, backup/restore instructions and explicit CPU/GPU guidance. Existing dependency locks and patched image versions are preserved; new packages are locked.

Verify owner isolation, fencing, lease expiry, replayed segments, partial files, source path traversal, process crashes, restart reconciliation, publication uncertainty, posting caps, and synthetic FFmpeg recording. No real social publication or deployment is claimed without configured credentials and a target VPS.

## Boundaries

This implementation provides unattended operation after account/channel/provider setup. It cannot guarantee platform availability or approval. Facebook publishing is a separate provider implementation; TikTok's reviewed-app and creator-consent requirements may prevent a private fully unattended deployment. Full VODs remain reproducible from archived segments and manifests; long-form social upload and additional ASR/GPU donors are subsequent extensions, not advertised as already present.
