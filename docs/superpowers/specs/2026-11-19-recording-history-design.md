# Recording history cleanup

The owner requested clearing failed windows while keeping captured recordings, controls to clear all history, and automatic removal of the attached history entry when its library generation is deleted.

Use durable soft clearing in each recording window's existing JSON metadata. Hard deletion would let capture recovery rediscover the source and replay deleted jobs. Keep immutable identities, source references, and upload/publication receipts. Cleared entries disappear from lists/counts, pending selection, and the capture backlog. Worker writes and retries cannot reopen cleared entries. Captured originals are untouched by clearing; normal recording retention and disk limits still apply.

Add owner-scoped `DELETE /recording/channels/{id}/windows?scope=failed|finished`. `failed` clears blocked windows; `finished` clears blocked and completed windows. Running/uploading/publishing work continues. Return the number cleared; repeats succeed with zero. Library task deletion marks attached windows cleared in the same transaction before the foreign key removes the binding, stopping their automation without changing other channels or external posts. Store owner/source-validated window provenance in the initial task metadata so deletion also works if a recorder crashes before saving the task binding. Reject task requests for an already-cleared window.

The dashboard offers **Clear failed** and **Clear all finished**, each with a confirmation that recordings/library clips/posts are kept and active work continues. Report request errors and refresh after success. Existing retry remains available for uncleared failed windows.

Verify PostgreSQL ownership, idempotency, transaction rollback, recovery replay, stale worker protection, backlog exclusion and retained originals. Test confirmation/cancellation/error behavior and signed DELETE proxying. Deploy backed up/drained, retain lockfiles/base images and scan final images. Use the failed-only action on Speed after deployment.
