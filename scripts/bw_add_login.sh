#!/usr/bin/env bash
# bw_add_login.sh — add a login item to Bitwarden with SILENT prompts (secrets never echo
# to the terminal or transcript). Companion to the 2026-07-17 recovery-chain hardening.
#
# Usage:  bash scripts/bw_add_login.sh "Item name"
# Needs:  ~/.config/bw_session (from: bw login && bw unlock --raw > session file)
set -euo pipefail
BW="/home/johnclaw/.local/bin/bw"
NAME="${1:?usage: bw_add_login.sh \"Item name\"}"
SESSION_FILE="$HOME/.config/bw_session"
[ -f "$SESSION_FILE" ] || { echo "FATAL: no session — run the login+unlock steps first" >&2; exit 1; }
export BW_SESSION="$(cat "$SESSION_FILE")"

# refuse duplicates
export BW_NAME_CHECK="$NAME"
if "$BW" list items --search "$NAME" 2>/dev/null | python3 -c "
import json,sys,os
items=json.load(sys.stdin)
sys.exit(0 if any(i.get('name')==os.environ['BW_NAME_CHECK'] for i in items) else 1)" 2>/dev/null; then
  echo "'$NAME' already exists in the vault — not creating a duplicate. (Edit it in the app if needed.)"
  exit 0
fi

read -r -p  "  username / email        : " BW_U
read -r -s -p "  password (hidden)       : " BW_P; echo
read -r -s -p "  2FA recovery codes (hidden, Enter to skip): " BW_R; echo
export BW_U BW_P BW_R BW_NAME="$NAME"

python3 - <<'EOF'
import json, os, subprocess, hashlib, sys
BW = "/home/johnclaw/.local/bin/bw"
env = dict(os.environ)
name, user, pw, rec = env["BW_NAME"], env["BW_U"], env["BW_P"], env.get("BW_R", "")
notes = "Added via bw_add_login.sh (recovery-chain hardening 2026-07-17)."
if rec.strip():
    notes += "\n\n2FA RECOVERY CODES:\n" + rec.strip()
tmpl = {"type": 1, "name": name, "notes": notes, "login": {"username": user, "password": pw}}
enc = subprocess.run([BW, "encode"], input=json.dumps(tmpl), capture_output=True, text=True, env=env).stdout.strip()
r = subprocess.run([BW, "create", "item", enc], capture_output=True, text=True, env=env)
if r.returncode != 0:
    print(f"CREATE FAILED: {r.stderr[:200]}", file=sys.stderr); sys.exit(1)
item = json.loads(r.stdout)
got = subprocess.run([BW, "get", "password", item["id"]], capture_output=True, text=True, env=env).stdout.strip()
ok = hashlib.sha256(got.encode()).hexdigest() == hashlib.sha256(pw.encode()).hexdigest()
print(f"'{name}': created (id {item['id'][:8]}…) · round-trip verified: {ok}")
sys.exit(0 if ok else 1)
EOF
unset BW_P BW_R
