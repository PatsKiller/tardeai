#!/usr/bin/env bash
# Run research only outside the regular/premarket US equity session.
# A prohibited session is a successful skip; infrastructure failures are not.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 70
root="$PWD"
python="${PY:-${VENV_PYTHON:-${CANONICAL_SOURCE:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}/.venv/bin/python}}"
dry_run=0
if [[ "${1:-}" == "--dry-run" ]]; then dry_run=1; shift; fi

# A system interpreter records health even when the configured runtime is absent.
# The session check itself never falls back to a different runtime.
record() {
    local status="$1" reason="$2" session="${3:-}"
    echo "[non_trading_hours_gate] status=$status reason=$reason session=$session"
    [[ "$dry_run" == 1 ]] && return 0
    /usr/bin/python3 - "$root" "$status" "$reason" "$session" "$python" <<'PYHEALTH'
import json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
root, status, reason, session, interpreter = sys.argv[1:]
sys.path.insert(0, root)
from scripts.lib.persistent_state_root import resolve_durable_dir
path = resolve_durable_dir("data/health", Path(root)) / "non_trading_hours_gate.json"
path.parent.mkdir(parents=True, exist_ok=True)
row = {"status": status, "reason": reason, "session": session, "interpreter": interpreter,
       "as_of": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "root": root}
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
    json.dump(row, f)
    f.write("\n")
os.replace(f.name, path)
PYHEALTH
}
if [[ ! -x "$python" ]]; then
    record FAILED interpreter_missing || echo "health receipt failed" >&2
    exit 69
fi
if ! session=$("$python" -c 'import sys; sys.path.insert(0, "scripts"); from market_session import current_market_session; print(current_market_session())'); then
    record FAILED session_check_failed || echo "health receipt failed" >&2
    exit 70
fi
case "$session" in
    afterhours|closed|weekend|holiday)
        record ALLOWED allowed_session "$session" || exit 74
        if [[ "$dry_run" == 1 ]]; then
            printf 'would_run:'; printf ' %q' "$@"; printf '\n'
            exit 0
        fi
        [[ "$#" -gt 0 ]] || { record FAILED command_missing "$session"; exit 64; }
        exec "$@"
        ;;
    regular|premarket)
        record SKIPPED prohibited_session "$session" || exit 74
        exit 0
        ;;
    *)
        record FAILED unknown_session "$session" || echo "health receipt failed" >&2
        exit 65
        ;;
esac
