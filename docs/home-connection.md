# Use your Mac's home connection

This optional feature routes YouTube requests through your Mac while recording, rendering and publishing remain on the Linux server. It requires no VPN, router port forwarding or Google login. It cannot guarantee permanent access to YouTube; a successful short capture is not a guarantee of unattended long-term service.

## Mac setup

1. In **Live channels → Home connection**, select **Set up my Mac**.
2. Copy the setup command into Terminal on your Mac. The pairing code expires after ten minutes and works once.
3. Wait for **Connected**. The helper starts at login and reconnects after network interruptions. No browser tab needs to remain open.

Keep the Mac awake and connected during recording. Closing a laptop lid or logging out interrupts the connection. The installer uses a private Python runtime and your Mac's built-in SSH; no sudo or shell-profile changes are needed. Its SSH private key stays on the Mac. YouTube cookies and AI credentials are not copied to it.

The helper only forwards HTTPS connections to YouTube/Google media domains and rejects private, loopback and link-local DNS answers. It pins the selected public IP to avoid DNS re-resolution. It does not expose a public proxy or change your Mac's system proxy settings. All paired-instance YouTube imports and recording use this route; a disconnected paired Mac causes those operations to fail instead of silently using the server connection.

**Disconnect Mac** revokes its server key. Active tunnel sessions close within the controller's polling interval (five seconds). To stop the helper locally, open `~/Library/Application Support/SupoClip Home Proxy/uninstall.command`; it stops the login service. Revoke the pairing in the dashboard as well. A later fresh setup command can pair it again.

## Efficiency

The helper forwards bytes and SSH encrypts them; no local video encoding or video storage occurs. Your home connection receives and sends the captured stream. For example, a 4 Mb/s stream uses approximately 1.8 GB/hour in each direction, before protocol overhead. Set a recording quality your home upload can sustain. Capturing several channels adds their bitrates.

## One-time Linux server provisioning

After installing the normal Compose stack and applying its migrations, run as root:

```sh
python3 /opt/supoclip/deploy/home-proxy/provision.py \
  --root /opt/supoclip --ssh-host YOUR_SERVER_IP --ssh-port YOUR_SSH_PORT
```

The provisioner discovers the private Docker bridge, creates the tunnel-only `supoclip-relay` user and a scoped SSH Match block, validates SSH configuration before reloading, adds a bridge-only firewall rule when UFW is active, and enables the public-key controller. It writes `HOME_PROXY_*` deployment settings. Drain active jobs before recreating API/worker/recorder containers to apply those settings. Do not change the main SSH login or publish proxy port 18888.

The host controller reads only the registered public key through the existing local PostgreSQL service. Containers receive no permission to execute host commands. It closes existing relay-user sessions when the key changes or is revoked. A database outage longer than thirty seconds closes existing relay access. The controller starts at reboot and does not require a browser session.

The internal listener accepts requests only through the private bridge; the public server exposes its existing authenticated SSH port, not a new proxy port. SSH host identity is delivered over the app's HTTPS connection and pinned on the Mac. Ensure all reverse-proxied public traffic to pairing endpoints is appropriately bounded; pairing redemption also has a shared database-backed attempt limit.

## Remove server support

Disconnect from the dashboard, stop/disable `supoclip-home-proxy.service`, remove the managed `80-supoclip-relay.conf` SSH drop-in and validate/reload SSH. Remove the exact UFW rule labeled `SupoClip home proxy private`, the relay user and `HOME_PROXY_*` settings. Drain active jobs before applying the changed Compose environment. Retain the normal SupoClip data volumes.

## Verification boundaries

The November yt-dlp source is pinned by commit and archive hash in `backend/uv.lock`. Other providers still use Streamlink. YouTube discovery and capture use yt-dlp consistently, including selected proxy routing. The helper is a setup script/login service, not a signed Mac application; Terminal is required once. Only an explicit future feature would add Google session cookies or full local capture.
