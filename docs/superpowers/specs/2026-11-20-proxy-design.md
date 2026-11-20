# Proxy connections and failover

## Intent

Make the existing home connection a separate **Proxy** feature. Configure named
connections once, assign **Live streams**, **Video imports**, or **Both**, order
them, and try another eligible connection when one fails. The current Mac
connection already serves YouTube URL imports and live recording through a
single global setting; the UI currently describes only recording.

The owner requested implementation and has already asked us to proceed without
reopening routine design choices. The decisions below are implementation calls.
“Video imports” means downloading a source URL; local browser file uploads and
official social publishing APIs keep their current connections. This release
governs YouTube ingestion, the purpose of the existing home connection.

## Approach

Keep one existing paired-Mac connection and add up to ten saved proxy URL
connections. Multiple proxy URLs and the Mac can form one ordered failover list.
The existing single-Mac installer and restricted SSH relay remain compatible;
pairing another Mac still replaces the paired Mac. Multi-device SSH provisioning
is outside this change. Keep an encrypted registry in the existing PostgreSQL app-settings table and add a small routing module;
reuse current yt-dlp download budgets, source caches and recording recovery.

A renamed card alone cannot provide routing/failover. Environment-variable lists
cannot provide safe editing, stable identities or health in the dashboard. A
general VPN/tunnel platform would unnecessarily replace the working relay.

## Stored configuration and migration

- Admin-only instance settings, matching the existing home-connection authority.
- Each connection has an opaque ID, name (1–80 characters), kind (URL/home),
  enabled flag, purpose (live/imports/both), integer priority and optional
  two-letter country. URL credentials are encrypted with the existing runtime
  encryption key. GET never returns credentials or a reusable full URL.
- Accept HTTP, HTTPS, SOCKS5 and SOCKS5h URL endpoints, including the existing
  `{session}`/`{country}` template syntax. Reject malformed URLs, control
  characters, paths, query/fragment and unsupported placeholders/schemes.
- First initialization imports existing paired-Mac and configured proxy values
  once, keeping the Mac first and both purposes enabled. An initialization
  marker prevents deleted entries returning from old environment settings.
  A newly paired Mac creates its entry if needed. Existing enabled/purpose/
  priority choices are retained across pairing replacement and restart.
- The database is authoritative. Store the versioned registry as a private
  encrypted app-settings value, loaded alongside existing runtime settings. This
  reuses the established encryption and cross-worker refresh without a database
  migration. Initialize it on first management use; until then, legacy routing
  remains compatible. The generic Admin settings API cannot read/edit this key.
  No dependency or base-image changes.

## Routing and failure behavior

- Filter by enabled/purpose; sort by priority then stable ID. With no assigned
  proxy, retain the ordinary connection. With assigned proxies, exhausted or
  offline routes fail visibly rather than silently using the VPS or paid backup
  downloaders. Cached media remains usable without network access.
- Retry another proxy on connection refusal/reset, timeout, proxy authentication
  rejection, gateway errors or YouTube bot challenge. A deleted/private/age-
  restricted video, an offline channel, bad local media, cancellation, storage
  pressure or byte-budget exhaustion must not condemn a connection.
- Try each eligible connection at most once per failover cycle, within the
  existing overall timeout and shared byte budget. Existing region/session retry
  logic stays bounded. Prefer the successful connection for the rest of the
  source job; changing connections discards only that attempt's incomplete files
  and re-extracts signed media URLs. Never mix route-specific partial responses.
- Redis holds shared failure counts, cooldown and last-result telemetry keyed by
  connection ID, with 30s exponential cooldown capped at 15 minutes. Success
  resets failures. Redis loss may reset health hints, but must not cause direct
  routing or bypass the configured list. IDs/config revision isolate old results
  after a URL edit. API statuses distinguish not checked, reachable, cooling down
  and unavailable; a TCP connection is never called verified YouTube playback.
- Live discovery tries the next proxy on access/transport errors. Capture holds
  one route for the attempt. On connection loss/stall, retain finalized segments,
  stop the current attempt, report the route failure and retry discovery using
  another route. Do not rotate a healthy running stream merely on priority edits.
- yt-dlp/ffmpeg cannot reliably route SOCKS/credentialed proxies themselves in the
  live merge path. Use a bounded loopback HTTP CONNECT adapter for those routes,
  preserving existing A/V clock flags and restricted YouTube destinations. Use
  the locked yt-dlp SOCKS implementation and Python standard library; credentials
  do not appear in child argv, environment, UI responses or diagnostics.

## Dashboard

An admin navigation item **Proxy** opens `/proxy`. It shows the existing Mac
setup controls, an ordered connection list with purpose, enabled state and
health, and **Add proxy**, edit, remove, test and move-up/down actions. Live
channels links to Proxy instead of embedding setup. Blank URL on edit preserves
the saved secret. Removing the Mac entry revokes its pairing; disabling a route
does not revoke it. Removal warns that active work may reconnect. No secret is
placed in a browser URL or validation response.

## Verification and release

Test import-once, authorization, encryption/no echo, purpose filtering,
priority changes, active/ineligible/cooling routes, sticky job selection,
transport/bot failure versus offline/content errors, shared budgets, no direct
fallback, real local proxy transport/authentication and cancellation cleanup.
Exercise desktop/mobile add/edit/clear/reorder and error handling with demo data.
Run affected regressions plus repository checks; build and scan deployable
images, wait for finite jobs to drain, back up DB/config, and verify health,
preserved Mac/AI/social settings and the live changelog after rollout.

Reference: [yt-dlp proxy support](https://github.com/yt-dlp/yt-dlp#network-options).
The installed, locked `FFmpegFD` source explicitly warns that SOCKS is unsupported
and forwards HTTP proxy settings through environment variables; the adapter
keeps the live media merge on the selected connection.
