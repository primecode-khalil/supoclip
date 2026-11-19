#!/bin/sh
# Safe to run online. This is a database/config backup, not a media snapshot.
set -eu
umask 077
vps_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
backup_root=${1:?Usage: backup-db.sh /absolute/private/backup-directory}
case "$backup_root" in /*) ;; *) echo 'Use an absolute backup directory.' >&2; exit 1 ;; esac
mkdir -p "$backup_root"
chmod 700 "$backup_root"
backup_name="db-$(date -u +%Y%m%dT%H%M%SZ)-$$"
partial="$backup_root/.$backup_name.partial"
mkdir "$partial"
trap 'rm -f "$partial/postgres.dump" "$partial/deployment.env" "$partial/rclone.conf" "$partial/revision.txt"; rmdir "$partial" 2>/dev/null || true' EXIT
trap 'exit 130' HUP INT TERM
"$vps_dir/compose.sh" exec -T postgres pg_dump -U supoclip -d supoclip --format=custom > "$partial/postgres.dump"
"$vps_dir/compose.sh" exec -T postgres pg_restore --list < "$partial/postgres.dump" > /dev/null
cp "$vps_dir/.env" "$partial/deployment.env"
cp "$vps_dir/rclone.conf" "$partial/rclone.conf"
git -C "$vps_dir/../.." rev-parse HEAD > "$partial/revision.txt"
mv "$partial" "$backup_root/$backup_name"
trap - EXIT HUP INT TERM
printf '%s\n' "Database/config backup completed: $backup_root/$backup_name"
# Prune only this script's dated directories, never foreign files or symlinks.
python3 - "$backup_root" <<'PY'
from pathlib import Path
import re
import shutil
import sys
import time
root = Path(sys.argv[1])
cutoff = time.time() - 14 * 86400
for path in root.iterdir():
    if not path.is_symlink() and path.is_dir() and re.fullmatch(r"db-[0-9]{8}T[0-9]{6}Z-[0-9]+", path.name) and path.stat().st_mtime < cutoff:
        shutil.rmtree(path)
PY
