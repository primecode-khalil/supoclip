#!/bin/sh
# Read-only health checks; this script never restarts services or prints env vars.
set -eu
vps_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$vps_dir/compose.sh" exec -T backend .venv/bin/python - <<'PY'
import json
from urllib.request import urlopen
for endpoint in ("health/db", "health/redis", "health/worker"):
    with urlopen("http://localhost:8000/" + endpoint, timeout=15) as response:
        result = json.load(response)
    if result.get("status") != "healthy":
        raise SystemExit(f"Unhealthy: {endpoint}")
    print(f"Healthy: {endpoint}")
PY
"$vps_dir/compose.sh" exec -T frontend curl -fsS -o /dev/null http://localhost:3107/api/auth/get-session
"$vps_dir/compose.sh" exec -T cron-worker .venv/bin/arq --check src.workers.cron_worker.CronWorkerSettings
"$vps_dir/compose.sh" exec -T ai-worker .venv/bin/arq --check src.workers.ai_worker.AIWorkerSettings
"$vps_dir/compose.sh" exec -T recorder .venv/bin/python -m src.workers.recording_supervisor --healthcheck
"$vps_dir/compose.sh" exec -T caddy wget -q -O /dev/null http://127.0.0.1:2019/config/
printf '%s\n' 'Frontend, workers, proxy and recording supervisor passed their health checks.'
