#!/bin/sh
# Keep path resolution identical from the repo root, cron, and an SSH session.
set -eu
vps_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
https_mode=$(sed -n 's/^VPS_HTTPS=//p' "$vps_dir/.env" 2>/dev/null | tail -n 1)
if [ "$https_mode" = "true" ]; then
  exec docker compose --project-directory "$vps_dir" --env-file "$vps_dir/.env" -f "$vps_dir/compose.yml" -f "$vps_dir/compose.https.yml" "$@"
fi
exec docker compose --project-directory "$vps_dir" --env-file "$vps_dir/.env" -f "$vps_dir/compose.yml" "$@"
