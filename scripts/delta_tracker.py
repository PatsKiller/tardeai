"""delta_tracker.py — Persistent delta tracking between runs.

State file: data/state.json
Tracks per-ticker:
  - first_seen_date
  - first_criteria_met (list of criteria names first satisfied)
  - score_history      (list of {run_label, score, grade, decision} dicts)
  - rvol_peak          (highest RVOL observed)
  - catalyst_fingerprints (set of seen catalyst fingerprints to detect new ones)
  - last_run_label
  - last_score / last_grade / last_decision

Delta events generated per run:
  - NEW_TICKER          : ticker seen for the first time
  - NEW_CATALYST        : catalyst not seen in any previous run
  - GRADE_UP / GRADE_DOWN : score changed by >= threshold
  - RVOL_THRESHOLD_CROSS: RVOL crossed a configured threshold (2, 3, 5, 8)
  - NEW_CRITERIA_MET    : additional criteria satisfied vs. first sighting
  - TICKER_FADED        : was in previous run, not in this one
"""
from __future__ import annotations
import hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _fingerprint(title: str) -> str:
    words = title.lower().split()[:10]
    return hashlib.md5(" ".join(words).encode()).hexdigest()

def _grade_order(grade: str) -> int:
    return {"A_plus": 5, "A": 4, "B": 3, "C": 2, "D": 1}.get(grade, 0)

RVOL_THRESHOLDS = [2.0, 3.0, 5.0, 8.0]
GRADE_CHANGE_THRESHOLD = 5  # score must shift >= 5 pts to log grade event


# ── State I/O ─────────────────────────────────────────────────────────────────

def _state_path(project_root: str) -> Path:
    raw = os.getenv("STATE_FILE", "data/state.json")
    return Path(project_root) / raw

def load_state(project_root: str = ".") -> Dict[str, Any]:
    path = _state_path(project_root)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_state(state: Dict[str, Any], project_root: str = ".") -> None:
    path = _state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    # Postgres dual-write (non-blocking, JSON already saved above)
    try:
        from db_adapter import save_state as _db_save_state, USE_DB
        if USE_DB:
            _db_save_state(state, path)
    except Exception as e:
        print(f"  [state] Postgres write failed (JSON saved OK): {e}")


# ── Delta computation ─────────────────────────────────────────────────────────

def compute_delta(
    scored_tickers: List[Dict[str, Any]],
    date_str: str,
    run_label: str,
    project_root: str = ".",
) -> Dict[str, Any]:
    """Compare current run to stored state.

    Returns:
      {
        "events":       list of delta event dicts,
        "new_tickers":  list of symbols new this run,
        "faded":        list of symbols that were in last run but not this one,
        "go_tickers":   list of symbols with decision == "GO",
        "updated_state": the new state dict (call save_state to persist)
      }
    """
    state = load_state(project_root)
    current_symbols: Set[str] = {t["symbol"] for t in scored_tickers}

    # Which symbols were in the last full state entry
    previously_active = set(state.get("_active_symbols", []))

    events: List[Dict[str, Any]] = []
    new_tickers: List[str] = []
    go_tickers: List[str] = []

    for ticker in scored_tickers:
        sym = ticker["symbol"]
        score = ticker["score"]
        grade = ticker["grade"]
        decision = ticker["decision"]
        rvol = ticker.get("relative_volume", 0) or 0
        criteria: Dict[str, bool] = ticker.get("criteria", {})
        catalysts: List[Dict] = ticker.get("catalysts", [])
        new_fps: Set[str] = {_fingerprint(c.get("title", "")) for c in catalysts if c.get("title")}

        if decision == "GO":
            go_tickers.append(sym)

        prev = state.get(sym, {})

        if not prev:
            # Brand-new ticker
            new_tickers.append(sym)
            events.append({
                "event": "NEW_TICKER",
                "symbol": sym,
                "score": score,
                "grade": grade,
                "decision": decision,
                "rvol": rvol,
                "timestamp": _now_str(),
                "run_label": run_label,
            })
            # Initialise state entry
            state[sym] = {
                "first_seen_date": date_str,
                "first_seen_run": run_label,
                "first_criteria_met": [k for k, v in criteria.items() if v],
                "score_history": [{
                    "date": date_str, "run_label": run_label,
                    "score": score, "grade": grade, "decision": decision,
                }],
                "rvol_peak": rvol,
                "catalyst_fingerprints": list(new_fps),
                "last_run_label": run_label,
                "last_score": score,
                "last_grade": grade,
                "last_decision": decision,
                "consecutive_go_days": 1 if decision == "GO" else 0,
                "last_go_date": date_str if decision == "GO" else None,
            }
        else:
            # Returning ticker — check for delta events
            last_score = prev.get("last_score", 0)
            last_grade = prev.get("last_grade", "D")
            prev_fps: Set[str] = set(prev.get("catalyst_fingerprints", []))
            prev_criteria: List[str] = prev.get("first_criteria_met", [])
            rvol_peak: float = prev.get("rvol_peak", 0)

            # Grade / score change
            score_diff = score - last_score
            if abs(score_diff) >= GRADE_CHANGE_THRESHOLD:
                event_type = "GRADE_UP" if score_diff > 0 else "GRADE_DOWN"
                events.append({
                    "event": event_type,
                    "symbol": sym,
                    "score": score,
                    "prev_score": last_score,
                    "score_delta": score_diff,
                    "grade": grade,
                    "prev_grade": last_grade,
                    "timestamp": _now_str(),
                    "run_label": run_label,
                })

            # New catalysts
            truly_new_fps = new_fps - prev_fps
            if truly_new_fps:
                new_catalyst_titles = [
                    c.get("title", "") for c in catalysts
                    if _fingerprint(c.get("title", "")) in truly_new_fps
                ]
                events.append({
                    "event": "NEW_CATALYST",
                    "symbol": sym,
                    "count": len(truly_new_fps),
                    "titles": new_catalyst_titles,
                    "timestamp": _now_str(),
                    "run_label": run_label,
                })

            # RVOL threshold crossings
            for threshold in RVOL_THRESHOLDS:
                if rvol >= threshold > rvol_peak:
                    events.append({
                        "event": "RVOL_THRESHOLD_CROSS",
                        "symbol": sym,
                        "threshold": threshold,
                        "rvol": rvol,
                        "timestamp": _now_str(),
                        "run_label": run_label,
                    })

            # New criteria met
            now_met = {k for k, v in criteria.items() if v}
            prev_met = set(prev_criteria)
            newly_met = now_met - prev_met
            if newly_met:
                events.append({
                    "event": "NEW_CRITERIA_MET",
                    "symbol": sym,
                    "new_criteria": list(newly_met),
                    "total_met": len(now_met),
                    "timestamp": _now_str(),
                    "run_label": run_label,
                })

            # Update state entry
            history = prev.get("score_history", [])
            history.append({
                "date": date_str, "run_label": run_label,
                "score": score, "grade": grade, "decision": decision,
            })
            # --- consecutive GO days tracking (v12) ---
            prev_go_date    = prev.get("last_go_date")
            prev_go_days    = prev.get("consecutive_go_days", 0)
            from datetime import datetime, timedelta
            if decision == "GO":
                if prev_go_date == date_str:
                    # Same day, different run — keep count unchanged
                    consec_days = prev_go_days
                else:
                    # Check if yesterday was also a GO day
                    try:
                        yesterday = (datetime.fromisoformat(date_str) - timedelta(days=1)).strftime("%Y-%m-%d")
                        consec_days = prev_go_days + 1 if prev_go_date == yesterday else 1
                    except Exception:
                        consec_days = 1
                last_go_date = date_str
            else:
                consec_days  = 0
                last_go_date = prev_go_date
            state[sym] = {
                **prev,
                "score_history": history[-20:],  # keep last 20 run snapshots
                "rvol_peak": max(rvol_peak, rvol),
                "catalyst_fingerprints": list(prev_fps | new_fps),
                "last_run_label": run_label,
                "last_score": score,
                "last_grade": grade,
                "last_decision": decision,
                "first_criteria_met": list(prev_met | now_met),  # accumulate
                "consecutive_go_days": consec_days,
                "last_go_date": last_go_date,
            }

    # Faded tickers — were active last run, not in this one
    faded: List[str] = sorted(previously_active - current_symbols)
    for sym in faded:
        events.append({
            "event": "TICKER_FADED",
            "symbol": sym,
            "last_score": state.get(sym, {}).get("last_score", 0),
            "timestamp": _now_str(),
            "run_label": run_label,
        })

    # Inject consecutive_go_days back onto scored tickers
    for t in scored_tickers:
        sym = t["symbol"]
        t["consecutive_go_days"] = state.get(sym, {}).get("consecutive_go_days", 0)

    # Update the active symbol registry
    state["_active_symbols"] = sorted(current_symbols)
    state["_last_run"] = {"date": date_str, "run_label": run_label, "timestamp": _now_str()}

    return {
        "events":        events,
        "new_tickers":   new_tickers,
        "faded":         faded,
        "go_tickers":    go_tickers,
        "updated_state": state,
    }
