#!/bin/sh
# Run beets as the PUID/PGID user; seed /config on first start.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if ! getent group beets >/dev/null; then
    groupadd -o -g "$PGID" beets
fi
if ! id beets >/dev/null 2>&1; then
    useradd -o -u "$PUID" -g "$PGID" -d /config -M -s /usr/sbin/nologin beets
fi

mkdir -p /config /music/inbox /music/library
[ -f /config/config.yaml ] || cp /defaults/config.yaml /config/config.yaml
chown -R beets:beets /config
# not recursive: a large library would take ages; only the mount points
chown beets:beets /music/inbox /music/library 2>/dev/null || true

exec gosu beets beet "$@"
