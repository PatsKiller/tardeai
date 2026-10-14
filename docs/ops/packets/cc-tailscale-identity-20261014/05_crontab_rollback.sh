#!/usr/bin/env bash
# 05 rollback — reinstall the crontab snapshot taken by 05_crontab_install.sh (only if the live
# crontab is still exactly the installed candidate; otherwise restore by hand).
set -euo pipefail
set -f
OUT="${CC_PACKET_OUT:-$HOME/n8n-maturity-verification/packets/cc-tailscale-identity-20261014}"
if ! crontab -l | diff -q - "$OUT/crontab.candidate" >/dev/null; then
  echo "ABORT: live crontab is not the installed candidate; restore by hand from $OUT/crontab.snapshot"; exit 1
fi
if [[ "${1:-}" != "--apply" ]]; then echo "[dry-run] would: crontab $OUT/crontab.snapshot"; exit 0; fi
crontab "$OUT/crontab.snapshot"
crontab -l | diff -q - "$OUT/crontab.snapshot" && echo "rolled back; read-back matches snapshot"
