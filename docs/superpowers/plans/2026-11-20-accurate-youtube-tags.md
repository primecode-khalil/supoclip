# Accurate YouTube tags

The owner wants useful, accurate tags from the existing Gemini response, without
keyword stuffing. The configured model remains interchangeable; no additional
model request is needed for a newly generated clip.

- Add `youtube_tags` to highlight segments and existing workflow copy/draft
  responses. Aim for 3–6 specific terms, allow fewer or none, cap at eight.
- Only retain generated terms grounded in the final clip transcript. Never guess
  a person, game, place or topic from the rest of the source. Drop generic
  promotional filler. Preserve language and meaningful multiword terms.
- Normalize, deduplicate and enforce YouTube's 500-character aggregate budget.
  Keep tags separate from description hashtags; add no automatic generic tags.
- Preserve candidates in clip `workflow_meta`, without a database migration.
  Check against the rendered clip text again after cut/trim decisions.
- Show editable tags in Publishing review. An explicit empty list clears them;
  omitted approval tags use the clip suggestions. Freeze approved tags in the
  post's existing `provider_options`, then in its resumable upload metadata.
- Existing uploads/schedules remain unchanged. Older clips without suggestions
  can be tagged manually; no automatic paid backfill.

Implementation slices:

1. Test and implement normalization, grounding and AI-to-clip persistence.
2. Test approval/default/clear behavior, actual provider payloads and review UI.
3. Run affected regressions, lint/types and browser workflows; document limits,
   capture demo UI evidence, scan final images and roll out after finite jobs
   drain. Preserve the recorder's settings and existing upload receipts.

Sources: [YouTube tag guidance](https://support.google.com/youtube/answer/146402),
[video metadata limits](https://developers.google.com/youtube/data/reference/rest/v3/videos).
Tags supplement discovery; YouTube says the title, thumbnail and description are
more important. This change makes no promise of increased views.
