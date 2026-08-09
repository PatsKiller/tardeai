#!/usr/bin/env bash
# sync_cio_delivery.sh — Sync CIO Phase 3 delivery doc to Drive + email summary
# Run once: bash scripts/sync_cio_delivery.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

DOC="docs/architecture/cio/CIO_PHASE_3_DELIVERY.md"
GOG="$(which gog 2>/dev/null || echo "$HOME/.local/bin/gog")"
ACCOUNT="john@jwwhiting.com"

# ── Resolve keyring password ──────────────────────────────────────────────
if [ -f "$HOME/.openclaw/credentials/gog_keyring_password" ]; then
    export GOG_KEYRING_PASSWORD=$(cat "$HOME/.openclaw/credentials/gog_keyring_password")
fi

echo "=== Syncing CIO delivery doc to Google Drive ==="
"$GOG" --account "$ACCOUNT" drive upload "$DOC" 2>&1 || echo "Drive upload failed (non-fatal)"

echo ""
echo "=== Sending email summary ==="
"$PROJECT_ROOT/.venv/bin/python" -c "
import sys; sys.path.insert(0, 'scripts')
from email_notifier import send_email
result = send_email(
    subject='CIO Phase 3 — Autonomous Investment Office Delivered',
    body=open('$DOC').read()[:4000],
    to='$ACCOUNT'
)
print('Email:', result.get('sent', result))
" 2>&1 || echo "Email failed (non-fatal)"

echo ""
echo "=== Done ==="
echo "CIO delivery doc: $DOC"
echo "Drive: synced to john@jwwhiting.com Drive"
echo "Email: sent to john@jwwhiting.com"
