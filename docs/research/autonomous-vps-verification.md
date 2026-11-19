# Autonomous fork implementation and verification

Verified on 16 November 2026 on branch `feat/recording-foundation`. The fork survey and donor-specific findings remain in [forks/summary.md](forks/summary.md). No complete production-ready hybrid was found; the implementation keeps SupoClip's current APIs, authentication, rendering, editor and social workers, and adapts the capture/recovery/archive ideas into that architecture.

## Implemented

- One Linux installer with AMD64/ARM64 detection, private generated server settings, optional HTTPS, protected first-owner setup and safe first-install recovery.
- A `/recording` dashboard for channels, strict automation policies, capture versus monitoring status, native rendering progress, session/window history and explicit blocked-work retries.
- Encrypted administration of AI and social app credentials, alongside existing account OAuth connections.
- PostgreSQL leases with database-clock expiry and fencing, finalized CSV segments, media validation/checksums, durable overlapping windows, restart recovery and immutable work receipts.
- Separate capture monitoring and processing tasks, disk/backlog guards, bounded retries, optional rclone archives and conservative retention.
- Native captioned vertical rendering and score-filtered YouTube/Instagram publication. Account ownership, current destination revocation, visibility, daily submission limits and temporal overlap reservations are checked before new submissions.
- Atomic native task/post request identities. A deleted social history row preserves a publication tombstone instead of allowing a repeated upload.

## Evidence

| Check | Result |
| --- | --- |
| Complete backend suite in the Debian ARM64 image, real PostgreSQL and Redis, actual FFmpeg/libass | 3,493 passed, 2 skipped |
| Additional fresh-schema compatibility and recording integration checks after the final additive migration | 36 passed |
| Complete frontend suite on the local Node 26 host | 981 passed with `--no-experimental-webstorage` |
| Real Next.js browser workflows with demo API fixtures | 8 passed; desktop/mobile screenshots, GIF and video recorded; the daily-cap notice was also checked in the running app |
| Publication-cap restart/receipt handling and recording/social regressions | 300 passed |
| Linux installer/configuration/recovery checks | 14 passed |
| Prisma validation, TypeScript, focused frontend lint and shell syntax | Passed |
| Backend/frontend production ARM64 image builds | Passed |
| Chromium JavaScript, locked Streamlink CLI and FFmpeg caption filters inside the deployment image | Passed |
| Production Compose cold start with the patched PostgreSQL image | All nine application/infrastructure services healthy |
| Actual production first-owner flow through Caddy and Next.js | Missing token rejected; initial owner became admin; later signup rejected; administration, channel creation, policy changes and progress APIs passed |
| PostgreSQL privilege-helper patch | ARM64 and AMD64 builds and critical-vulnerability gates passed; fresh and retained-volume initialization and UID 70 execution verified |
| Final deployment image security gate | Backend, frontend, patched PostgreSQL, Redis and Caddy passed the existing Trivy policy for fixable critical findings |

The first Debian suite exposed an unchanged upstream raw-video measurement test that let FFmpeg choose 25 fps for a 30 fps input. The same failure was reproduced on pristine upstream. Adding `-fps_mode passthrough` to the test's frame-measurement command preserved all 60-frame and cut-location assertions; production rendering already explicitly selects its frame rate. Its 32-test suite passes on Debian and macOS.

The cold-start test also exposed a pre-existing frontend/backend schema mismatch: Prisma expected Stripe routing columns absent from fresh backend databases. An additive migration now mirrors the frontend schema. A regression test creates the actual installer schema, applies backend migrations, and checks every modeled Prisma scalar column.

The stock PostgreSQL image contained gosu 1.19 compiled with Go 1.24.6, triggering CVE-2025-68121. The deployment [rebuilds the same helper](../../deploy/vps/postgres/README.md) using pinned sources/modules and a patched compiler; the server stays on PostgreSQL 15. No scanner exclusions or version-metadata removal were used.

## Practical limits

No real stream, ASR/LLM account or social destination was used in these checks, and no external VPS was provisioned. The production setup test used generated internal credentials and demo data. Browser workflow proof uses the running Next.js app with demo API fixtures; it is not evidence of a real social publication.

Provider-specific live ingestion and actual captioned generations/publications still need an authorized acceptance test after the operator configures accounts. Native rendering is retained, not replaced by a new rendering implementation. Editorial quality depends on source material, transcription, model choices and selected policies.

Autonomous posting currently covers YouTube and Instagram. Instagram requires explicit public visibility and appropriate account/app setup. TikTok retains its native interactive publishing flow; autonomous consent handling and a Facebook provider are not implemented. Additional donor ASR/GPU adapters and assembled full-VOD publishing are not advertised as implemented.

Container restarts, lost API responses and routine transient failures have recovery paths. A lost VPS disk, rejected platform credentials, inaccessible source, ambiguous external publication or corrupted original can still require operator action. Temporal deduplication works within a capture epoch; it does not establish semantic uniqueness across unrelated recordings. Follow the [backup and maintenance runbook](../vps-autonomy.md) before calling a particular deployment ready for unattended operation.
