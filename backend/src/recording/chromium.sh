#!/bin/sh
# Streamlink creates a fresh temporary browser profile. This browser is isolated
# by the dedicated recorder container; it never reuses an operator's browser.
exec /usr/bin/chromium --no-sandbox --disable-dev-shm-usage "$@"
