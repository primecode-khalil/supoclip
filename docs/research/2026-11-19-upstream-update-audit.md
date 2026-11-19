# Upstream update audit — 19 November 2026

## Recommendation

Keep this fork on its existing AGPL foundation. Backport selected fixes from the
last upstream AGPL snapshot on a separate integration branch, then implement the
YouTube publishing reliability work. Do not rebase the published recording branch
onto current upstream main or deploy an untested automatic merge.

This is an audit and proposed integration sequence. No application code, branch
history, production service, automation setting, or database was changed.

## Verified Git state

| Item | Revision or count |
| --- | --- |
| Fork branch | `feat/recording-foundation` |
| Fork/deployed baseline | `35c383c431952e645142e7290d2eaeec52cd4357` |
| Fetched upstream main | `09690e0d07955ba4917c5e6cb88e5a838d776288` |
| Common ancestor | `e42e93b02873d29e2000a6a8235c10e23f8c99c9` |
| Fork-only / upstream-only commits | 17 / 78, including merge commits |
| Paths changed on upstream since the ancestor | 285 |
| Paths changed by both sides | 14 |
| Last snapshot before the license replacement | `d2378a91030e5197b8ccb9edffc2823901319a7a` |
| Upstream-only commits through that snapshot | 70 |

Counts describe the fetched revisions, not a permanent state or 78 independent
features. The working tree was clean at the start of the audit.

## License boundary

Upstream commit [`dc856b5`](https://github.com/FujiwaraChoki/supoclip/commit/dc856b5)
replaced AGPL on November 18 with the SupoClip Noncommercial Source License.
Its [published terms](https://github.com/FujiwaraChoki/supoclip/blob/09690e0d07955ba4917c5e6cb88e5a838d776288/LICENSE)
require prior written permission for commercial use, explicitly including
producing clips for monetized channels and internal business use. Section 1 says
rights already granted under earlier licenses remain intact.

The parent `d2378a9` still contains AGPL-3.0 in `LICENSE`. Use that exact historical
snapshot when sourcing the proposed backports, retain attribution and provenance,
and continue meeting the existing license obligations. Merely skipping the license
commit while copying subsequent code is not a sound licensing strategy. Adoption
of current upstream code for a commercial workflow needs a separate permissions
decision. No permission request was sent to upstream.

## Trial integration results

`git merge-tree --write-tree HEAD upstream/main` computed a candidate tree without
checking it out or moving a branch. It reported conflicts in:

- `CHANGELOG.md`
- `backend/Dockerfile`
- `backend/src/api/routes/tasks.py`
- `backend/src/repositories/task_repository.py`
- `backend/src/services/task_service.py`

The same trial against `d2378a9` reported the same conflicts except the Dockerfile.
These are merge conflict counts, not a prediction of the number of repeated
conflicts a 17-commit rebase would encounter, and not proof of runtime compatibility.

The critical semantic conflict is task creation: upstream adds transactional
idempotency while this fork writes recording provenance and storage metadata at
creation. Both must survive, including concurrent requests, task deletion, and
cleared-window tombstones. Choosing either whole side would lose behavior.

Other clean textual merges still need review: database migrations and pool
budgets, the private home-connection proxy, Docker browser dependencies, task
cancellation, and the VPS installer. Upstream's cloud serving/autoscaling layout
does not automatically replace this fork's single-machine Compose deployment.

## Backport candidates

| Priority | Historical commits / paths | Benefit and required adaptation |
| --- | --- | --- |
| 1 | `b375695`, `39fe352` | Durable task request keys and safe upload-completion retries. Merge with initial recording metadata; keep deleted-task keys from recreating deleted work. Includes additive SQL/Prisma changes and concurrency tests. |
| 1 | `c714ff1`, `02851b5`, `270913f` | Bound database pools and release idle connections. Port runtime configuration and tests; calculate the combined budget for this fork's API, recorder and workers. Do not copy deployment scripts that depend on upstream serving slots. |
| 1 | `2232b76`, `60b3477`, `208077a`, `3fb35e7` | Avoid export/edit races and holding database connections during storage I/O; stop accumulating editor polls. Bring the dependent fixes and race tests together. |
| 2 | `f9e012d` | Checkpoint long YouTube section downloads, reuse completed ranges, and extend moving-transfer deadlines within the total budget. Verify with the fork's home proxy. This does not itself resolve bot challenges. |
| 2 | `4cf87a7`, `d24b6d0` | Handle interrupted preview playback and reduced-motion hydration. Small, focused browser fixes with tests. |
| Optional | `412c990` | Structured output for the named Anthropic model; useful if that provider is selected. |

Exclude the hosted billing/marketing changes, feedback integrations and cloud
autoscaler from the initial backport. They are separate features, not prerequisites
for YouTube posting. The newest upload-probing fix `09690e0` is after the license
boundary and is not part of this AGPL backport proposal.

## Integration and validation sequence

1. Preserve `35c383c` as a rollback point and create an integration branch from it.
2. Import the selected historical fixes in coherent batches with original commit
   references. Resolve task creation by retaining both metadata and idempotency.
3. Rehearse additive migrations against a disposable copy; account for both
   backend migrations and the frontend Prisma schema/init SQL.
4. Run upstream regression tests for each imported batch, plus this fork's
   recording, proxy, A/V timestamp, deletion/history and publication-limit tests.
   Exercise concurrent task creation and deletion while a window is submitting.
5. Run frontend checks and targeted browser workflows. Build the final production
   images with committed locks/base pins and pass critical image scans.
6. Review the combined diff, release notes and deployment impact. Before a later
   production restart, drain active application and ARQ work as required by
   `AGENTS.md`; retain source/image rollback points and verify the live changelog.

A selective backport will not make GitHub's behind counter zero. Track imported
commit IDs explicitly instead of treating that counter as a reliability score.

## Effect on the YouTube plan

No upstream changes were found in the core social provider, social service,
social repository, social routes, social client types, or scheduled-posts component
between the common ancestor and the fetched main. The account page only gains a
tour attribute. Existing gaps remain: upload sessions are not durable, and an
accepted YouTube upload is marked published before processing is checked.

See the [YouTube design](../superpowers/specs/2026-11-19-youtube-autopublishing.md)
and [implementation plan](../superpowers/plans/2026-11-19-youtube-autopublishing.md).
The upstream backport is a separate maintenance change; publisher tasks can be
built on the retained AGPL baseline without importing current main.
