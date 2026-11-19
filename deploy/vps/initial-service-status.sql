-- Initialize the private installation's operator-maintained status.
-- Only replace the historical upstream seed before an owner has registered.
-- Never overwrite an existing owner's incident or a customized status.
UPDATE service_statuses
SET status = 'operational',
    headline = 'No incident reported',
    description = 'Status is maintained by this installation''s operator. This is not an automatic YouTube connectivity check.',
    updated_at = CURRENT_TIMESTAMP
WHERE id = 'video-downloads'
  AND status = 'degraded'
  AND headline = 'Investigating'
  AND description = 'We are investigating slow video downloads. Importing videos from YouTube may take longer than usual or fail with a timeout. Please avoid repeatedly retrying the same video while we investigate. We will update this page when we have more information.'
  AND NOT EXISTS (SELECT 1 FROM users);
