# YouTube publishing release verification — 2026-11-19

Runtime source: `10ddfb0`; baseline: `35c383c`. Review: [PR #2](https://github.com/primecode-khalil/supoclip/pull/2).

## Verified behavior

Watch finished vertical clips sequentially, approve/reject/undo, and reserve native
YouTube publication slots every six hours or with an interval/weekly pattern.
Private resumable upload, processing proof and verified native schedules use a
single durable video ID. A source deletion dialog lists affected uploads and
requires acknowledgement. It removes the selected pending/private YouTube copies,
including a selected copy that publishes while the dialog/removal is in progress.
Remote absence must be verified; connection failures retain a recoverable receipt.
Editing/regenerating preserves the reviewed bytes and approval. Already-published
history outside the deletion selection remains on YouTube.

## Evidence

- All YouTube/social backend integration and unit files: **522 passed**.
- Full frontend suite on Node 22: **1,051 passed**, 144 files.
- Frontend lint/TypeScript: `make check` passed.
- Real browser with playable MP4: **4 passed**, desktop 1440px and mobile 320px,
  covering review/approve/reject/undo, pattern/cancellation and acknowledged source deletion.
- Whole-branch fresh review found three critical and five important findings;
  regression tests reproduced and fixed them. No deferred minor findings.
- Additional task/clip service compatibility tests: **98 passed**.
- Fresh backend, frontend, PostgreSQL and MCP images: Trivy 0.76.1 critical scan
  passed for all four, using `--severity CRITICAL --ignore-unfixed --exit-code 1`.
  Committed locks and patched base-image pins are preserved. All 17 frontend
  filesystem layers were verified unchanged after transfer from the Mac build
  to the VPS.
- Additive schema migration and replay, then previous-app startup against the
  upgraded disposable database: passed database and Redis health checks.
- Full Linux backend: **3,749 passed, 2 skipped** in 2,206.60 seconds. The
  configured auth/billing coverage gate passed at 92.54% (not whole-app coverage).
  The clean run followed an intentionally stopped overloaded attempt; no failing
  test was excluded.
- VPS rollout passed the drain and database/config backup gates; previous source
  and image receipts are retained. All nine services and `health.sh` passed.
  Automation policies were preserved. The recorder was gracefully restarted.
- Public `/publishing` and `/changelog`: HTTP 200. Fresh Chrome smoke verified
  the signed-out Publishing guard and live release entry, without page errors.
  Authenticated owner flows were verified in the four demo browser workflows;
  the user browser host was unavailable for an authenticated live inspection.

[Desktop screenshot](https://raw.githubusercontent.com/primecode-khalil/supoclip/pr-assets/feat/youtube-autopublishing/review-desktop.png),
[mobile deletion warning](https://raw.githubusercontent.com/primecode-khalil/supoclip/pr-assets/feat/youtube-autopublishing/deletion-warning-mobile.png),
[workflow GIF](https://raw.githubusercontent.com/primecode-khalil/supoclip/pr-assets/feat/youtube-autopublishing/review-workflow.gif),
[original video](https://raw.githubusercontent.com/primecode-khalil/supoclip/pr-assets/feat/youtube-autopublishing/review-workflow.webm).
All captures use demo data.

## External setup gate

No real account has been connected and no chargeable upload or public schedule
has been created by this release verification. Google OAuth configuration,
channel consent and the first explicit approval are owner actions. Real Google
processing, public scheduling and A/V playback remain unverified until then.

## Rulings I made

All execution decisions in their recorded order, with their costs and limits.
The owner’s review-first steering superseded the earlier direct-auto-post proposal
before the decision/scheduling flow was implemented.

1. Ruling: Implement natively with one final fresh reviewer as executing-plans requires — user approved implementation without requesting implementer delegation — review misses cost regressions, so independent final review is retained.

2. Ruling: Backport runtime/database/editor fixes only from the pinned d2378a9 AGPL snapshot; do not import hosted serving scripts, billing/marketing or post-license code — preserves authorized self-host architecture — omitted upstream features remain unavailable.

3. Baseline: social provider/runtime tests: 41 passed; focused command exited 1 because global coverage threshold applies to the selected subset. Ruling: use --no-cov for focused regressions and retain coverage/full-suite validation later — avoids treating unrelated coverage percentage as functional failure.

4. Maintenance Ruling: New interactive keyed tasks use upstream 24-hour request retention; retain lifetime replay for recording-window requests and existing legacy durable flags — avoids weakening long recording recovery while honoring expiry for new interactive requests — wrong classification could recreate or over-deduplicate work; covered by expiry, recording and history regressions.

5. Task 3 Ruling: Reuse existing dispatch_scheduled_social_posts/resolve_pending_posts cron instead of creating another cron job — current pipeline already provides the needed cadence — a cron outage still delays reconciliation; integration tests cover accepted IDs remaining eligible for polling.

6. Task 3 Ruling: Finalize the private checkpoint, post publication and private-test receipt in one database transaction instead of calling the generic committing _mark_published helper — removes a crash gap between ready and published — custom finalization must preserve public fields/analytics; lifecycle tests cover them.

7. Task 3 Ruling: Do not restart legacy unmarked publishing rows with no checkpoint — their old upload outcome cannot be recovered — they may require owner review instead of automatic progress.

8. Task 4 Ruling: Approval atomically commits review status, immutable render proof, native-intent post and account-locked slot; add a transactional option to the existing social service/repository instead of tolerating multi-commit approval gaps — avoids duplicate/half-approved jobs — callers must defer enqueue until commit.

9. Task 4 Ruling: New review-mode windows hand off to Social and complete without waiting for publication; legacy source rules remain until adoption — prevents a publishing backlog pausing capture — later publication errors are managed in Social rather than reopening recording windows.

10. Task 4 Ruling: Freeze approved file references and keep pending review/approved snapshot media in the cleanup reference index — editing the library must not replace the approved bytes — rejected files follow normal library retention.

11. Task 4 Ruling: An explicitly approved first clip can provide the private processing proof before its approved future public schedule is set; unattended mode still requires prior private proof — keeps setup smooth without implicit public posting — live proof remains untested until owner consent/approval.

12. Task 5 Ruling: Network recovery uses the existing cron queue with minute-bucket job IDs, while legacy non-native polling remains compatible — finished ARQ result retention must not block future checks — a cron outage delays app status updates, while confirmed native schedules remain on Google.

13. Task 5 Ruling: Respect a future publication time edited directly in YouTube Studio and synchronize the reservation; flag an overdue private schedule after a 20-minute grace period — preserves owner edits without claiming publication — manually conflicting Studio times require attention.

14. Task 5 Ruling: Shared quota waits use a conservative one-hour delay per hashed Google project and API bucket — avoids guessing daily reset times and retry storms — a quota reset can precede the next retry by up to one hour.

15. Task 6 Ruling: Use a dedicated Publishing navigation destination and retain social account management in Settings — avoids mixing review decisions with OAuth setup — existing social bookmarks continue to work.

16. Task 6 Ruling: Interval anchors use clearly labelled device-local input; weekly times use the selected IANA timezone — browser-native datetime controls have no timezone support — owners using a different device timezone must read the anchor label; upcoming publication time is shown in destination timezone.

17. Final Ruling: Real Google consent/upload remains an owner gate; differently licensed upstream remains excluded; baseline full-suite attribution is executor-owned — these are the reviewer's only declined behaviors — external behavior remains unproven until an approved real clip.

18. Final Ruling: Initial root schema runs once; replay the additive publishing migrations instead of rerunning unrelated non-idempotent base bootstrap — matches installer/Postgres lifecycle — future bootstrap re-entry needs its own migration strategy.

19. Final Ruling: Correct pre-existing test fixtures to advance the clock past update triggers and name required Stripe columns explicitly — full-suite RED exposed invalid fixture assumptions, not a publishing runtime change — incorrect fixture timing could otherwise hide stale-job regressions.

20. Task 8 Ruling: A lost final upload with all bytes accepted but no ID remains Needs attention instead of claiming removal — cannot prove remote absence — owner may need Studio/retry, but no duplicate upload is started.

21. Task 8 Ruling: Deleting a source also removes its already-cancelled private YouTube copy; individually disconnecting a channel only withdraws its schedule, while whole-account deletion removes pending/private copies — makes source-of-truth deletion match the owner's instruction — permanent external deletion cannot be undone after explicit confirmation.

22. Task 8 follow-up Ruling: Send the exact warned upload IDs with source deletion, reject newly linked uploads until the warning is refreshed, and retain that selection even if it becomes public before confirmation — makes the warning describe the actual destructive action — a disconnected Google account still requires reconnection to finish removal.

23. Task 8 follow-up Ruling: Internal editing/regeneration retains frozen approved renders and records source replacement; explicit library deletion removes linked copies — honors approval of the reviewed bytes while distinguishing editing from deleting — approved old renders consume storage until publication or cancellation. Failed approvals retain their render for retry.

24. Task 8 follow-up Ruling: Keep cancelled private-copy receipts and include revoked channels in whole-account deletion — prevents losing the only external video ID — account deletion can remain pending until the owner reconnects.

25. Task 7 Ruling: The recording runner also contains the review handoff, so keeping the old recorder would omit live review intake. Drain finite tasks and ARQ jobs, then gracefully restart the live recorder with retained chunks; active_recordings=0 was an executor-added gate, not AGENTS.md — preserves required new behavior without interrupting active clip processing — live capture can have a brief restart gap. User was informed before rollout; no automation policy is changed.

26. Task 7 Ruling: ARQ finish_job deliberately retains cron in-progress locks after completion; observed five retained markers with fresh j_ongoing=0 health records and empty render queues. Drain on fresh worker j_ongoing, empty user-work queues and zero pending/queued/processing tasks instead of requiring retained cron locks to vanish — avoids a false deployment deadlock without deleting Redis state — any job starting in the check/stop interval relies on the configured graceful stop.

## Deferred minors

None.
