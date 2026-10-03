#!/usr/bin/env bash
# LIVE CURRENT browser acceptance for the CIO surfaces (post-deploy; never in PR CI).
#
#   bash scripts/live_cio_browser_acceptance.sh [BASE_URL]
#
# Runs apps/command-center-v3/e2e-live (no API interception) against the served
# host, one page at a time, and brackets the run with the portfolio-server's
# process identity: MainPID and NRestarts before/after and RSS sampled every
# second. A changed MainPID or NRestarts is a FAIL: the run itself must not take
# the server down (the 2026-10-03 heavy-composition finding). Writes a JSON
# receipt under artifacts/live_cio_browser/<UTC stamp>/receipt.json.
# Read-only against the server: GET requests only.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${1:-${LIVE_BASE_URL:-http://localhost:7777}}"
UNIT="${PORTFOLIO_UNIT:-portfolio-server.service}"
CURRENT_DIR="$(readlink -f "${HOME}/trade-ai-releases/portfolio-server/CURRENT" 2>/dev/null || true)"
EXPECTED_SHA="${EXPECTED_SHA:-$(cat "${CURRENT_DIR}/GIT_SHA" 2>/dev/null || true)}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="${LIVE_RUN_DIR:-${ROOT}/artifacts/live_cio_browser/${STAMP}}"
mkdir -p "$RUN_DIR"

svc() { systemctl --user show -p "$1" --value "$UNIT" 2>/dev/null; }
PID_BEFORE="$(svc MainPID)"; RESTARTS_BEFORE="$(svc NRestarts)"
CWD_BEFORE="$(readlink "/proc/${PID_BEFORE}/cwd" 2>/dev/null || true)"

RSS_LOG="${RUN_DIR}/rss.tsv"
(
  while true; do
    pid="$(svc MainPID)"
    rss_kb="$(awk '/^VmRSS:/{print $2}' "/proc/${pid}/status" 2>/dev/null || echo 0)"
    printf '%s\t%s\t%s\t%s\n' "$(date -u +%H:%M:%S)" "$pid" "$rss_kb" "$(svc MemoryCurrent)" >> "$RSS_LOG"
    sleep 1
  done
) &
SAMPLER=$!

cd "${ROOT}/apps/command-center-v3"
LIVE_BASE_URL="$BASE_URL" EXPECTED_SHA="$EXPECTED_SHA" LIVE_RUN_DIR="$RUN_DIR" \
  npx playwright test -c playwright.live.config.ts > "${RUN_DIR}/playwright.log" 2>&1
PW_RC=$?
kill "$SAMPLER" 2>/dev/null; wait "$SAMPLER" 2>/dev/null

PID_AFTER="$(svc MainPID)"; RESTARTS_AFTER="$(svc NRestarts)"
python3 - "$RUN_DIR" "$PW_RC" "$PID_BEFORE" "$PID_AFTER" "$RESTARTS_BEFORE" "$RESTARTS_AFTER" \
  "$EXPECTED_SHA" "$BASE_URL" "$CWD_BEFORE" <<'EOF'
import json, sys
from pathlib import Path
run, rc, pid_b, pid_a, rs_b, rs_a, sha, base, cwd = sys.argv[1:]
run = Path(run)
pages = json.loads((run / "pages.json").read_text()) if (run / "pages.json").exists() else []
lineage = json.loads((run / "lineage.json").read_text()) if (run / "lineage.json").exists() else None
meta = json.loads((run / "build-meta.json").read_text()) if (run / "build-meta.json").exists() else {}
rss = []
for line in (run / "rss.tsv").read_text().splitlines() if (run / "rss.tsv").exists() else []:
    parts = line.split("\t")
    if len(parts) >= 3 and parts[2].isdigit():
        rss.append(int(parts[2]))
restarted = pid_b != pid_a or rs_b != rs_a
receipt = {
    "schema": "LiveCioBrowserAcceptance@v1",
    "authority": "READ_ONLY_ADVISORY",
    "base_url": base,
    "expected_sha": sha or None,
    "served_bundle_sha": meta.get("git_sha"),
    "server": {"main_pid_before": pid_b, "main_pid_after": pid_a, "n_restarts_before": rs_b,
               "n_restarts_after": rs_a, "restarted_during_run": restarted, "cwd": cwd,
               "rss_peak_mb": round(max(rss) / 1024, 1) if rss else None,
               "rss_start_mb": round(rss[0] / 1024, 1) if rss else None, "rss_samples": len(rss)},
    "pages_total": len(pages),
    "pages_failed": [f"{p['name']} @ {p['viewport']}: {'; '.join(p['failures'])}" for p in pages if not p["ok"]],
    "lineage": lineage,
    "playwright_rc": int(rc),
    "verdict": "PASS" if int(rc) == 0 and not restarted else "FAIL",
}
(run / "receipt.json").write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt, indent=2))
sys.exit(0 if receipt["verdict"] == "PASS" else 1)
EOF
