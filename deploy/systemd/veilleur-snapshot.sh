#!/bin/sh
# SPDX-License-Identifier: EUPL-1.2
# A consistent copy of what a restore needs, replaced in one step. Needs the sqlite3 command.
set -eu
state=/var/lib/veilleur
work=$(mktemp -d "$state/.snapshot.XXXXXX")
trap 'rm -rf "$work"' EXIT
sqlite3 "$state/veilleur.db" ".backup '$work/veilleur.db'"
test "$(sqlite3 "$work/veilleur.db" 'PRAGMA integrity_check;')" = ok
for name in signing.key rotation.json rotation.sig webhook.key; do
    if [ -e "$state/$name" ]; then cp -p "$state/$name" "$work/$name"; fi
done
rm -rf "$state/snapshot.old"
if [ -e "$state/snapshot" ]; then mv "$state/snapshot" "$state/snapshot.old"; fi
mv "$work" "$state/snapshot"
rm -rf "$state/snapshot.old"
