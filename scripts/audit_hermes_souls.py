#!/usr/bin/env python3
"""audit_hermes_souls.py — audit all Hermes SOUL/persona files (Phase 208C). Read-only, no secrets.
Output: data/hermes/hermes_soul_audit_latest.json"""
import json, hashlib, glob
from pathlib import Path

HOME = Path.home()
HERMES_HOME = HOME / ".hermes"
SIDECAR = Path(__file__).resolve().parent.parent / "hermes_sidecar"

UNSAFE_ENABLE = ["execute trades", "place orders", "modify stops", "approve proposals",
                 "use tools to execute actions", "autonomous trading", "enable live trading", "submit order"]
RETIRED_REFS = ["hermes_sidecar/.hermes", "hermes_sidecar/install", "run_hermes_gateway", "install/.venv/bin/hermes"]
NEGATIONS = ("do not", "does not", "never", "cannot", "won't", "will not", "n't", "no ")


def collect():
    files = []
    # active
    p = HERMES_HOME / "SOUL.md"
    if p.exists():
        files.append(("default", p, True))
    for d in sorted(glob.glob(str(HERMES_HOME / "profiles/*/SOUL.md"))):
        files.append((Path(d).parent.name, Path(d), True))
    # retired
    for d in sorted(glob.glob(str(SIDECAR / ".hermes.RETIRED_*/**/SOUL.md"), recursive=True)) + \
             sorted(glob.glob(str(SIDECAR / ".hermes.RETIRED_*/SOUL.md"))):
        files.append((f"retired:{Path(d).parent.name}", Path(d), False))
    return files


def negated(low, phrase):
    i = 0
    while True:
        j = low.find(phrase, i)
        if j < 0:
            return True  # all occurrences (if any) checked; default safe when none left
        seg_start = max(low.rfind(".", 0, j), low.rfind("\n", 0, j), low.rfind(";", 0, j), low.rfind(":", 0, j))
        if not any(n in low[seg_start + 1:j] for n in NEGATIONS):
            return False
        i = j + len(phrase)


def main():
    rows, hashes = [], {}
    for owner, path, active in collect():
        txt = path.read_text(errors="ignore")
        low = txt.lower()
        h = hashlib.sha256(txt.encode()).hexdigest()[:16]
        hashes.setdefault(h, []).append(owner)
        unsafe = [ph for ph in UNSAFE_ENABLE if ph in low and not negated(low, ph)]
        retired = [r for r in RETIRED_REFS if r.lower() in low]
        rows.append({
            "owner": owner, "path": str(path).replace(str(HOME), "~"), "active": active,
            "hash": h, "mtime": int(path.stat().st_mtime), "bytes": len(txt),
            "unsafe_tool_enablement": unsafe,
            "instructs_live_trading": any(p in low for p in ("enable live trading", "execute trades", "submit order")) and bool(unsafe),
            "references_retired_paths": retired,
            "first_line": (txt.splitlines() or [""])[0][:120],
        })
    dup = {h: o for h, o in hashes.items() if len(o) > 1}
    active_rows = [r for r in rows if r["active"]]
    out = {
        "generated_note": "Phase 208C read-only SOUL audit",
        "active_soul_count": len(active_rows),
        "retired_soul_count": len([r for r in rows if not r["active"]]),
        "duplicate_soul_hashes": dup,
        "active_souls_safe": all(not r["unsafe_tool_enablement"] and not r["instructs_live_trading"] for r in active_rows),
        "any_active_references_retired": any(r["references_retired_paths"] for r in active_rows),
        "any_active_enables_live_trading": any(r["instructs_live_trading"] for r in active_rows),
        "any_active_enables_broker_mutation": any(r["unsafe_tool_enablement"] for r in active_rows),
        "souls": rows,
    }
    Path("data/hermes").mkdir(parents=True, exist_ok=True)
    Path("data/hermes/hermes_soul_audit_latest.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({k: out[k] for k in ("active_soul_count", "retired_soul_count", "duplicate_soul_hashes",
          "active_souls_safe", "any_active_references_retired", "any_active_enables_live_trading",
          "any_active_enables_broker_mutation")}, indent=2))
    print("active souls:", [(r["owner"], r["hash"], r["unsafe_tool_enablement"]) for r in active_rows])


if __name__ == "__main__":
    main()
