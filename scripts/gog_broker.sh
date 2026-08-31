#!/usr/bin/env bash
# gog_broker.sh — run gog with the keyring credential brokered from Bitwarden.
#
# WHY THIS EXISTS
# ---------------
# gog's keyring backend is `file`, unlocked by GOG_KEYRING_PASSWORD. The working
# uploader (scripts/sync-docs-to-drive.sh) reads that password from
#   ~/.openclaw/credentials/gog_keyring_password
# Cursor's read guard (guard-read.sh:32) blocks every path matching *credentials*,
# fail-closed. So Cursor cannot publish to Drive -- not because gog is broken, and
# not because an env var is missing, but because the only supported source of the
# secret is a path the guard is right to refuse.
#
# This broker takes the secret from Bitwarden instead. No agent reads the plaintext
# credential file, so the guard is satisfied without being weakened.
#
# GUARANTEES
#   - the secret is never echoed, logged, or written to disk by this script
#   - it is exported only into the exec'd child process
#   - an unapproved caller fails loudly; it never falls through to a weaker source
#   - it never reads ~/.openclaw/credentials/* -- that path stays operator-only
#
# USAGE
#   TRADEAI_AGENT=cursor scripts/gog_broker.sh drive files list
#
# ONE-TIME OPERATOR SETUP
#   1. store the item (prompts silently, round-trip verified):
#        scripts/bw_add_login.sh "$GOG_BW_ITEM"
#   2. unlock once per boot and export the session:
#        export BW_SESSION=$(bw unlock --raw)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALLOWLIST="${GOG_APPROVED_AGENTS_FILE:-$ROOT/config/gog_approved_agents.txt}"
BW_ITEM="${GOG_BW_ITEM:-gog_keyring_password}"
BW_BIN="${BW_BIN:-$HOME/.local/bin/bw}"

die() { echo "gog_broker: $*" >&2; exit 2; }

# ── 1. approval ───────────────────────────────────────────────────────────────
[ "$#" -gt 0 ] || die "no gog arguments given. Example: TRADEAI_AGENT=cursor $0 drive files list"

AGENT="${TRADEAI_AGENT:-}"
[ -n "$AGENT" ] || die "TRADEAI_AGENT is not set. Declare which agent you are; see $ALLOWLIST"
[ -r "$ALLOWLIST" ] || die "approval list not readable: $ALLOWLIST"
if ! grep -vE '^[[:space:]]*(#|$)' "$ALLOWLIST" | grep -qxF "$AGENT"; then
    die "agent '$AGENT' is not approved. The operator adds ids to $ALLOWLIST; agents must not add themselves."
fi

# ── 2. bitwarden ──────────────────────────────────────────────────────────────
[ -x "$BW_BIN" ] || die "bitwarden CLI not found or not executable at $BW_BIN (set BW_BIN)"
[ -n "${BW_SESSION:-}" ] || die "BW_SESSION is not set. The vault is locked and this script will not prompt for a master password.
  The operator unlocks once per boot:  export BW_SESSION=\$(bw unlock --raw)"

status="$("$BW_BIN" status --session "$BW_SESSION" 2>/dev/null \
          | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status","unknown"))' 2>/dev/null || echo unreadable)"
[ "$status" = "unlocked" ] || die "vault is '$status', not unlocked. Re-run: export BW_SESSION=\$(bw unlock --raw)"

# Capture into a variable, never a file, never stdout.
if ! secret="$("$BW_BIN" get password "$BW_ITEM" --session "$BW_SESSION" 2>/dev/null)" || [ -z "$secret" ]; then
    die "could not read item '$BW_ITEM' from Bitwarden.
  Store it once with:  scripts/bw_add_login.sh '$BW_ITEM'
  (a missing item and a locked vault are different failures; the vault reads as unlocked here)"
fi

# ── 3. exec ───────────────────────────────────────────────────────────────────
# Exported into the child only. `exec` replaces this shell, so the value does not
# outlive the call and is not inherited by anything the caller runs afterwards.
GOG_BIN="${GOG_BIN:-$HOME/.local/bin/gog}"
[ -x "$GOG_BIN" ] || die "gog not found or not executable at $GOG_BIN (set GOG_BIN)"
export GOG_KEYRING_PASSWORD="$secret"
unset secret
exec "$GOG_BIN" "$@"
