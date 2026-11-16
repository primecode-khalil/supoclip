#!/bin/sh
# Full media snapshots require stopped writers, as explained in docs/vps-autonomy.md.
set -eu
umask 077
vps_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
destination=${1:?Usage: snapshot.sh /absolute/new-empty-backup-directory}
case "$destination" in /*) ;; *) echo 'Use an absolute backup directory.' >&2; exit 1 ;; esac
for service in recorder frontend backend worker cron-worker ai-worker; do
  if [ -n "$("$vps_dir/compose.sh" ps --status running --quiet "$service")" ]; then
    echo "Stop $service after draining its work before taking a media snapshot." >&2
    exit 1
  fi
done
mkdir "$destination"
chmod 700 "$destination"
"$vps_dir/compose.sh" run --rm --no-deps --volume "$destination:/snapshot" snapshot
"$vps_dir/compose.sh" exec -T postgres pg_dump -U supoclip -d supoclip --format=custom > "$destination/postgres.dump"
"$vps_dir/compose.sh" exec -T postgres pg_restore --list < "$destination/postgres.dump" > /dev/null
cp "$vps_dir/.env" "$destination/deployment.env"
cp "$vps_dir/rclone.conf" "$destination/rclone.conf"
git -C "$vps_dir/../.." rev-parse HEAD > "$destination/revision.txt"
printf '%s\n' "Quiesced backup completed: $destination"
