#!/bin/bash
# Downloaded over the authenticated app's HTTPS origin. No sudo or PATH edits.
set -eu
umask 077
if [ "$(uname -s)" != Darwin ]; then echo 'Run this setup command on your Mac.'; exit 1; fi
if [ "$#" != 2 ]; then echo 'Copy a fresh setup command from SupoClip → Home connection.'; exit 1; fi
APP_ORIGIN="$1"
PAIR_CODE="$2"
case "$(uname -m)" in
  arm64) ARCH=aarch64; EXPECTED=5aeca67f2283f75235de40d0bd9c0a5bbc5fce23b6d48b3bf9fa1b2db08382ca ;;
  x86_64) ARCH=x86_64; EXPECTED=617a3211261b0fc739562f0071aa34e9739797c510208ede8e2977c30903d041 ;;
  *) echo 'This Mac architecture is not supported.'; exit 1 ;;
esac
ROOT="$HOME/Library/Application Support/SupoClip Home Proxy"
mkdir -p "$ROOT"
chmod 700 "$ROOT"
TEMP_SETUP="$(mktemp -d "$ROOT/setup.XXXXXX")"
trap 'rm -rf "$TEMP_SETUP"' EXIT
echo 'Preparing a private runtime. Your system Python and shell settings will not change.'
curl --proto '=https' --tlsv1.2 -fsSL --connect-timeout 15 --max-time 180 \
  "https://github.com/astral-sh/uv/releases/download/0.13.9/uv-$ARCH-apple-darwin.tar.gz" -o "$TEMP_SETUP/uv.tar.gz"
ACTUAL="$(/usr/bin/shasum -a 256 "$TEMP_SETUP/uv.tar.gz" | /usr/bin/awk '{print $1}')"
if [ "$ACTUAL" != "$EXPECTED" ]; then echo 'Runtime download checksum failed. Setup stopped.'; exit 1; fi
tar -xzf "$TEMP_SETUP/uv.tar.gz" -C "$TEMP_SETUP"
mkdir -p "$ROOT/uv"
cp "$TEMP_SETUP/uv-$ARCH-apple-darwin/uv" "$ROOT/uv/uv"
export UV_PYTHON_INSTALL_DIR="$ROOT/python"
"$ROOT/uv/uv" python install 3.12 --no-progress
PYTHON="$("$ROOT/uv/uv" python find --managed-python 3.12)"
"$PYTHON" - "$APP_ORIGIN" "$PAIR_CODE" "$ROOT" <<'PY'
import hashlib,json,os,plistlib,re,subprocess,sys,tempfile,urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
origin,token,root=sys.argv[1:]
p=urlsplit(origin)
if p.scheme!='https' or not p.hostname or p.username or p.password or p.path not in ('','/') or p.query or p.fragment:
    raise SystemExit('Invalid app address; get a fresh setup command from your dashboard.')
if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}',token):
    raise SystemExit('Invalid pairing code; get a fresh setup command from your dashboard.')
root=Path(root)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args): return None
opener=urllib.request.build_opener(NoRedirect)
with tempfile.TemporaryDirectory(dir=root,prefix='pair.') as tmp:
    key=Path(tmp)/'id_ed25519'
    subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-C','supoclip-home-proxy','-f',str(key)],check=True)
    request=urllib.request.Request(origin.rstrip('/')+'/backend/recording/home-proxy/pair',
        data=json.dumps({'token':token,'public_key':key.with_suffix('.pub').read_text().strip()}).encode(),
        headers={'Content-Type':'application/json'},method='POST')
    try:
        with opener.open(request,timeout=30) as response:
            config=json.load(response)
        with opener.open(origin.rstrip('/')+'/backend/recording/home-proxy/helper.py',timeout=30) as response:
            helper=response.read(128000)
    except urllib.error.HTTPError as e:
        raise SystemExit(f'Pairing failed (HTTP {e.code}). Get a fresh setup command from your dashboard.') from None
    except OSError:
        raise SystemExit('Could not reach SupoClip. Check the connection, then get a fresh setup command.') from None
    # Validate the descriptor with the same standalone helper before installing it.
    helper_file=Path(tmp)/'helper.py';helper_file.write_bytes(helper)
    import runpy
    module=runpy.run_path(str(helper_file))
    module['ssh_command'](config,root,19891)
    public=config['ssh_host_key'].split()
    if len(public)<2 or public[0]!='ssh-ed25519' or not re.fullmatch(r'[A-Za-z0-9+/=]+',public[1]):
        raise SystemExit('The server returned an invalid host identity; setup stopped.')
    agent=root/'helper.py';agent.write_bytes(helper);agent.chmod(0o700)
    target=root/'id_ed25519';target.write_bytes(key.read_bytes());target.chmod(0o600)
    (root/'known_hosts').write_text(module['known_hosts_entry'](config))
    (root/'config.json').write_text(json.dumps(config))
label='io.supoclip.home-proxy'
domain=f'gui/{os.getuid()}'
agents=Path.home()/'Library/LaunchAgents';agents.mkdir(parents=True,exist_ok=True)
plist=agents/(label+'.plist')
plist.write_bytes(plistlib.dumps({'Label':label,'ProgramArguments':[sys.executable,str(root/'helper.py'),'--config',str(root/'config.json')],
    'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,
    'StandardOutPath':str(root/'connection.log'),'StandardErrorPath':str(root/'connection.log')}))
subprocess.run(['/bin/launchctl','bootout',domain+'/'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.run(['/bin/launchctl','bootstrap',domain,str(plist)],check=True)
subprocess.run(['/bin/launchctl','kickstart',domain+'/'+label],check=True)
uninstall=root/'uninstall.command'
uninstall.write_text('#!/bin/bash\n/bin/launchctl bootout gui/$(id -u)/io.supoclip.home-proxy 2>/dev/null || true\n'
    '/bin/rm -f "$HOME/Library/LaunchAgents/io.supoclip.home-proxy.plist"\n'
    'echo "Home connection stopped. Disconnect it in the SupoClip dashboard to revoke its key."\n')
uninstall.chmod(0o700)
print('Paired. SupoClip will connect automatically at login and reconnect after interruptions.')
print('Keep this Mac awake and online during recording. Check Home connection in your dashboard.')
print('To stop locally, open: '+str(uninstall))
PY
