#!/bin/sh
# First installation/resume only. Completed installations receive health checks.
set -eu
vps_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 "$vps_dir/preflight.py"
docker info >/dev/null
exec python3 "$vps_dir/bootstrap.py"
