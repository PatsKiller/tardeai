#!/usr/bin/env python3
"""check_hermes_update_available.py — READ-ONLY check for a newer Hermes build.

Never upgrades. If a newer hermes-agent version is published than the one installed, it records a runtime
flag and recommends re-testing Codex headless (Phase 213). No alert storm when nothing is new. Optional
WEEKLY schedule only (not enabled unless the operator approves).

  python3 scripts/check_hermes_update_available.py            # check + update runtime status quietly
"""
import argparse, json, re, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
VENV_PY = Path.home() / ".local" / "share" / "hermes-agent-venv" / "bin" / "python"
OUT = ROOT / "data" / "runtime" / "hermes_update_status.json"
CAP = ROOT / "data" / "runtime" / "hermes_llm_capabilities.json"


def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def installed_version():
    try:
        out = subprocess.run([str(VENV_PY), "-m", "pip", "show", "hermes-agent"],
                             capture_output=True, text=True, timeout=20).stdout
        m = re.search(r"^Version:\s*(.+)$", out, re.M)
        return m.group(1).strip() if m else None
    except Exception:
        return None


def available_versions():
    try:
        out = subprocess.run([str(VENV_PY), "-m", "pip", "index", "versions", "hermes-agent"],
                             capture_output=True, text=True, timeout=40).stdout
        m = re.search(r"Available versions:\s*(.+)", out)
        return [v.strip() for v in m.group(1).split(",")] if m else []
    except Exception:
        return []


def _check():
    """Return failure when version evidence cannot be measured."""
    return _run_check()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.dry_run:
        print("DRY-RUN hermes-update-check: would inspect installed/published Hermes versions and update status; no subprocess, network or writes")
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        rc = _check()
    except Exception as exc:
        write_lane_receipt("hermes-update-check", ok=False, exit_code=1, started_at=started,
                           script="check_hermes_update_available.py", error=type(exc).__name__)
        raise
    write_lane_receipt("hermes-update-check", ok=rc == 0, exit_code=rc, started_at=started,
                       script="check_hermes_update_available.py", summary={"versions_measured": rc == 0})
    return rc


def _run_check():
    inst = installed_version()
    avail = available_versions()
    measured = bool(inst and avail)
    newer = [v for v in avail if inst and _ver_tuple(v) > _ver_tuple(inst)]
    status = {"checked_at": datetime.now().isoformat(), "installed": inst, "available": avail,
              "newer_available": bool(newer), "newer_versions": newer,
              "codex_headless_retest_recommended": bool(newer),
              "status": "ok" if measured else "not_measured",
              "note": ("Version evidence unavailable; update readiness is NOT_MEASURED." if not measured else
                       "Newer Hermes published — re-run PHASE212E to re-test Codex headless; do NOT auto-upgrade."
                       if newer else "Hermes is up to date (no newer build); no action.")}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(status, indent=2))
    # if newer, flag the chatgpt capability for retest (quietly; never auto-upgrade)
    if newer:
        try:
            cap = json.loads(CAP.read_text())
            cap.setdefault("lanes", {}).setdefault("chatgpt", {})["retest_recommended"] = True
            cap["lanes"]["chatgpt"]["newer_hermes_available"] = newer
            CAP.write_text(json.dumps(cap, indent=2))
        except Exception:
            pass
    print(json.dumps(status, indent=2))
    return 0 if measured else 1


if __name__ == "__main__":
    sys.exit(main())
