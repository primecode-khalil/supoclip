# Fork research and reuse decision

Research date: **16 November 2026, Europe/Bucharest**. Base revisions: SupoClip `e42e93b02873d29e2000a6a8235c10e23f8c99c9`, py-autovod `424f49815aba773c85cc8a7851ac52c6554dfa96`.

**Someone has already built parts of this, including an actual SupoClip-derived live clipper. No inspected implementation is a verified, complete production-ready replacement for the desired product.** Keep current SupoClip as the base and selectively adapt code behind its existing contracts. The authorized development fork is [primecode-khalil/supoclip](https://github.com/primecode-khalil/supoclip).

## Coverage

- SupoClip's initial forks endpoint returned **728 records**. Following every reported descendant-fork link added **3**, for **731 listed repositories**, **725 reachable** and **6 inaccessible**. These counts are an inventory snapshot, not a promise about private/deleted repositories or future changes.
- Enumerated **11,331 advertised branch references**, including non-default branches, representing **616 distinct head commits**. **354** heads were already reachable from upstream branches/history. All **262** other heads were submitted for comparison: **257** comparable and **5** with unrelated histories. Upstream reachability does not imply a commit was merged into current main; squash merges were checked for relevant candidates.
- GitHub compare truncates file lists at 300. All **10** capped comparisons and **5** unrelated-history outliers received full-tree follow-up: **26,265 tree entries** across those heads. Product source/configuration was screened and matching implementation paths read; bundled virtual environments/framework files were excluded from feature claims.
- py-autovod's endpoint returned **19** records, **18 reachable**; all **47 branch references / 35 distinct heads** were examined. Descendant endpoints were also checked. Relevant-looking queue/rclone/metadata/ASR improvements mostly already exist in upstream main.
- Additional GitHub repository/PR/code searches located **detached derivatives outside the fork network**. This matters: the strongest live-capture result is not marked as a GitHub fork.

This is exhaustive public metadata/advertised-branch screening plus targeted source review, **not execution or line-by-line review of every fork and historical commit**. Tags, unadvertised refs, private/deleted code and unindexed detached projects remain outside the established coverage. GPU performance, live continuity, media quality and public publishing were not benchmarked in fork research.

## Recommended candidates

| Candidate and exact implementation | What is real | Reuse decision |
|---|---|---|
| [OPPAILUVR/supoclip](https://github.com/OPPAILUVR/supoclip/tree/0092933e43ca48c31b60cce3e02eec1575613d33), `main` | Channel monitoring, FFmpeg nominal 60-second rolling segments, watch-list UI/API and automatic live clipping | Closest match to the live feature. Mine recorder/watch-list concepts; do not adopt the whole fork. |
| [Obiorachibuike/supoclip](https://github.com/Obiorachibuike/supoclip/tree/49ddba2ee829f4b5960484ee98c67ffbea1411cf), `main` | Separate faster-whisper engine with CPU/CUDA selection, word timing, model cache and load fallback | Strongest inspected modular transcription donor. Fix lockfile/runtime gaps during a narrow port. |
| [FloMotion33/supoclip](https://github.com/FloMotion33/supoclip/tree/778dc43ac09bba40fb1fc97f4fa0ab234f820782), `feat/faster-whisper-transcription` | Small CPU-int8 faster-whisper adapter and separate sentence-end caption grouping | Smallest transcription/caption donor; feature is absent from its default branch. Not GPU inference. |
| [Sh8ders/claudeclip](https://github.com/Sh8ders/claudeclip/tree/6dcef5e2f58e1233c08d1e035f4f3ea189f3d1f1), `claude-native` | Word-timed faster-whisper/MLX alternatives and native CLI | Useful native Apple Silicon provider; preserve web architecture instead of adopting the whole CLI rewrite. |
| [Zeidev/supoclip](https://github.com/Zeidev/supoclip/tree/9a3aabb7efcacaedded0e5c2f5e4253c777e3301), `feat/custom-openai-compatible-llm` | Generic LLM gateway, optional NVIDIA worker setup and SRT input | Split reusable gateway/runtime configuration from storage and subtitle-timing limitations. |
| [stale2000/supoclip](https://github.com/stale2000/supoclip/tree/6405d91ef562fec6daf5f6c9f55d07d47dd1ae8e), `Bryan-dev-whisper` | Faster-whisper plus actual NVENC encoding selection | Older architecture; adapt codec/runtime policy rather than merge the monolith. |

A recursively discovered descendant, [Metalbenji/supoclip](https://github.com/Metalbenji/supoclip/tree/c9fa30c6ab54243be6de91847099a476ba6c1d09), adds encrypted per-user BYOK/profiles, review editing and NVENC-related rendering. It is an old broad fork with authentication/default-key changes requiring adaptation, not a live controller. See [the descendant audit](descendant-fork-findings.md).

Further source-verified references include tsfarizi's Qwen3-ASR/forced-alignment service, cspenn's detached Parakeet/VLM rewrite, RyanSquad's ElevenLabs adapter, and Aspirewastaken's older scheduler/backup/hardware-encoding code. They are optional donors, not mandatory dependencies or production endorsements.

## Why not switch to the live-clipping fork?

OPPA is the most useful discovery. At `0092933`, it has three derivative commits on a 11 November SupoClip base, missing **79 current upstream commits**. Its live workflow is genuine, but:

- The new clip-list endpoint omits owner filtering, exposing other users' live clip metadata.
- Session/process ownership and deduplication are volatile; dedup keys use moving-window timestamps rather than source-global intervals.
- A probe exception is treated as offline and can stop/delete buffered media.
- Buffer cleanup destroys source footage without a full-archive handoff.
- AI integration depends on hardcoded desktop paths; a separate browser/cookie publisher bypasses the existing durable OAuth queue.
- No tests specific to these added capture/service paths were found.

These are source-backed reasons to reuse selected concepts while writing the owned durable session/asset foundation natively. [Detailed live audit](supoclip-live-fork-findings.md)

## What is still missing after reuse?

- Durable recording sessions, finalized media manifests, timing/gap maps and capture recovery integrated with current SupoClip.
- Full-stream archives and dependency-aware retention alongside short clips; rclone through the same durable job model.
- Reliable overlapping windows and event deduplication tied to source identity.
- Publishing the selected finished editor export or full VOD through an explicit artifact contract.
- Facebook publishing. No implementation was verified in the inspected candidates; Facebook downloads or Instagram's Meta endpoints do not establish Facebook account publishing.
- Runtime validation of selected provider/GPU changes. A CUDA import, encoder listing or README claim does not prove inference/encoding works in the final container.

## Implementation decision

Proceed on the current SupoClip fork. First implement owned channel/session bookkeeping with database constraints and recovery-ready identities. Next build supervised capture and finalized-segment persistence, informed by OPPA's useful small pieces. Port a tested faster-whisper adapter separately, using Obiorachibuike/FloMotion33 as candidates. Preserve current editing, word-timed captions and social infrastructure.

Research does not justify replacing the product with an older detached fork. It does justify avoiding duplicate implementation of separable adapters and reusing their tests/ideas with provenance and license notices.

## Evidence files

- [Live capture and detached derivatives](supoclip-live-fork-findings.md)
- [Provider/GPU/caption candidates](supoclip-provider-fork-findings.md)
- [Complete py-autovod fork review](py-autovod-fork-findings.md)
- [Capped/unrelated-history follow-up](fork-outlier-findings.md)
- [Descendant forks](descendant-fork-findings.md)
- [Coverage summary](coverage-summary.json)

The research workspace also retains raw paginated fork lists, complete branch snapshots, compare results and scripts for reproducibility. The development fork keeps compact reports rather than committing cloned repositories or large raw API dumps.
