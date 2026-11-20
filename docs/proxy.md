# Proxy connections

Open **Proxy** in the dashboard (administrator only), or follow the link from
**Live channels**. Save each connection once and choose **Live streams**,
**Video imports**, or **Both**. Video imports means YouTube URLs entered in the
upload/create flow. Local video file uploads and official social publishing use
their usual connections; they do not need a YouTube proxy.

## Set up

1. To use your Mac's internet connection, select **Set up my Mac**, copy the
   command and run it on that Mac. Keep it awake and online. The existing
   installer reconnects automatically; no router changes are needed.
2. Alternatively, select **Add proxy**, give it a name and enter an HTTP, HTTPS,
   SOCKS5 or SOCKS5h endpoint. URL-encode special characters in credentials.
3. Select its purpose and enable it. Move connections up/down to choose priority.
   You can save ten URL endpoints plus one paired Mac. Replacing the Mac still
   replaces the single paired device.
4. Select **Test YouTube**. It checks metadata through that connection. Optionally
   choose a public YouTube test video below the list. This does not promise that
   playback, every channel or every restricted video will work.

Credentials are encrypted in the existing settings store. Reads show only the
host/port and whether credentials are saved. When editing, leave the Proxy URL
empty to preserve its endpoint and credentials. A country template can use
`{country}` and a sticky endpoint can use `{session}`.

## Failover

Each new operation tries eligible connections in priority order. A successful
import keeps its connection for the task's metadata, audio and sections. A live
probe returns its winning connection to the recorder; capture uses that same
route. A later capture failure or stall retains completed chunks and allows the
supervisor to reconnect using another eligible proxy. Reconnection can leave a
gap in a live recording; it is not a seamless network handoff.

Known transport, authentication and bot-challenge failures produce a shared
cooldown, starting at 30 seconds and rising to 15 minutes. Success resets it.
Offline/private videos and local processing errors do not mark every route bad.
Source-specific geographic/403 errors may try another route without a shared
penalty. Import attempts share the original byte allowance and overall deadline;
adding proxies does not multiply these budgets.

If a purpose has assigned enabled proxies and none is usable, that operation
fails or waits for its normal retry. It does not silently switch to the server
IP or a paid downloader. If no enabled proxy is assigned to that purpose, the
normal server/provider path applies. Disabling all connections therefore opts
back into that path. Redis health is advisory; losing Redis does not permit a
direct bypass of configured routing.

Settings apply to new operations. An in-progress download or recording may
finish using its held connection. Removing the paired Mac also disconnects it;
removing another endpoint does not delete saved videos or clip tasks.

## Existing installations

On first opening Proxy, the app adopts the existing paired Mac and
`YOUTUBE_PROXY_URL` as saved connections, initially for **Both**. It preserves
the current pairing, AI keys and social accounts. After adoption, this registry
is authoritative for YouTube ingestion; edit it in Proxy. The old environment
values are a bootstrap source, not a way to restore deleted connections.

The registry uses an encrypted private `app_settings` value, so no new database
migration or dependency is needed. Keep the server's settings encryption key
stable and back up the database with it. Health is transient Redis state.
The YouTube routing manager does not change Twitch/Kick ingestion.

A proxy uses another internet exit. YouTube may still challenge that exit or
restrict a particular account/video; this feature cannot guarantee access.
