# Home Proxy Implementation Plan

**Goal:** Pair a Mac with the recording dashboard and route YouTube capture through its connection without a VPN.

**Architecture:** A loopback-only, public-YouTube-destination-only HTTP CONNECT proxy runs on the Mac. An outbound, host-key-pinned SSH tunnel exposes it only on the VPS Docker bridge. A dedicated SSH identity permits only that reverse listener, never a shell. The dashboard issues expiring one-use pairing codes; a host controller installs/revokes public keys. Existing processing and publication stay on the VPS.

**Tech Stack:** Python standard library, macOS launchd, OpenSSH, FastAPI/PostgreSQL, existing Next.js components.

**Authorization:** The operator explicitly requested implementation of the private Mac proxy and easy setup after reviewing the proposed approach. This replaces the earlier unapproved capture-companion design; no additional design approval is requested.

## Constraints

- No public proxy listener, router forwarding, VPN, Google login or browser-cookie extraction.
- Pairing/admin APIs require the existing admin session; redemption is limited, atomic and expires after ten minutes. Only one paired Mac is active per private instance.
- Never distribute VPS login credentials, backend signing secrets or AI keys. Mac generates its own restricted Ed25519 key.
- Fail closed when the tunnel is unavailable; proxy mode must not silently revert to the blocked VPS route.
- Mac remains awake only when the operator enables keep-awake; it must remain connected during capture.
- Existing tasks must drain before any production service recreation; new images must pass the critical security gate.

## Review focus

Cross-account pairing; replay/expiry races; proxy requests to private networks; shell/forwarding escalation; tunnel loss and capture restart without losing finalized segments.

## Task 1 — restricted Mac proxy and proof

- [ ] Add `deploy/home-proxy/home_proxy.py` and tests for CONNECT authority validation, public DNS pinning, bounded connections and pinned SSH arguments.
- [ ] Run tests red, implement standard-library helper, run green.
- [ ] Provision a dedicated tunnel-only server user with config validation and reload; confirm existing SSH settings unchanged for root.
- [ ] Test native media capture through the private bridge endpoint; verify audio/video and cleanup the short capture.

## Task 2 — server pairing and status

- [ ] Add migration and `backend/src/api/routes/home_proxy.py`; register router.
- [ ] GET `/recording/home-proxy`: admin-only status. POST `/setup`: one-use code and setup command. POST `/pair`: redeem code with a generated Ed25519 public key and return pinned SSH descriptor. POST `/disconnect`: revoke pairing and disable route.
- [ ] Record device/public-key state in PostgreSQL; host controller polls only public-key state and terminates revoked tunnel sessions. Do not give containers host-shell authority.
- [ ] Add `deploy/home-proxy/install.sh`, served generically without credentials; copyable command includes only the expiring pairing token.

## Task 3 — dashboard

- [ ] Add a Home connection card to recording dashboard: setup command/copy, connected/waiting/offline status, disconnect, explicit Mac-awake/home-bandwidth description.
- [ ] Extend existing Next recording API allowlist, with tests preserving auth and bounded bodies.
- [ ] Keep setup tokens out of persistent client storage and clear them when expired/paired/disconnected.

## Task 4 — recorder/import routing and deployment

- [ ] Wire configured home proxy into YouTube lookup, Streamlink/browser requests and media capture; use pinned yt-dlp fallback for YouTube where needed.
- [ ] Add dependency source/locks only if the verified November build is needed; preserve all unrelated package pins.
- [ ] Add host installer/controller and deployment environment documentation; add changelog.
- [ ] Run focused and full appropriate tests, typecheck/lint, new image critical scans and live endpoint/changelog checks. Exercise actual Mac setup, reconnect and public-listener isolation. Report any unproven long-running behavior explicitly.
