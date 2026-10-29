#!/usr/bin/env bash
# Build a release_train_arm test sandbox and print the env lines to run the arming script inside it.
#   bash make_sandbox.sh <new dir under $TMPDIR> <repo root> <python>   ->   KEY=VALUE lines on stdout
# Everything the arming script touches lands under <dir>: HOME, state root, config, unit dir, live-lanes env,
# receipts. psql / systemctl / docker / curl are stubs in <dir>/bin (the script refuses a sandbox where they
# resolve anywhere else). The code root is a symlink farm onto the repo, so the real libraries run.
set -euo pipefail
SB="$1"; REPO="$2"; PYBIN="$3"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$SB/home/.config/tradeai" "$SB/bin" "$SB/code/.venv/bin" "$SB/fake/n8n/rows"
touch "$SB/.rtarm-sandbox" "$SB/calls.log"
for t in psql systemctl docker curl; do cp "$HERE/stubs/$t" "$SB/bin/$t"; chmod 755 "$SB/bin/$t"; done
for d in scripts config docs migrations; do ln -sfn "$REPO/$d" "$SB/code/$d"; done
ln -sfn "$PYBIN" "$SB/code/.venv/bin/python"
# A pre-existing live list with one unrelated lane and one unrelated line, both of which must survive step E.
printf 'TRADEAI_N8N_RELAY_LIVE_LANES=disk-usage-monitor\nOTHER_KEY=keep-me\n' > "$SB/home/.config/tradeai/n8n-live-lanes.env"
chmod 600 "$SB/home/.config/tradeai/n8n-live-lanes.env"
echo ACTIVE > "$SB/fake/n8n/rows/tradeai-fabric-error"
cat <<EOF
RTARM_SANDBOX=$SB
RTARM_CODE_ROOT=$SB/code
RTARM_PY=$PYBIN
RTARM_EXPECT_USER=$(id -un)
RTARM_EXPECT_HOST=$(hostname -s)
RTARM_RELAY_PROBE=0
RTARM_PSQL_ARGS=-U trade_ai -d trade_ai
RTARM_NOW_HM=1200
RTARM_SLEEP=0
PYTHONDONTWRITEBYTECODE=1
PATH=$SB/bin:$PATH
EOF
