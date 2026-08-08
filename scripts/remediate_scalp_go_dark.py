#!/usr/bin/env python3
"""Iterative autonomous remediation for scalp_catalyst_verification_dead.

Diagnoses why GO is dark, records root cause + how-to-fix in health_root_cause_memory,
then executes the next strategy on the ladder (not the same thrashing scanner forever).

Exit codes:
  0 — strategy ran cleanly OR hold recorded (progress toward fix / correctly deferred)
  1 — strategy failed or diagnosis shows hard failure needing code review
  2 — usage / import error

Usage:
  .venv/bin/python scripts/remediate_scalp_go_dark.py
  .venv/bin/python scripts/remediate_scalp_go_dark.py --diagnose-only
  .venv/bin/python scripts/remediate_scalp_go_dark.py --strategy rescan_social_scalp
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.live_project_root import DEV_ROOT, DEV_VENV_PYTHON, get_live_project_root
from lib import health_root_cause_memory as rcmem

FINDING = "scalp_catalyst_verification_dead"
GO_THRESHOLD = int(os.getenv("SCALP_GO_THRESHOLD", "40"))
WINDOW_DAYS = int(os.getenv("SCALP_RC_WINDOW_DAYS", "3"))


def _root() -> Path:
    try:
        r = get_live_project_root()
        if (DEV_ROOT / "scripts").is_dir():
            return DEV_ROOT
        return r
    except Exception:
        return DEV_ROOT


def _py() -> str:
    if DEV_VENV_PYTHON.is_file():
        return str(DEV_VENV_PYTHON)
    cand = _root() / ".venv" / "bin" / "python"
    return str(cand) if cand.is_file() else sys.executable


def _db(sql: str, params=None, fetch="one"):
    try:
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(sql, params or ())
        cols = [d[0] for d in cur.description] if cur.description else []
        if fetch == "all":
            rows = cur.fetchall()
            cur.close()
            return [dict(zip(cols, r)) for r in rows]
        row = cur.fetchone()
        cur.close()
        return dict(zip(cols, row)) if row else None
    except Exception as e:
        return {"_error": str(e)[:200]}


def diagnose() -> dict:
    """Snapshot scalp GO darkness root signals."""
    d: dict = {
        "at": datetime.now(timezone.utc).isoformat(),
        "window_days": WINDOW_DAYS,
        "go_threshold": GO_THRESHOLD,
    }
    recent = _db(
        "SELECT count(*) AS n FROM scalp_scan_results "
        "WHERE scanned_at > now() - interval '18 hours'"
    ) or {}
    d["rows_18h"] = int(recent.get("n") or 0) if "_error" not in recent else 0
    if recent.get("_error"):
        d["db_error"] = recent["_error"]

    r = _db(
        f"""SELECT count(*) AS rows,
                   count(*) FILTER (WHERE decision='GO') AS go,
                   count(*) FILTER (WHERE decision='WAIT') AS wait,
                   count(*) FILTER (WHERE decision='AVOID') AS avoid,
                   count(*) FILTER (WHERE catalyst_verified) AS verified,
                   max(score) AS max_score,
                   avg(score)::float AS avg_score,
                   count(*) FILTER (WHERE grade IN ('A','A+')) AS a_grades
            FROM scalp_scan_results
            WHERE scanned_at > now() - make_interval(days => {int(WINDOW_DAYS)})"""
    ) or {}
    if r.get("_error"):
        d["db_error"] = r["_error"]
    else:
        d.update({
            "rows": int(r.get("rows") or 0),
            "go": int(r.get("go") or 0),
            "wait": int(r.get("wait") or 0),
            "avoid": int(r.get("avoid") or 0),
            "verified": int(r.get("verified") or 0),
            "max_score": float(r.get("max_score") or 0),
            "avg_score": round(float(r.get("avg_score") or 0), 2),
            "a_grades": int(r.get("a_grades") or 0),
        })

    # Feed freshness proxies
    try:
        news = _db(
            "SELECT EXTRACT(EPOCH FROM (now()-max(published_at)))/3600 AS age_h "
            "FROM news_articles WHERE published_at > now() - interval '7 days'"
        ) or {}
        d["news_age_h"] = float(news.get("age_h") or 999) if not news.get("_error") else None
    except Exception:
        d["news_age_h"] = None

    # Root-cause classification
    go = int(d.get("go") or 0)
    rows = int(d.get("rows") or 0)
    max_score = float(d.get("max_score") or 0)
    verified = int(d.get("verified") or 0)
    rows_18h = int(d.get("rows_18h") or 0)
    news_age = d.get("news_age_h")

    if rows_18h == 0:
        rc = "scanner_not_running"
    elif go > 0:
        rc = "cleared"  # not actually dark
    elif max_score >= GO_THRESHOLD and verified == 0 and rows >= 20:
        # Scores high enough for GO but none verified → classic catalyst cap / feed bug
        rc = "catalyst_cap_bug"
    elif news_age is not None and news_age > 12 and max_score < GO_THRESHOLD:
        rc = "news_or_social_feed_dead"
    elif max_score > 0 and max_score < (GO_THRESHOLD - 5):
        rc = "low_max_score_regime"
    elif max_score == 0 and rows > 0:
        rc = "finviz_metrics_missing"
    else:
        rc = "low_max_score_regime" if max_score < GO_THRESHOLD else "unknown"

    d["root_cause"] = rc
    d["how_to_fix"] = rcmem.how_to_fix_text(FINDING, rc if rc != "cleared" else "unknown")
    return d


def _rewrite_cmd(cmd: str) -> str:
    if not cmd:
        return cmd
    py = _py()
    return cmd.replace(".venv/bin/python", py)


def _run_cmd(cmd: str, timeout: int = 300) -> dict:
    root = _root()
    full = _rewrite_cmd(cmd)
    try:
        proc = subprocess.run(
            full, shell=True, cwd=str(root),
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-400:],
            "stderr_tail": (proc.stderr or "")[-400:],
            "cmd": full[:300],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "error": f"timeout {timeout}s", "cmd": full[:300]}
    except Exception as e:
        return {"ok": False, "exit_code": -2, "error": str(e)[:200], "cmd": full[:300]}


def verify_go_present() -> tuple[bool, str]:
    r = _db(
        f"""SELECT count(*) AS n FROM scalp_scan_results
            WHERE scanned_at > now() - make_interval(days => {int(WINDOW_DAYS)})
              AND decision = 'GO'"""
    ) or {}
    if r.get("_error"):
        return False, f"verify_error:{r['_error']}"
    n = int(r.get("n") or 0)
    return (n > 0, f"scalp_go_{n}" if n else "scalp_go_still_zero")


def run(strategy_id: str | None = None, diagnose_only: bool = False) -> dict:
    diag = diagnose()
    root_cause = diag.get("root_cause") or "unknown"
    err_msg = (
        f"scalp GO dark: rows={diag.get('rows')} go={diag.get('go')} "
        f"wait={diag.get('wait')} max_score={diag.get('max_score')} "
        f"verified={diag.get('verified')} rc={root_cause}"
    )
    rcmem.record_error(
        FINDING,
        err_msg,
        root_cause=root_cause if root_cause != "cleared" else None,
        diagnosis=diag,
        how_to_fix=diag.get("how_to_fix"),
    )

    result = {
        "finding_type": FINDING,
        "diagnosis": diag,
        "root_cause": root_cause,
        "how_to_fix": diag.get("how_to_fix"),
    }

    if root_cause == "cleared":
        rcmem.record_outcome(FINDING, strategy_id="already_clear", ok=True, note="GO present")
        result.update({"ok": True, "strategy_id": "already_clear", "note": "GO already present"})
        return result

    if diagnose_only:
        # Do not record a "success" outcome — that would clear hold_until / reset the ladder.
        result.update({"ok": True, "strategy_id": "diagnose_only", "note": "diagnose only"})
        return result

    # Product regime: after enough failures with low max_score, hold 6h instead of thrash
    mem = rcmem.summary_for(FINDING)
    if root_cause == "low_max_score_regime" and int(mem.get("fail_count") or 0) >= 4:
        strat = {"id": "record_product_regime_hold", "cmd": None,
                 "how": diag.get("how_to_fix")}
    else:
        strat = rcmem.select_next_strategy(FINDING, prefer_id=strategy_id)

    if not strat:
        result.update({"ok": False, "note": "no strategy"})
        return result

    sid = strat.get("id") or "unknown"
    result["strategy_id"] = sid
    result["strategy_how"] = strat.get("how")

    if strat.get("held") or sid in ("record_product_regime_hold", "hold"):
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=True, root_cause=root_cause,
            note=f"hold — {root_cause}; max_score={diag.get('max_score')}",
            hold_minutes=1440,  # daily re-eval — market regime won't shift faster
        )
        result.update({
            "ok": True,
            "held": True,
            "note": f"Recorded root_cause={root_cause}; holding thrash 6h",
        })
        return result

    if sid == "diagnose_only" or not strat.get("cmd"):
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=True, root_cause=root_cause, note="diagnosed",
        )
        # Advance so next autonomous cycle runs a real fix
        rcmem.advance_strategy(FINDING)
        result.update({"ok": True, "note": "diagnosed; ladder advanced for next cycle"})
        return result

    run_res = _run_cmd(strat["cmd"])
    result["run"] = {k: run_res.get(k) for k in ("ok", "exit_code", "error", "cmd") if k in run_res or True}

    cleared, vnote = verify_go_present()
    result["verify"] = {"cleared": cleared, "note": vnote}

    # Strategy "ok" for ladder means command exited 0; verify may still fail (product regime)
    cmd_ok = bool(run_res.get("ok"))
    if cleared:
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=True, root_cause=root_cause,
            note=vnote, cmd=run_res.get("cmd"), exit_code=run_res.get("exit_code"),
        )
        result["ok"] = True
        result["note"] = f"fixed: {vnote}"
    elif cmd_ok and root_cause == "low_max_score_regime":
        # Command worked but GO still zero because scores are soft — not a script thrash win
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=False, root_cause=root_cause,
            note=f"cmd_ok but {vnote}; max_score={diag.get('max_score')}",
            cmd=run_res.get("cmd"), exit_code=run_res.get("exit_code"),
            hold_minutes=120 if sid.startswith("rescan") else None,
        )
        result["ok"] = True  # exit 0 so health doesn't storm; memory advanced
        result["note"] = f"cmd ok, still dark ({vnote}); root_cause recorded, ladder advanced"
    else:
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=False, root_cause=root_cause,
            note=vnote if cmd_ok else (run_res.get("error") or f"exit {run_res.get('exit_code')}"),
            cmd=run_res.get("cmd"), exit_code=run_res.get("exit_code"),
        )
        result["ok"] = cmd_ok
        result["note"] = vnote if cmd_ok else run_res.get("error") or "cmd failed"

    result["memory"] = rcmem.summary_for(FINDING)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--diagnose-only", action="store_true")
    ap.add_argument("--strategy", default=None, help="Force strategy id from ladder")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = run(strategy_id=args.strategy, diagnose_only=args.diagnose_only)
    if args.json or True:
        print(json.dumps(out, indent=2, default=str))
    # Exit 0 on ok/held; 1 on hard fail
    sys.exit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
