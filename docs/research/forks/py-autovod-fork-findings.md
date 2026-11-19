# py-autovod public fork audit

Audited 2026-11-16 against upstream `0jc1/py-autovod` main **`424f49815aba773c85cc8a7851ac52c6554dfa96`**. Static inspection only: fetched Git objects and read source/diffs; did not install dependencies, execute fork code, record streams, or upload media.

**No inspected fork already provides an integrated SupoClip live-clipping product. Keep current upstream as the reference for reusable py-autovod behavior.** The apparently promising upload queue, rclone support, shorts generation, metadata polling, and multilingual Whisper changes have already reached upstream. The remaining alternate capture/status implementations are incomplete and do not produce finalized rolling video windows. This is a conclusion from the branch/source coverage below, not an operational test result.

## Coverage and reproducibility

The paginated [upstream forks API](https://api.github.com/repos/0jc1/py-autovod/forks?per_page=100) returned **19 rows**, while [upstream repository metadata](https://api.github.com/repos/0jc1/py-autovod) reported `forks_count = network_count = 18`. **18 repositories were reachable; `carycooper777/py-autovod` returned HTTP 404** for both branches and descendant-fork enumeration. A 404 does not establish whether it was deleted, made private, or otherwise unavailable. Every reachable fork's own `/forks` endpoint returned an empty array, so no reachable second-generation fork remained to inspect.

For every reachable repository, enumerated every advertised branch with paginated REST requests, fetched all branch heads into an isolated bare Git repository, compared each head against its merge base with upstream main, and checked history against all three upstream branch heads. Coverage: **47 fork branch heads, 35 distinct commit SHAs, 18 branch heads with commits absent from upstream history, across 14 forks**. Different commit hashes often reflect squash merges rather than new functionality; source comparison and upstream merge commits were used to distinguish them. The four remaining reachable forks contain only commits already in upstream history. Upstream's shared `streamlink-api` and Cursor environment branches were also inspected.

The exact inventory and comparisons are saved in `py-autovod-forks.json`, `py-autovod-branches.json`, `py-autovod-descendant-forks.json`, and `py-autovod-head-comparisons.json`. `py-autovod-fork-candidates.json` gives per-branch decisions, pinned evidence, upstream equivalents, and limitations. Scope is the public fork network and advertised branch heads available at audit time; inaccessible/private forks, unadvertised refs, and detached copies outside that network are not established by this audit.

## Findings that matter for reuse

| Fork and branch | Actual implementation | Decision |
| --- | --- | --- |
| [VedantMadane — `feat/background-upload-queue`](https://github.com/VedantMadane/py-autovod/tree/1a916d9d2f2c6da2f6b27a2196d2c69cf201e63a) | Threaded upload worker, retry/backoff, JSON pending list, rclone copy, cleanup options. `src/uploader.py`, `src/processor.py`, and `src/stream_manager.py` are byte-identical to current upstream main. | **Already merged** as [upstream #226](https://github.com/0jc1/py-autovod/commit/f985cfa). No fork-only queue improvement. |
| [HarshRajSinghania — `fix/fetch-metadata-polling`](https://github.com/HarshRajSinghania/py-autovod/tree/894e6455605db14f0fbf41de9157a7ac4eb5e2f5) | Replaces the fixed 22-second delay with metadata polling. The branch's **entire Git tree equals current upstream main** despite different history. | **Already merged** as [upstream #236](https://github.com/0jc1/py-autovod/commit/424f49815aba773c85cc8a7851ac52c6554dfa96). |
| [squonk4303 — `faster-live-stream-check`](https://github.com/squonk4303/py-autovod/tree/819faea539cec219d2dc02e6c2ca178ca5fe6f1b) | Adds Twitch Helix status checks and a YouTube HTML canonical-link heuristic. | **Idea only; substantial repair needed.** No timing benchmark or rolling ingest. [Source](https://github.com/squonk4303/py-autovod/blob/819faea539cec219d2dc02e6c2ca178ca5fe6f1b/src/utils.py#L71-L144) always classifies non-YouTube URLs as Twitch, returns false when Twitch credentials are missing rather than using its advertised Streamlink fallback, prepends `https://` unconditionally, and makes requests without timeouts. It imports BeautifulSoup but [does not declare its package](https://github.com/squonk4303/py-autovod/blob/819faea539cec219d2dc02e6c2ca178ca5fe6f1b/pyproject.toml#L13-L29). |
| [jamestwilkinson — `feature/rclone-upload`](https://github.com/jamestwilkinson/py-autovod/tree/051057932e504200ba12be52b4d87885bd9a0c66) | Alternate rclone `copyto`/`moveto` upload and FFmpeg changes. | **Do not adopt as a base.** [Processor imports `uploader_commands.upload_with_rclone`](https://github.com/jamestwilkinson/py-autovod/blob/051057932e504200ba12be52b4d87885bd9a0c66/src/processor.py#L1-L8), but [that module is absent](https://github.com/jamestwilkinson/py-autovod/tree/051057932e504200ba12be52b4d87885bd9a0c66/src); the implemented function is instead [`uploader.upload_rclone`](https://github.com/jamestwilkinson/py-autovod/blob/051057932e504200ba12be52b4d87885bd9a0c66/src/uploader.py#L41-L84). Current upstream already has rclone through the background worker. |
| [squonk4303 — `issue-195`](https://github.com/squonk4303/py-autovod/tree/b5ff5c37c2f3137b17e5cc8f43abaa524e50f1ef) | Extracts Streamlink command construction and adds quality fallback tests/documentation. | **Broken capture call.** [`download_video()` passes undefined `stream_url` and two arguments to a helper accepting one](https://github.com/squonk4303/py-autovod/blob/b5ff5c37c2f3137b17e5cc8f43abaa524e50f1ef/src/stream_monitor.py#L81-L125). Quality strings were already passed straight to Streamlink; this does not add adaptive quality recovery. |
| [binggao1230 — `fix-217-shorts-per-clip`](https://github.com/binggao1230/py-autovod/commit/607c37c13fbd5ac2ef4f5c7f9f9b4030cbf59dea) | Generates optional 9:16 versions for selected extracted clips, using scaled video with black padding. | **Already merged** as [upstream #222](https://github.com/0jc1/py-autovod/commit/bd01fc8). No subject tracking, caption editor, or SupoClip integration added by this branch. |
| [VedantMadane — `feat/whisper-multi-language`](https://github.com/VedantMadane/py-autovod/commit/913be515a2a9547f6f9fd6ba956d131391f1fc43) | Passes one configurable language into Whisper and faster-whisper. | **Already merged** as [upstream #141](https://github.com/0jc1/py-autovod/commit/bc39a63). This is language selection, not simultaneous multilingual diarization. |
| [Deepak8858 — `fix/issue-143-downsample-audio`](https://github.com/Deepak8858/py-autovod/commit/bca9c0d1431406619a0df31c90ac062f8d7fced6) and [atharva-matale — `jarvis-fix-1775369485`](https://github.com/atharva-matale/py-autovod/commit/c6c82d0facd1addcb72588b5d840eb308591b3ac) | Downsamples feature-analysis audio to 8 kHz; broadens original Whisper's CUDA FP16 check. | **Already merged** as [#144](https://github.com/0jc1/py-autovod/commit/76ff45b) and [#146](https://github.com/0jc1/py-autovod/commit/7949902). Current upstream additionally has [batched faster-whisper transcription #228](https://github.com/0jc1/py-autovod/commit/b506f8e). |

The inherited upload worker is useful but is **not a transactional durable processing queue**: it removes an item from the in-memory queue before work, while persistence snapshots only the remaining queue. A concurrent save or shutdown can omit the in-flight item. This limitation is identical in the Vedant branch and upstream; there is no fork fix to import. Processing jobs themselves still use an in-memory queue. [Upload handling and persistence](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/uploader.py#L215-L329), [processor](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/processor.py#L22-L101).

The shared, unmerged upstream [`streamlink-api` branch](https://github.com/0jc1/py-autovod/blob/0f320f8914ce4c782126e9b8836183f94b405b75/src/stream_monitor.py#L69-L129) reads 8 KiB byte blocks into one growing recording. Its variable `chunk_size` denotes I/O bytes, not independently playable media segments. It calls the processor only after `download_video()` returns, [at lines 180–193](https://github.com/0jc1/py-autovod/blob/0f320f8914ce4c782126e9b8836183f94b405b75/src/stream_monitor.py#L180-L193). It therefore does not solve low-latency finalized chunks or event windows. The Cursor branch only adds development-environment files. [Cursor commit](https://github.com/0jc1/py-autovod/commit/c0762b6f87ba36fda156ad7bb72b13e201eaca0d).

## Complete repository disposition

Branch counts include inherited branches. Every branch SHA is retained in the machine-readable coverage file.

| Reachable fork | Branches | Distinct contribution disposition |
| --- | ---: | --- |
| HarshRajSinghania/py-autovod | 4 | Metadata polling already merged; branch tree equals upstream main. |
| floze-the-genius/py-autovod | 3 | Core module tests already merged as [#225](https://github.com/0jc1/py-autovod/commit/c40aa7a). |
| webbrain-one/py-autovod | 3 | Chinese README already merged as [#224](https://github.com/0jc1/py-autovod/commit/0cf979f). |
| binggao1230/py-autovod | 3 | Shorts-per-selected-clip already merged as #222. |
| jamestwilkinson/py-autovod | 2 | Alternate rclone branch has missing-module import; no unique live ingest. |
| senseipri/py-autovod | 2 | Logging replacement already merged as [#200](https://github.com/0jc1/py-autovod/commit/56b0354). |
| MohnishOnGitHub/py-autovod | 1 | Only workflow, tests, and quality-fallback documentation changes; no changed production Python source. CI matrix reached [#197](https://github.com/0jc1/py-autovod/commit/68cb83b); no capture feature to reuse. |
| squonk4303/py-autovod | 3 | Two unfinished status/command branches detailed above. |
| alceops/py-autovod | 3 | Lint workflow and test cleanup; Python source changes remove unnecessary `global`, wrap an expression, and add final newline. No live feature. [Branch commit](https://github.com/alceops/py-autovod/commit/943edbe566ad78f4d6ca7b371f16e2cac4db3ba8). |
| arjunrawal1/py-autovod | 4 | Encode output path and shorts FFmpeg argument fixes already incorporated as [#174](https://github.com/0jc1/py-autovod/commit/7b17a90) and [#175](https://github.com/0jc1/py-autovod/commit/16f5e3b). |
| Ajay43634/Python_syntax | 1 | Renamed fork; only upstream-history head. |
| atharva-matale/py-autovod | 3 | CUDA FP16 fix already merged as #146. |
| Deepak8858/py-autovod | 3 | Audio feature downsampling already merged as #144. |
| VedantMadane/py-autovod | 4 | Upload queue/rclone and language setting already merged as #226/#141. |
| Simon99/py-autovod | 4 | Runtime and test dependency declarations already incorporated as [#136](https://github.com/0jc1/py-autovod/commit/f6cc746) and [#135](https://github.com/0jc1/py-autovod/commit/756bec1). |
| austinsonger/py-autovod | 2 | Only upstream-history heads, including shared streamlink-api branch. |
| hacineyahia/py-autovod | 1 | Only upstream-history head. |
| frenchwhy/py-autovod | 1 | Only upstream-history head. |

**Unavailable:** carycooper777/py-autovod (listed by upstream forks API; branches and forks API HTTP 404).

## Implication for the authorized implementation

No reachable fork supplied the missing adapter: supervised rolling media segments, durable session/chunk/job state, overlapping context assembly, or a SupoClip task handoff. Main still writes one output recording and waits for capture to end before enqueueing processing. [Capture and handoff](https://github.com/0jc1/py-autovod/blob/424f49815aba773c85cc8a7851ac52c6554dfa96/src/stream_monitor.py#L81-L179). The fork search does not change the earlier recommendation to build the live ingest boundary around SupoClip. Reuse current upstream ideas selectively; avoid replacing it with older fork tips whose apparent additions are already upstream. Real-stream reliability, latency, and output quality remain unmeasured in this static audit.
