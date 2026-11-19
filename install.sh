#!/usr/bin/env bash
# Install the single-operator SupoClip fork on a Docker-capable Linux machine.
# Default: local HTTP dashboard. --domain enables Caddy-managed HTTPS.
set -euo pipefail
umask 077

usage() {
  cat <<'HELP'
Usage: bash install.sh [--directory PATH] [--host HOST] [--port PORT]
                       [--domain DOMAIN --email EMAIL] [--ref BRANCH_TAG_OR_COMMIT] [--no-start]

Existing Docker/Compose and application secrets are preserved. On supported
Debian/Ubuntu/Fedora/RHEL-family hosts, missing prerequisites can be installed
using the distro package manager and Docker's official package repositories.
Root/sudo is required only if those packages or Docker daemon access need it.
HTTP defaults to localhost:3107. For a remote server, use an SSH tunnel or
--host with its reachable address. Configure AI keys, channels and publishing
accounts in the dashboard after creating the protected initial owner.
HELP
}

install_directory=""
public_host=localhost
http_port=3107
domain=""
operator_email=""
no_start=false
source_ref=${SUPOCLIP_REF:-feat/recording-foundation}
while (($#)); do
  case "$1" in
    --directory|--host|--port|--domain|--email|--ref)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --directory) install_directory=$2 ;;
        --host) public_host=$2 ;;
        --port) http_port=$2 ;;
        --domain) domain=$2 ;;
        --email) operator_email=$2 ;;
        --ref) source_ref=$2 ;;
      esac
      shift 2 ;;
    --no-start) no_start=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ $source_ref =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || { echo '--ref must be a branch, tag, or full commit SHA.' >&2; exit 2; }
[[ $(uname -s) == Linux ]] || { echo 'This installer targets Linux. Use the repository development instructions on macOS/Windows.' >&2; exit 1; }
case "$(uname -m)" in
  x86_64|amd64) backend_platform=linux/amd64 ;;
  aarch64|arm64) backend_platform=linux/arm64 ;;
  *) echo 'The video dependency set requires a 64-bit amd64 or arm64 Linux host. This CPU architecture is unsupported.' >&2; exit 1 ;;
esac
[[ $http_port =~ ^[0-9]+$ && $http_port -ge 1024 && $http_port -le 65535 ]] || { echo 'Choose an HTTP port from 1024 to 65535.' >&2; exit 2; }
[[ $public_host =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || { echo '--host must be a hostname or IPv4 address.' >&2; exit 2; }
if [[ -n $domain ]]; then
  [[ $domain =~ ^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,63}$ && -n $operator_email && $operator_email != *$'\n'* && $operator_email != *$'\r'* ]] || { echo '--domain requires a DNS hostname and --email for certificate management.' >&2; exit 2; }
fi

as_root() {
  if [[ $(id -u) == 0 ]]; then "$@"; else sudo "$@"; fi
}

install_prerequisites() {
  local distro release codename arch repo_distro
  [[ -r /etc/os-release ]] || { echo 'Install Docker Engine, Compose, Git, curl, and Python 3, then rerun.' >&2; exit 1; }
  # This is the host OS metadata, not downloaded executable code.
  . /etc/os-release
  distro=${ID:-}
  release=${VERSION_ID:-}
  case "$distro" in
    ubuntu|debian)
      as_root apt-get update
      as_root apt-get install -y ca-certificates curl git python3
      if ! command -v docker >/dev/null 2>&1; then
        codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}
        [[ -n $codename ]] || { echo 'Could not determine the Docker repository distribution codename.' >&2; exit 1; }
        arch=$(dpkg --print-architecture)
        as_root install -m 0755 -d /etc/apt/keyrings
        as_root curl --fail --silent --show-error --location "https://download.docker.com/linux/$distro/gpg" -o /etc/apt/keyrings/docker.asc
        as_root chmod a+r /etc/apt/keyrings/docker.asc
        printf 'Types: deb\nURIs: https://download.docker.com/linux/%s\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' "$distro" "$codename" "$arch" | as_root tee /etc/apt/sources.list.d/docker.sources >/dev/null
        as_root apt-get update
        as_root apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
      elif ! docker compose version >/dev/null 2>&1; then
        # Never remove or replace an existing engine/package family automatically.
        if ! as_root apt-get install -y docker-compose-plugin; then
          echo 'The existing Docker installation needs its matching Compose plugin. Install it using your Docker package source, then rerun.' >&2
          exit 1
        fi
      fi ;;
    fedora|rhel|centos|rocky|almalinux)
      command -v dnf >/dev/null 2>&1 || { echo 'Install Docker/Compose with the host package manager, then rerun.' >&2; exit 1; }
      as_root dnf install -y ca-certificates curl git python3
      if ! command -v docker >/dev/null 2>&1; then
        repo_distro=$distro
        case "$distro" in rocky|almalinux) repo_distro=centos ;; esac
        as_root curl --fail --silent --show-error --location "https://download.docker.com/linux/$repo_distro/docker-ce.repo" -o /etc/yum.repos.d/docker-ce.repo
        as_root dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
      elif ! docker compose version >/dev/null 2>&1; then
        as_root dnf install -y docker-compose-plugin
      fi ;;
    *)
      echo 'This distro needs Docker Engine/Compose, Git, curl, and Python 3 installed first. Existing Docker-capable Linux hosts are supported; no existing packages were removed.' >&2
      echo 'See https://docs.docker.com/engine/install/' >&2
      exit 1 ;;
  esac
  if command -v systemctl >/dev/null 2>&1; then as_root systemctl enable --now docker; fi
}

if ! command -v git >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1 || ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  install_prerequisites
fi

if [[ -z $install_directory ]]; then
  script_source=${BASH_SOURCE[0]:-}
  if [[ -f $script_source && -d $(dirname -- "$script_source")/backend && -f $(dirname -- "$script_source")/deploy/vps/compose.yml ]]; then
    install_directory=$(CDPATH= cd -- "$(dirname -- "$script_source")" && pwd)
  else
    install_directory=$PWD/supoclip
  fi
fi
if [[ ! -f $install_directory/deploy/vps/compose.yml ]]; then
  [[ ! -e $install_directory ]] || { echo 'The target directory exists and is not a SupoClip checkout; choose --directory.' >&2; exit 1; }
  if [[ $source_ref =~ ^[0-9a-fA-F]{40}$ ]]; then
    git clone --no-checkout --filter=blob:none https://github.com/primecode-khalil/supoclip.git "$install_directory"
    git -C "$install_directory" fetch --depth 1 origin "$source_ref"
    git -C "$install_directory" checkout --detach FETCH_HEAD
  else
    git clone --branch "$source_ref" --single-branch https://github.com/primecode-khalil/supoclip.git "$install_directory"
  fi
fi
install_directory=$(CDPATH= cd -- "$install_directory" && pwd)
vps_dir=$install_directory/deploy/vps
if [[ ! -f $vps_dir/.env ]]; then
  python3 "$vps_dir/init-env.py"
  python3 - "$vps_dir" "$public_host" "$http_port" "$domain" "$operator_email" "$backend_platform" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
host, port, domain, email, backend_platform = sys.argv[2:]
path = root / ".env"
values = {"APP_ORIGIN": f"http://{host}:{port}", "API_ORIGIN": f"http://{host}:{port}/backend", "HTTP_PORT": port}
if domain:
    values.update(APP_DOMAIN=domain, APP_ORIGIN=f"https://{domain}", API_ORIGIN=f"https://{domain}/backend", ACME_EMAIL=email, VPS_HTTPS="true")
values["BACKEND_PLATFORM"] = backend_platform
lines = path.read_text().splitlines()
path.write_text("\n".join(f"{line.split('=', 1)[0]}={values[line.split('=', 1)[0]]}" if "=" in line and line.split('=', 1)[0] in values else line for line in lines) + "\n")
path.chmod(0o600)
PY
else
  echo 'Preserving the existing private configuration and selected HTTP/HTTPS mode.'
fi
python3 "$vps_dir/preflight.py"
if [[ $no_start == true ]]; then
  echo 'Configuration prepared. No images were built or containers started.'
  exit 0
fi
if ! docker info >/dev/null 2>&1; then
  echo 'Docker daemon access is required. Start Docker, or rerun this saved script with sudo if your account lacks access.' >&2
  exit 1
fi
# A durable completion marker, not container presence, distinguishes a healthy
# install from a failed first start. Recovery never recreates existing containers.
"$vps_dir/up.sh"
python3 - "$vps_dir/.env" <<'PY'
from pathlib import Path
import sys
values = dict(line.split("=", 1) for line in Path(sys.argv[1]).read_text().splitlines() if line and not line.startswith("#") and "=" in line)
print("Open the setup dashboard: " + values["APP_ORIGIN"] + "/sign-up")
print("Initial owner setup token (keep private): " + values["INITIAL_SETUP_TOKEN"])
print("After registration, configure AI providers at /admin and channels at /recording.")
PY
