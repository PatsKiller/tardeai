#!/usr/bin/env bash
# 05 — route the live crontab's loopback CC prewarm curls (finviz-strip-map, trade-ai,
# trade-ai/scanner — 3 invocations on 2 lines as of 2026-10-14) through scripts/cc_curl.sh so they
# carry the service token. config/lane_registry.json needs NO change: its scheduler.match strings
# are the URLs, which are unchanged.
#
# Builds snapshot + candidate + diff from the LIVE crontab at run time (no stale copy).
# Dry run by default; --apply installs the candidate and reads it back.
# Rollback: 05_crontab_rollback.sh --apply
set -euo pipefail
set -f   # never glob-expand cron lines
OUT="${CC_PACKET_OUT:-$HOME/n8n-maturity-verification/packets/cc-tailscale-identity-20261014}"
CC="${CC_CURL_PATH:-$HOME/trade-ai-releases/portfolio-server/CURRENT/scripts/cc_curl.sh}"
mkdir -p "$OUT"
[[ -x "$CC" ]] || { echo "ABORT: $CC missing/not executable — deploy the release first (step 2)"; exit 1; }
crontab -l > "$OUT/crontab.snapshot"
sha256sum "$OUT/crontab.snapshot" > "$OUT/crontab.snapshot.sha256"
python3 - "$OUT/crontab.snapshot" "$OUT/crontab.candidate" "$CC" <<'PY'
import sys
src, dst, cc = sys.argv[1], sys.argv[2], sys.argv[3]
out, n = [], 0
for line in open(src, encoding="utf-8").read().splitlines(keepends=True):
    if not line.lstrip().startswith("#") and "http://127.0.0.1:7777/" in line and "curl -s -m" in line:
        n += line.count("curl -s -m")
        line = line.replace("curl -s -m", cc + " -s -m")
    out.append(line)
open(dst, "w", encoding="utf-8").write("".join(out))
print(f"substituted {n} curl invocation(s)")
PY
diff "$OUT/crontab.snapshot" "$OUT/crontab.candidate" > "$OUT/crontab.diff" || true
cat "$OUT/crontab.diff"
if [[ "${1:-}" != "--apply" ]]; then
  echo "[dry-run] would: crontab $OUT/crontab.candidate"
  exit 0
fi
crontab "$OUT/crontab.candidate"
crontab -l | diff -q - "$OUT/crontab.candidate" && echo "installed; read-back matches candidate"
