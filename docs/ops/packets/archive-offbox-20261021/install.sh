#!/usr/bin/env bash
# archive-offbox-20261021 — install the archive off-box sync timer (OPERATOR-RUN ONLY; AGENTS.md §17: a new
# systemd entry is an operator decision).
#   bash install.sh            # DRY RUN (default): shows what would be copied and the diff against any installed copy
#   bash install.sh --apply    # copies the two units to ~/.config/systemd/user, daemon-reload, enable --now the timer
# Prerequisite: the release carrying scripts/archive_offbox_sync.py is CURRENT (the unit runs CURRENT's copy).
# Enabling the timer does not run the service now; the first run is the next 03:30 ET (Persistent=true catches up a
# missed one). To observe a first run by hand, see README.md step 2.
# Rollback: systemctl --user disable --now tradeai-archive-offbox-sync.timer (the unit files may stay; nothing is
# deleted). The manifest and Drive copies are kept.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
CURRENT="${CURRENT_DIR:-$HOME/trade-ai-releases/portfolio-server/CURRENT}"
UNITS=(tradeai-archive-offbox-sync.service tradeai-archive-offbox-sync.timer)
APPLY=0
for a in "$@"; do case "$a" in --apply) APPLY=1 ;; *) echo "unknown argument: $a" >&2; exit 2 ;; esac; done

if [ ! -f "$CURRENT/scripts/archive_offbox_sync.py" ]; then
  echo "WARN: $CURRENT/scripts/archive_offbox_sync.py not present — deploy the release carrying it first" >&2
  [ "$APPLY" = 1 ] && { echo "REFUSED: --apply needs the script in CURRENT" >&2; exit 2; }
fi

for u in "${UNITS[@]}"; do
  if [ -f "$DEST/$u" ]; then
    if cmp -s "$HERE/$u" "$DEST/$u"; then echo "unchanged: $DEST/$u"; else echo "would replace: $DEST/$u"; diff -u "$DEST/$u" "$HERE/$u" || true; fi
  else
    echo "would install: $DEST/$u"
  fi
done
echo "would run: systemctl --user daemon-reload && systemctl --user enable --now tradeai-archive-offbox-sync.timer"

if [ "$APPLY" != 1 ]; then echo "DRY RUN: nothing written"; exit 0; fi

mkdir -p "$DEST"
for u in "${UNITS[@]}"; do
  if [ -f "$DEST/$u" ] && ! cmp -s "$HERE/$u" "$DEST/$u"; then
    bk="$DEST/$u.bak-$(date -u +%Y%m%dT%H%M%SZ)"; cp -p "$DEST/$u" "$bk"; echo "backup: $bk"
  fi
  install -m 0644 "$HERE/$u" "$DEST/$u"
  cmp -s "$HERE/$u" "$DEST/$u" || { echo "FAILED: read-back differs for $DEST/$u" >&2; exit 1; }
done
systemctl --user daemon-reload
systemctl --user enable --now tradeai-archive-offbox-sync.timer
systemctl --user list-timers --all --no-pager | grep -F tradeai-archive-offbox-sync || { echo "FAILED: timer not listed" >&2; exit 1; }
echo "INSTALLED. Next: flip config/lane_registry.json row archive-offbox-sync to ACTIVE (README.md step 4)."
