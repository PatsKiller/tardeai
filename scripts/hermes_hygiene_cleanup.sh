#!/usr/bin/env bash
# hermes_hygiene_cleanup.sh
# Safe cleanup for retired Hermes sidecar artifacts and old backups.
# Run manually when desired. Does NOT touch live ~/.hermes/profiles/* or active state.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HOME}/.hermes"

echo "=== Hermes hygiene cleanup (retired artifacts only) ==="

# Retired sidecar install (big venv + old code)
if [[ -d "$ROOT/hermes_sidecar/install.RETIRED_"* ]]; then
  echo "Removing retired sidecar installs..."
  rm -rf "$ROOT/hermes_sidecar"/install.RETIRED_* || true
  rm -rf "$ROOT/hermes_sidecar"/.hermes.RETIRED_* || true
fi

# Migration snapshot from sidecar retirement
if [[ -d "$HERMES_HOME/migration_from_tradeai_sidecar_"* ]]; then
  echo "Removing old migration snapshot..."
  rm -rf "$HERMES_HOME"/migration_from_tradeai_sidecar_* || true
fi

# Optional: aggressively prune very old profile backups (keep last ~3 per profile)
# Commented by default — enable if disk pressure.
# find "$HERMES_HOME/profile_backups" -type f -mtime +30 -delete 2>/dev/null || true

echo "Hermes retired cleanup complete."
echo "Note: live profiles, state.db, sessions, and current logs are untouched."
