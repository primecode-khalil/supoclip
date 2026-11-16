# Unattended operation on a VPS

This fork uses SupoClip's existing transcription, highlight selection, vertical reframing, captions, editor, and publishing workers. The recording supervisor adds live monitoring and finalized recording windows backed by PostgreSQL and a persistent capture volume. Automatic publishing is an explicit channel policy; no connected destinations means clips stay in the studio. The useful fork ideas and rejected failure modes are recorded in [the fork survey](research/forks/summary.md).

This is a single-host setup, not a high-availability cluster. A container restart preserves its named volumes; losing the VPS disk does not. Initial account/OAuth setup, platform approval, credential revocation, and exceptional content decisions can require an operator. TikTok's required consent flow is not suitable for an unattended private posting utility; this runtime excludes it from automatic destination selection. Facebook Page publishing is a separate missing provider. See [the platform research](research/social-publishing-research.md), researched 15 November 2026, before promising public posting on any platform.

## Services and durable state

Use the standalone [VPS Compose file](../deploy/vps/compose.yml), not the root development Compose file. The frontend uses the Dockerfile's production `runner` target. The API, video worker, cron worker, AI editor worker, and recorder use the same backend image and committed dependency lockfile. No development source directory is mounted over installed application code. The root installer chooses local HTTP or domain HTTPS automatically.

Only Caddy exposes host ports: the selected HTTP port in local mode, or 80/TCP, 443/TCP, and 443/UDP in domain HTTPS mode. PostgreSQL 15 uses the [patched privilege-helper image](../deploy/vps/postgres/README.md), built from pinned sources with a patched Go compiler. PostgreSQL and Redis have no published host ports; the API and frontend share one origin, with `/backend/*` routed to FastAPI. Redis enables AOF with one-second fsync. Caddy's certificate state is persistent. The image includes FFmpeg with caption filters, the locked Streamlink CLI, rclone and Chromium. Streamlink can launch a fresh headless Chromium profile for Kick/Twitch JavaScript challenges; no operator browser profile is mounted. The recorder container is the browser isolation boundary, and media/browser children do not inherit server credentials in their environment. Source platforms may still block headless clients or datacenter addresses; these failures remain unknown/retryable without deleting recordings. See [Streamlink browser requirements](https://streamlink.github.io/cli.html#web-browser-options).

The backend defaults to CPU wheels; a GPU is not required when transcription and the LLM use hosted providers.

| Volume | Contents | Recovery role |
| --- | --- | --- |
| `postgres_data` | Owners, policies, leases, windows, tasks, posts, encrypted OAuth credentials | Durable control plane; back up with `pg_dump` |
| `redis_data` | ARQ queues, caches, running-job bookkeeping | Persistent queue state; preserve during updates |
| `recordings` | Original segments and manifests | Durable capture input; archive off-host for disk-loss recovery |
| `uploads` | Uploads, rendered assets, editor files, and processing scratch under `TEMP_DIR` | Shared by API/workers on this host; include in a media snapshot |
| `clips` | Legacy/native clip output directory | Include in a media snapshot |
| `caddy_data`, `caddy_config` | TLS certificates and proxy state | Preserve to avoid unnecessary certificate issuance |

Volume names receive the prefix `supoclip-vps_`. Never use `docker compose down -v` for a routine update. PostgreSQL backups alone cannot restore recording or clip files.

## One-script installation and dashboard setup

On a 64-bit amd64/arm64 Linux machine, download this fork's `install.sh`, review it, and run it:

```sh
curl --fail --location https://raw.githubusercontent.com/primecode-khalil/supoclip/feat/recording-foundation/install.sh -o install-supoclip.sh
bash install-supoclip.sh
```

The installer detects `x86_64`/`aarch64` and selects native backend images; unsupported CPU architectures fail with a clear message. The committed CPU Torch lock includes a Linux ARM64 Python 3.11 wheel. The script installs missing host prerequisites on Debian/Ubuntu and Fedora/RHEL-family systems using the distro package manager and Docker's official repositories. It works on other Linux distributions when Docker Engine, Compose, Python 3, Git, and curl are already available. It never removes an existing Docker installation. Root/sudo is needed for host packages or Docker daemon access; the script reports the specific requirement instead of silently changing an existing engine. Docker's official platform matrix distinguishes supported distributions from derivatives. [Docker installation](https://docs.docker.com/engine/install/)

Run from an existing checkout, or let the script clone `primecode-khalil/supoclip` to `./supoclip`. `--ref BRANCH_TAG_OR_COMMIT` or `SUPOCLIP_REF` selects a revision; while this work is on a feature branch its default is `feat/recording-foundation`. Published releases should use a reviewed immutable tag. `--directory PATH` selects another installation directory. A second run preserves existing secrets, configuration, containers, and work instead of silently updating them. A durable `.bootstrap-complete` marker is written only after every application health check passes. If first installation fails after only some services start, rerun the same script at the same source revision: it starts missing services with `--no-recreate` and preserves running workers. Once completed, reruns only verify health and report recovery commands on failure; they never silently restart production jobs.

The default dashboard is `http://localhost:3107`. For a remote host, either forward that port over SSH or set its reachable name/address explicitly:

```sh
bash install.sh --host 192.0.2.10 --port 3107
```

HTTP is intended for localhost/private-network setup. Use HTTPS before entering provider credentials across a public network. For a public DNS name whose A/AAAA records already point to the machine:

```sh
bash install.sh --domain clips.your-domain.tld --email operator@your-domain.tld
```

This selects the HTTPS proxy override, with only ports 80/443 exposed. DNS and firewall changes remain the operator's responsibility; the installer does not require a particular VPS provider or ask for a channel list. Local mode exposes only the selected HTTP port. Docker-published ports may bypass ordinary host firewall rules; use the provider firewall or Docker-aware rules. [Docker firewall behavior](https://docs.docker.com/engine/install/ubuntu/)

The script generates owner-only `.env` and `rclone.conf` files and distinct internal database, Redis, signing, settings-encryption, session, and initial-owner secrets. It does not generate external provider credentials. Keep the internal keys for upgrades/restores; changing the settings-encryption key can make saved OAuth credentials unreadable. Never commit private files or share rendered `compose config` output.

The installer builds the production images, starts/migrates the backend, installs a **single-owner database guard before exposing the frontend**, then starts the rest of the stack. The console shows the registration URL and an initial setup token. Enter that token while creating the first owner through the web form. The server checks it, and a database lock serializes concurrent registrations, grants the first owner admin access, and permanently closes further signup. The token is server-only, never a `NEXT_PUBLIC` value. The database guard also prevents registration reopening if the owner is deleted. If initialization stops before the dashboard appears, rerun the installer; container presence alone is never reported as successful installation.

After registration, use the dashboard:

- `/admin`: configure transcription, highlight-selection LLM, and supported OAuth app credentials.
- `/settings/social`: authorize the owner's social accounts through the normal OAuth flow.
- `/recording`: add streaming channels, set caption/clipping policies, enable automation, and inspect progress.

Channels and publishing are disabled until configured. No AI/OAuth key is required merely to start the application and reach setup. The optional CLI below is for troubleshooting and scripting; normal setup stays in the web dashboard.

For capacity planning, a 6 Mbit/s stream uses approximately **2.7 GB/hour**, before temporary windows and rendered clips. Seven days of continuous originals is about 454 GB for one channel. Configure retention, archive targets, disk alerts, and provider budgets before enabling many channels. Measure real capture/transcription/render time before scaling; a GPU is optional when ASR/LLM run through hosted providers.

`--no-start` prepares and validates private configuration without building images or starting containers. `deploy/vps/preflight.py` can be rerun independently. The repository's **Image security** checks must pass for freshly built backend/frontend release images; scan PostgreSQL, Redis, and Caddy too. Do not bypass critical findings with an unreviewed override.

Caddy is pinned to **2.11.9**, verified against [the official release](https://github.com/caddyserver/caddy/releases/tag/v2.11.9). HTTPS mode provisions/renews certificates when DNS, public ports, and persistent certificate storage are available. [Caddy HTTPS requirements](https://caddyserver.com/docs/automatic-https)

## YouTube import access

An application health check does not establish that YouTube accepts the server's connection. Datacenter IPs may receive a "Sign in to confirm you're not a bot" response. This runtime reports that as `YOUTUBE_ACCESS_BLOCKED` before creating or charging a generation, rather than hiding it behind a missing-duration error.

In `/admin`, the encrypted **YouTube import proxy** setting applies to metadata and media downloads. The country field supplies an optional `{country}` placeholder; the proxy also supports `{session}`. A compatible bgutil HTTP token-provider endpoint can be configured for playback challenges. These settings require working operator-provided services; the application does not purchase or provision a proxy. A **YouTube Data API key** only supplies metadata and cannot make blocked media downloads work. Local file uploads remain available. See the official [yt-dlp FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ) and [PO token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) for provider requirements and limitations.

The status banner is maintained by this installation's operator, not a live global YouTube health feed. First-owner bootstrap replaces only the untouched upstream incident seed on an unclaimed installation. Existing owners' and customized status records are preserved.

## Existing HTTPS ingress

When another ingress already owns ports 80/443, first run the installer with `--no-start`. In the generated private `deploy/vps/.env`, set `VPS_HTTPS=false`, `VPS_EXTERNAL_HTTPS=true`, `APP_DOMAIN` to the public hostname, `APP_ORIGIN=https://YOUR_HOSTNAME`, and `API_ORIGIN=https://YOUR_HOSTNAME/backend`. Set `HTTP_BIND` to the private host interface reachable from that ingress (or loopback when the ingress runs on the host), and choose an unused `HTTP_PORT`. Route that hostname through your existing TLS ingress to this private HTTP listener, preserving the original Host header. Rerun `install.sh` to build and start the stack.

The external mode uses a dedicated Caddy configuration that forwards the HTTPS scheme to Next.js/FastAPI. Preflight rejects wildcard/public HTTP bindings, plain-HTTP origins and conflicting Caddy-managed/external HTTPS modes. The existing ingress remains responsible for certificate issuance/renewal; SupoClip does not request a duplicate certificate. Keep the binding on a trusted network and do not expose that HTTP port publicly.

## Optional channel CLI

The privileged setup CLI runs **inside the backend container**. It looks up an existing registered owner and uses the server signing key without printing it or putting it in command-line arguments. It does not create users or grant admin access. Anyone allowed to run it already has VPS/container administrator access.

```sh
./deploy/vps/compose.sh exec -T backend .venv/bin/python /opt/supoclip-operator.py \
  --email owner@your-domain.tld POST /recording/channels <<'JSON'
{"platform":"twitch","handle":"your_channel","name":"My stream","enabled":true,"quality":"720p,best"}
JSON
```

Save the returned channel ID. Kick and YouTube use their platform value and bare handle. The API accepts a platform identity, not arbitrary network addresses, shell flags, output paths, or capture credentials. Start with clipping only:

```sh
./deploy/vps/compose.sh exec -T backend .venv/bin/python /opt/supoclip-operator.py \
  --email owner@your-domain.tld PUT /recording/channels/CHANNEL_ID/automation <<'JSON'
{
  "enabled": true,
  "segment_seconds": 600,
  "overlap_seconds": 60,
  "processing_mode": "balanced",
  "caption_template": "default",
  "clip_length": "auto",
  "min_score": 75.0,
  "max_clips_per_window": 3,
  "max_posts_per_day": 10,
  "social_account_ids": [],
  "publish_privacy": "private",
  "archive": false,
  "retain_days": 7
}
JSON
```

The policy is a complete replacement; dashboard edits provide this configuration automatically. If using the CLI, keep its JSON in a private operator directory. To pause, send that policy with `enabled:false`. Pausing stops new capture and automation submissions. Use the native generation and Social controls for renders/posts that were already queued. Both channel `enabled` and automation `enabled` must allow capture. Read status and windows:

```sh
./deploy/vps/compose.sh exec -T backend .venv/bin/python /opt/supoclip-operator.py \
  --email owner@your-domain.tld GET /recording/channels/CHANNEL_ID/automation
./deploy/vps/compose.sh exec -T backend .venv/bin/python /opt/supoclip-operator.py \
  --email owner@your-domain.tld GET '/recording/channels/CHANNEL_ID/windows?limit=20'
```

A healthy supervisor with an offline channel is normal. An expired lease, growing backlog, repeatedly blocked windows, or an old heartbeat requires investigation. Inspect generated clips in the studio before selecting publishing accounts. A score filter does not guarantee editorial quality.

## Connect and enable publishing

Register the OAuth apps and privately configure their credentials. The callback addresses are **frontend** routes:

```text
https://APP_DOMAIN/api/social/callback/youtube
https://APP_DOMAIN/api/social/callback/instagram
```

Compose keeps `SOCIAL_OAUTH_REDIRECT_BASE_URL` and `SOCIAL_PUBLIC_MEDIA_BASE_URL` on the app domain. Use the settings UI to authorize accounts. Knowing a streaming channel's handle does not authorize publishing to its social accounts. Instagram requires the supported professional-account setup and a signed video URL the platform can reach.

The single-owner bundle exposes the social settings UI by default, while actual publishing still requires configured apps, connected accounts, and explicit channel destinations. The protected initial owner is an administrator. List owned destination IDs for optional CLI use:

```sh
./deploy/vps/compose.sh exec -T backend .venv/bin/python /opt/supoclip-operator.py \
  --email owner@your-domain.tld GET /social/connections
```

Add the chosen IDs to the channel policy and select visibility explicitly. Test YouTube privately first; Instagram Reels are public and require deliberate public configuration. Confirm a controlled authorized test from an external viewer before general unattended publishing. Preserve persisted upload handles and unknown-outcome records instead of blindly resubmitting uncertain posts.

TikTok remains available through its existing interactive flow; automatic policy selection is blocked because consent requirements need separate handling. No Facebook publisher is provided by this bundle.

## Archive originals

Configure an rclone remote using its normal private workflow. Put its config in `deploy/vps/rclone.conf`, keep mode `600`, and set `RECORDING_ARCHIVE_REMOTE` to a server-owned destination such as `archive:bucket/supoclip-originals`. Apply the drained update procedure. Channel requests cannot supply remote flags.

Set `archive:true` only after testing the remote. Download an archived segment and manifest and check its recorded SHA-256. An archive failure must remain visible and cannot justify deleting the only local original. Publishing a clip is not a backup of the original recording. Copy database/config backups off-host as well, with encryption and access controls; a remote path alone does not prove restoration works.

## Health and capacity

```sh
./deploy/vps/health.sh
./deploy/vps/compose.sh ps
./deploy/vps/compose.sh logs --tail 100 recorder worker cron-worker
```

Checks cover PostgreSQL, Redis, ARQ video/cron/AI heartbeats, frontend auth/Prisma, and the recorder heartbeat. Logs rotate to three 20 MB files per service. Review logs for private source content before sharing them.

`restart:unless-stopped` restarts exited processes and starts them after a host/Docker restart. Docker does **not** restart a container merely because it is unhealthy. Use an independent monitor to alert on health failures, low disk, expired leases, growing window age, and publishing errors. A process watchdog or operator must handle a hung container. Health checks cannot establish that source content is correct or a post is publicly visible.

Persistent media and PostgreSQL allow recovery after restarts. Leases prevent healthy supervisors from concurrently owning a channel. Abrupt power loss can leave partial files: process only finalized, verified media. Source errors do not justify erasing originals. Ad breaks and inaccessible streams can still produce real gaps; reconnecting cannot recover bytes never received.

Keep one concurrent video job per owner until measured capacity supports more. The native worker has four global job slots, so multiple owners can exhaust a small VPS; this bundle targets one operator. When rendering repeatedly takes longer than the window interval, reduce quality/window rate, change processing mode/provider, or add a [remote render worker](render-worker.md). Increasing upload allowance does not increase processing capacity.

The bundle sets `MEDIA_UPLOAD_DAILY_LIMIT=500`: a continuously live channel at ten-minute intervals can generate 144 uploads/day. It remains a bounded upload guard, **not** a daily AI-spend limit. Configure provider budgets and channel limits before scaling.

## Backups and restore

Install the daily PostgreSQL/config backup timer after editing its checkout path if needed:

```sh
sudo install -m 0644 deploy/vps/supoclip-backup.service /etc/systemd/system/
sudo install -m 0644 deploy/vps/supoclip-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now supoclip-backup.timer
```

`backup-db.sh` creates a custom-format `pg_dump`, checks its table of contents, and saves the private environment, rclone config, and Git revision. It retains 14 days of its own backup directories. This online backup is consistent for PostgreSQL; it is **not** a simultaneous media snapshot. The timer creates local backups only. Copy them off-host through an encrypted destination and alert on timer failures. Backups include server encryption keys and must remain private.

For a matching full database/media backup, follow the maintenance drain below and stop application writers while leaving PostgreSQL/Redis running:

```sh
./deploy/vps/snapshot.sh /var/backups/supoclip-full-YYYYMMDD
```

The script refuses running recorder/API/frontend/workers. It archives uploads, clips, and recordings using the installed backend image, writes SHA-256 manifests, and dumps the quiescent database. It refuses an existing destination. Restart the same revision afterward. A partial/failed snapshot is not a completed backup.

Test restoration on a **new isolated host/project**, without overwriting the live database:

1. Retrieve the recorded Git revision, private environment, rclone config, dump, media archives, and manifest. Verify archive hashes and preserve encryption/signing secrets.
2. Start only PostgreSQL/Redis on new empty volumes. Restore using `compose.sh exec -T postgres pg_restore -U supoclip -d supoclip --clean --if-exists < postgres.dump`.
3. Restore uploads/clips/recordings to the corresponding **empty** named volumes, removing the leading archive directory. Use extraction that rejects traversal and symlink escapes; the backend's Python supports `tarfile.extractall(..., filter="data")`. Never extract an untrusted archive as host root.
4. Start the recorded application revision. Check health, reconcile outstanding work, and open a clip plus an original segment. Do not run original/restored deployments simultaneously against the same social accounts until ownership is resolved.
5. Switch DNS after successful validation; confirm signed media URLs and OAuth callbacks still match.

Redis AOF supports ordinary restart recovery. Restoring PostgreSQL/media without Redis does not recreate every queued ARQ job automatically: reconcile/requeue durable work and resolve unknown publication outcomes before enabling capture. Deleting Redis is not a safe reset procedure.

## Updates and rollback

Use reviewed releases, not an unattended image updater:

1. Disable channel automation, let capture stop, then stop the recorder. Block new user submissions at the proxy while retaining operator access.
2. Let queued/processing videos and pending/running social posts finish, or cancel through the app. Check **both** PostgreSQL task/post statuses and queued/running Redis ARQ jobs. Recheck immediately before stopping services.
3. Keep a matching database/media backup and record previous backend/frontend image IDs. Stop application writers only after the queues drain.
4. Check out the reviewed revision, build fresh images, run image security checks, validate configuration/Caddy, then use `compose.sh up -d --no-build --wait`. Backend startup applies additive migrations before healthy API startup.
5. Run `health.sh`, check studio playback and the live `/changelog` entry, then enable one channel. Confirm processing and any chosen publishing destination before enabling more.

For rollback, leave capture disabled, drain new work, and return to known-good images. Review the migrations before running an older application: additive tables can often remain, but incompatible schema/data changes need the matching backup restored into a new deployment. Never roll back by deleting durable work or uncertain publication records.

## Optional NVIDIA acceleration

This CPU bundle has no GPU reservation. On a compatible amd64 NVIDIA host, verify NVIDIA Container Toolkit, set `BACKEND_CPU_ONLY=false`, rebuild from the same lockfile, and add an explicit GPU reservation to the **video worker** in a reviewed override. CUDA wheels alone do not grant device access. Native encoding can still use `libx264`; CUDA availability does not imply NVENC encoding.

## Validation status

The bundle supports static validation using `compose.sh config --quiet`, Python/shell syntax checks, and preflight tests. A live VPS deployment, TLS issuance, sustained real-stream capture, provider throughput, off-host restoration, and actual social publication require target infrastructure and authorized accounts. These remain launch checks, not outcomes of configuration validation.
