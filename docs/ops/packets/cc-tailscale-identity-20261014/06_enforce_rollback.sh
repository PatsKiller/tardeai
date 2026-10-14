#!/usr/bin/env bash
# 06 rollback — back to report_only (archive the drop-in; never delete it).
set -euo pipefail
F="$HOME/.config/systemd/user/portfolio-server.service.d/44-cc-auth-enforce.conf"
if [[ "${1:-}" != "--apply" ]]; then echo "[dry-run] would: mv $F $F.disabled-<stamp>; daemon-reload; restart portfolio-server"; exit 0; fi
mv "$F" "$F.disabled-$(date -u +%Y%m%dT%H%M%SZ)"
systemctl --user daemon-reload
systemctl --user restart portfolio-server.service
echo "report_only restored (config/cc_auth.yaml default)"
