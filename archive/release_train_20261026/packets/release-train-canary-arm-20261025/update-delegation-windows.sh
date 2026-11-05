#!/usr/bin/env bash
# update-delegation-windows.sh — OPERATOR ONLY, run once at the host TTY after PR #2099 is released (CURRENT carries
# the 9-slot release_delegation.WINDOW_IDS). The delegation record is operator-owned; no agent runs this.
#
# It authorizes the 2026-10-25 schedule slots in the standing delegation's windows section ONLY:
#   enabled: 1800 (kept), 1200, 0000, 0300, 0600, 0900, 1500, 2100      unchanged: 0800 (and every other section)
# The delegation authorizes slot ids on every day; the repo policy (config/release_train_policy.json windows[].days)
# schedules them (weekdays 12:00 + 18:00 ET; every three hours Saturday 06:00 through Sunday 21:00) and can only
# narrow, so later schedule edits within these slots need no delegation change. A live train needs both,
# plus the accepted digest, so this script finishes with release_control_cli.py change-scope (TTY phrase).
#
#   bash update-delegation-windows.sh            # default --preview: diff of the windows section only; writes nothing
#   bash update-delegation-windows.sh --apply    # type ACK-TRAIN-WINDOWS; archives the old record (never deleted),
#                                                # writes the new one (mode 600), then change-scope --dry-run and the
#                                                # live change-scope (you type its CHANGE_SCOPE EPOCH n phrase)
# Rollback: the archived copy sits next to the record (delegation.json.archived-<stamp>); move it back, then run
# release_control_cli.py change-scope again. STOP / revoke work at any time. MBI_BEHAVIOR = 0.
set -euo pipefail

CURRENT="${TRADEAI_CURRENT:-${HOME}/trade-ai-releases/portfolio-server/CURRENT}"
DELEGATION="${TRADEAI_RELEASE_DELEGATION:-${HOME}/.config/tradeai/release_train/delegation.json}"
PY="${CURRENT}/.venv/bin/python"
ACK_WORD="ACK-TRAIN-WINDOWS"
MODE="${1:---preview}"

[[ -x "$PY" ]] || { echo "refused: no interpreter at $PY"; exit 2; }
[[ -f "$DELEGATION" ]] || { echo "refused: no delegation record at $DELEGATION"; exit 2; }

plan() {  # $1 = out path for the new record ("" = preview only). Prints only the windows section diff.
  ( cd "$CURRENT" && "$PY" -I - "$DELEGATION" "${1:-}" <<'PY'
import difflib, json, os, sys
sys.path[:0] = [os.getcwd(), os.path.join(os.getcwd(), "scripts")]
from scripts.lib import release_delegation as RD

src, out = sys.argv[1], sys.argv[2]
need = ("0000", "0300", "0600", "0800", "0900", "1200", "1500", "1800", "2100")
if tuple(sorted(RD.WINDOW_IDS)) != need:
    sys.exit(f"refused: CURRENT's release_delegation.WINDOW_IDS is {RD.WINDOW_IDS}; release PR #2099 first")
v = RD.load(src)
if v.delegation is None:
    sys.exit(f"refused: the delegation does not load ({v.code}); nothing changed")
old = v.delegation
new = json.loads(json.dumps(old))
slots = {s["window_id"]: s for s in new["windows"]["slots"]}
ADD = {"1200": ("12:00", 90, "midday"), "0000": ("00:00", 120, "general"), "0300": ("03:00", 90, "weekend"),
       "0600": ("06:00", 60, "requires_drain_or_non_disruptive_path"), "0900": ("09:00", 90, "weekend"),
       "1500": ("15:00", 90, "weekend"), "1800": ("18:00", 90, "canary"), "2100": ("21:00", 90, "weekend")}
for wid, (start, dur, role) in ADD.items():
    if wid in slots:
        slots[wid]["enabled"] = True
    else:
        slots[wid] = {"window_id": wid, "start_et": start, "duration_min": dur, "enabled": True, "role": role}
order = ["1800", "1200", "0000", "0300", "0600", "0800", "0900", "1500", "2100"]
new["windows"]["slots"] = [slots[w] for w in order if w in slots]
errs = RD.validate(new)
if errs:
    sys.exit("refused: the new record would not validate: " + "; ".join(errs))
a = json.dumps(old["windows"], indent=2, sort_keys=True).splitlines()
b = json.dumps(new["windows"], indent=2, sort_keys=True).splitlines()
print("\n".join(difflib.unified_diff(a, b, "windows (current)", "windows (new)", lineterm="")) or "windows: UNCHANGED")
print(f"digest: {v.digest} -> {RD.policy_digest(new)}")
if out:
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(new, fh, indent=2)
        fh.write("\n")
PY
  )
}

case "$MODE" in
  --preview)
    echo "== PREVIEW (nothing written): windows section of $DELEGATION =="
    plan ""
    ;;
  --apply)
    plan "" >/dev/null || { echo "refused: preview failed; nothing written"; exit 2; }
    plan ""
    printf 'Type %s to write the new windows section: ' "$ACK_WORD"
    typed=""; read -r typed || true
    [[ "$typed" == "$ACK_WORD" ]] || { echo; echo "refused: acknowledgement not typed; nothing written"; exit 2; }
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    tmp="${DELEGATION}.new-${stamp}"
    plan "$tmp" >/dev/null
    cp -p "$DELEGATION" "${DELEGATION}.archived-${stamp}"
    chmod 600 "${DELEGATION}.archived-${stamp}" "$tmp"
    mv "$tmp" "$DELEGATION"
    echo "written (archive: ${DELEGATION}.archived-${stamp}); live trains refuse POLICY_NOT_ACCEPTED until change-scope"
    ( cd "$CURRENT" && "$PY" scripts/release_control_cli.py change-scope --delegation "$DELEGATION" \
        --reason "2026-10-25 schedule: weekdays 12:00+18:00 ET, every 3h Sat 06:00 - Sun 21:00" --dry-run )
    ( cd "$CURRENT" && "$PY" scripts/release_control_cli.py change-scope --delegation "$DELEGATION" \
        --reason "2026-10-25 schedule: weekdays 12:00+18:00 ET, every 3h Sat 06:00 - Sun 21:00" )
    ( cd "$CURRENT" && "$PY" scripts/release_control_cli.py status )
    ;;
  *) echo "usage: $0 [--preview|--apply]"; exit 2 ;;
esac
