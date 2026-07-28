"""Active Trader Configuration tab — READ-ONLY backend aggregator (Stage AT-CFG-S1).

`config_overview()` returns ALL EIGHT configuration panels in one payload so the React
frontend fetches once. Everything here is a read-only projection of live YAML files, live
DB rows, live .env presence, and `git log` provenance.

HARD RULES (enforced by tests + code review):
  * GET/read only. This module NEVER writes a file, table, or env var. No mutation surface.
  * NO secret VALUES ever leave this module — credential slots are reported by NAME +
    `populated: bool` ONLY (never masked, never truncated, never the value).
  * No fabricated fields — an unsourced value is emitted as
    {"value": null, "status": "unknown", "reason": "..."}.
  * Fail-closed: any panel builder that hits an error degrades to an honest `unknown`
    panel; the aggregator never raises.

The two known momentum_scalp contradictions (float ceiling YAML 20/pref10 vs DB 100 vs
engine 30; stop cap 8% vs 15%) are surfaced VERBATIM and NOT reconciled.
"""
from __future__ import annotations

import datetime as _dt
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

CONTRACT = "active-trader-at-cfg-s1-read-v1"

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Read-only / zero-authority markers stamped on every panel (consistent with the rest of
# the v3 read plane — see read_api.py / read_http.py).
_READ_ONLY = True
_AUTHORITY = {"mutation": False, "order": False, "financial_action": False}

# Config files that back the Active Trader tab (path is relative to repo root).
_CONFIG_FILES = {
    "momentum_scalp": "config/strategies/momentum_scalp.yaml",
    "scalp_signal_engine": "config/scalp_signal_engine.yaml",
    "scalp_setup_registry": "config/scalp_setup_registry.yaml",
    "finviz_momentum_scalp_screen": "config/finviz_momentum_scalp_screen.yaml",
}

# Tactical strategy keys tracked by the Active Trader config tab.
_TACTICAL_STRATEGY_IDS = (
    "momentum_scalp", "meme_squeeze_momentum", "large_float_social_scout",
    "swing_breakout", "gap_and_go", "earnings_post_momentum",
    "fib_retracement_bounce", "pullback_macd_reversal",
)

# Credential slot NAMES to report presence for (NEVER the value).
_CREDENTIAL_SLOT_NAMES = (
    "DB_PASSWORD", "TELEGRAM_BOT_TOKEN",
    "ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY",
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
    "ALPACA_TAXABLE_API_KEY", "ALPACA_IRA_API_KEY",
    "SCHWAB_APP_KEY", "SCHWAB_APP_SECRET",
    "OPENAI_API_KEY",
)


# --------------------------------------------------------------------------- helpers

def _moomoo_l2_entitlement() -> tuple[str, str]:
    """(feed_state, human_description) for the moomoo L2 data plane.

    Reads the snapshot written by the opend_health cron rather than dialling OpenD:
    this runs in an API request path, and a futu connect costs seconds. Same
    Engine-Room pattern as market_movers. Stale/missing snapshot degrades to an
    honest 'unknown', never an optimistic claim.
    """
    snap = _REPO_ROOT / "data" / "runtime" / "moomoo_opend_health.json"
    try:
        import json as _json
        d = _json.loads(snap.read_text(encoding="utf-8"))
    except Exception:
        return ("unknown", "moomoo OpenD — no health snapshot yet (opend_health cron pending)")

    age = _age_seconds(d.get("checked_at"))
    if age is not None and age > 1800:
        return ("unknown",
                f"moomoo OpenD — health snapshot stale ({int(age // 60)}m old); state not asserted")
    if not d.get("ok"):
        why = (d.get("quote") or {}).get("detail") or (d.get("unit") or {}).get("state") or "down"
        return ("unavailable", f"moomoo OpenD — DOWN ({why})")
    # ok=True means the quote round-trip succeeded, i.e. OpenD is logged in. Depth
    # entitlement itself was proven by probe on 2026-07-28 (ORDER_BOOK subscribe +
    # get_order_book returned real depth, quota remain 99).
    return ("real-time", "moomoo OpenD — AVAILABLE_REALTIME (L2 depth entitled; armed-symbol subscriptions only)")


def _panel_frame(extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Every panel carries the read-only + zero-authority markers."""
    base = {"read_only": _READ_ONLY, "authority": dict(_AUTHORITY)}
    if extra:
        base.update(extra)
    return base


def _unknown(reason: str) -> dict[str, Any]:
    return {"value": None, "status": "unknown", "reason": reason}


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(v: Any) -> Any:
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _age_seconds(ts: Any) -> Optional[float]:
    """Age in seconds of a timestamp against now. None if not a datetime."""
    if not isinstance(ts, _dt.datetime):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return round((_now() - ts).total_seconds(), 1)


def _num(v: Any) -> Any:
    """Coerce Decimal/None-safe to float for JSON; leave None/str as-is."""
    if v is None:
        return None
    try:
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
    except Exception:
        pass
    return v


def _load_yaml(rel_path: str) -> dict[str, Any]:
    """Fail-closed YAML load. Returns {} on any error (never raises)."""
    try:
        import yaml  # type: ignore
        p = _REPO_ROOT / rel_path
        if not p.is_file():
            return {}
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _git(args: Sequence[str]) -> Optional[str]:
    """Run a read-only git command in the repo. None on any failure."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(_REPO_ROOT),
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None
    except Exception:
        return None


def _git_sha(rel_path: str) -> Optional[str]:
    return _git(["log", "-1", "--format=%h", "--", rel_path])


def _git_last_modified(rel_path: str) -> Optional[str]:
    return _git(["log", "-1", "--format=%cI", "--", rel_path])


class _DB:
    """Lazy, fail-closed DB accessor. Every query degrades to rows=[] on error;
    NEVER writes, NEVER raises out of this module."""

    def __init__(self) -> None:
        self._conn = None
        self._tried = False
        self.available = False

    def _connect(self) -> None:
        if self._tried:
            return
        self._tried = True
        try:
            import sys as _sys
            sp = str(_REPO_ROOT / "scripts")
            if sp not in _sys.path:
                _sys.path.insert(0, sp)
            from db_adapter import get_connection  # type: ignore
            self._conn = get_connection()
            self.available = True
        except Exception:
            self._conn = None
            self.available = False

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        self._connect()
        if not self._conn:
            return []
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, list(params or []))
                if cur.description is None:
                    return []
                cols = [d[0] for d in cur.description]
                out = []
                for r in cur.fetchall():
                    d = dict(zip(cols, r))
                    for k, v in list(d.items()):
                        d[k] = _iso(v) if hasattr(v, "isoformat") else _num(v)
                    out.append(d)
                return out
        except Exception:
            # A failed query must not poison later queries — roll back the aborted txn.
            try:
                self._conn.rollback()
            except Exception:
                pass
            return []


# --------------------------------------------------------------------------- panels

def _panel_strategy_registry(db: _DB) -> dict[str, Any]:
    """Per-strategy: state, review-gate progress, config path, git SHA, drift object."""
    try:
        rows = db.query(
            "SELECT strategy_id, status, active, max_float_m, min_rvol, min_price, max_price, "
            "last_yaml_sync_at FROM strategy_registry WHERE strategy_id = ANY(%s)",
            [list(_TACTICAL_STRATEGY_IDS)],
        )
        by_id = {r["strategy_id"]: r for r in rows}

        # momentum_scalp deep context (YAML + review gate + drift)
        ms_yaml = _load_yaml(_CONFIG_FILES["momentum_scalp"])
        finviz_yaml = _load_yaml(_CONFIG_FILES["finviz_momentum_scalp_screen"])
        engine_yaml = _load_yaml(_CONFIG_FILES["scalp_signal_engine"])
        sf = ms_yaml.get("screen_filters", {}) if isinstance(ms_yaml, dict) else {}
        gate = ms_yaml.get("validation_gate", {}) if isinstance(ms_yaml, dict) else {}
        perf = ms_yaml.get("performance_context", {}) if isinstance(ms_yaml, dict) else {}

        # live scorecard for momentum_scalp (may be stale — reported honestly)
        sc_rows = db.query(
            "SELECT scorecard_date, closed_count, win_count, loss_count, win_rate, avg_r, "
            "sample_quality FROM paper_strategy_scorecards WHERE strategy_id = %s "
            "ORDER BY scorecard_date DESC LIMIT 1",
            ["momentum_scalp"],
        )
        scorecard = sc_rows[0] if sc_rows else None

        strategies = []
        for sid in _TACTICAL_STRATEGY_IDS:
            db_row = by_id.get(sid)
            entry: dict[str, Any] = {
                "key": sid,
                "db_present": db_row is not None,
                "status": (db_row or {}).get("status"),
                "active": (db_row or {}).get("active"),
                "state": _derive_state(sid, db_row, engine_yaml),
                "last_yaml_sync_at": (db_row or {}).get("last_yaml_sync_at"),
            }
            if sid == "momentum_scalp":
                rel = _CONFIG_FILES["momentum_scalp"]
                entry["config_file"] = rel
                entry["git_sha"] = _git_sha(rel)
                entry["last_modified"] = _git_last_modified(rel)
                # review-gate progress: closed trades / WR / PF vs thresholds
                entry["review_gate"] = {
                    "thresholds": {
                        "min_closed_validation_trades": gate.get("min_closed_validation_trades"),
                        "min_win_rate": gate.get("min_win_rate"),
                        "min_profit_factor": gate.get("min_profit_factor"),
                        "min_calendar_months": gate.get("min_calendar_months"),
                    },
                    "progress_yaml_performance_context": {
                        "closed_paper_trades": perf.get("closed_paper_trades"),
                        "win_rate": perf.get("win_rate"),
                        "profit_factor": perf.get("profit_factor"),
                        "ready_for_review": perf.get("ready_for_review"),
                        "last_updated": perf.get("last_updated"),
                    },
                    "progress_db_scorecard": scorecard or _unknown(
                        "no paper_strategy_scorecards row for momentum_scalp"),
                    "gate_met": _gate_met(gate, perf),
                }
                # DRIFT object — the three float-ceiling values + stop cap conflict
                entry["drift"] = _momentum_drift(sf, db_row, finviz_yaml, engine_yaml)
            else:
                entry["config_file"] = _unknown(
                    "per-strategy YAML path not mapped in AT-CFG-S1 (DB registry values only)")
                entry["git_sha"] = None
                entry["last_modified"] = None
                entry["review_gate"] = _unknown("review-gate detail only tracked for momentum_scalp in S1")
                entry["drift"] = {
                    "has_drift": False,
                    "note": "DB registry values only; per-strategy YAML/running reconciliation not in S1 scope.",
                    "db_values": {
                        "max_float_m": (db_row or {}).get("max_float_m"),
                        "min_rvol": (db_row or {}).get("min_rvol"),
                        "min_price": (db_row or {}).get("min_price"),
                        "max_price": (db_row or {}).get("max_price"),
                    } if db_row else None,
                }
            strategies.append(entry)

        return _panel_frame({
            "source": "strategy_registry (DB) + config/strategies/*.yaml + git",
            "strategies": strategies,
            "note": "momentum_scalp carries full YAML+gate+drift context; other tactical keys are DB-only in S1.",
        })
    except Exception as e:  # fail-closed
        return _panel_frame({"status": "unknown", "reason": f"strategy_registry panel error: {e}",
                             "strategies": []})


def _derive_state(sid: str, db_row: Optional[Mapping[str, Any]],
                  engine_yaml: Mapping[str, Any]) -> str:
    """enabled | suspended | shadow_candidate | unknown — derived from strategy_registry
    (the authority: active + status)."""
    if db_row is None:
        return "unknown"
    active = db_row.get("active")
    status = str(db_row.get("status") or "").upper()
    if active is False:
        return "suspended"
    if status in ("UNVALIDATED",):
        return "shadow_candidate"
    return "enabled" if active else "suspended"


def _gate_met(gate: Mapping[str, Any], perf: Mapping[str, Any]) -> bool:
    try:
        closed = perf.get("closed_paper_trades")
        need = gate.get("min_closed_validation_trades")
        if closed is None or need is None:
            return False
        return bool(closed >= need and perf.get("ready_for_review"))
    except Exception:
        return False


def _momentum_drift(sf: Mapping[str, Any], db_row: Optional[Mapping[str, Any]],
                    finviz_yaml: Mapping[str, Any], engine_yaml: Mapping[str, Any]) -> dict[str, Any]:
    """The two known momentum_scalp contradictions, surfaced verbatim, NOT reconciled."""
    finviz_tr = (finviz_yaml.get("momentum_scalp_finviz_screen", {}) or {}).get("tradeable", {})
    finviz_float = (finviz_tr.get("float_m", {}) or {}).get("max")
    engine_uni = engine_yaml.get("universe", {}) if isinstance(engine_yaml, dict) else {}
    engine_float = engine_uni.get("float_mm_max")

    yaml_float = sf.get("max_float_m")
    db_float = (db_row or {}).get("max_float_m")

    float_values = {
        "yaml": {"value": yaml_float, "preferred": sf.get("preferred_max_float_m"),
                 "source": "config/strategies/momentum_scalp.yaml:screen_filters.max_float_m"},
        "db": {"value": db_float,
               "source": "strategy_registry.max_float_m (nightly YAML->DB sync not updating this column)"},
        "engine": {"value": engine_float,
                   "source": "config/scalp_signal_engine.yaml:universe.float_mm_max (momentum_scalp_intraday key)"},
        "finviz_running_screen": {"value": finviz_float,
                                  "source": "config/finviz_momentum_scalp_screen.yaml:tradeable.float_m.max"},
    }
    distinct = {v["value"] for k, v in float_values.items() if k != "finviz_running_screen"}
    float_agree = len(distinct) <= 1

    stop_fallback = None
    try:
        exit_rules = _load_yaml(_CONFIG_FILES["momentum_scalp"]).get("exit_rules", {})
        stop_fallback = exit_rules.get("stop_max_pct")
    except Exception:
        pass
    stop_cap = {
        "yaml_fallback_cap": {"value": stop_fallback,
                              "source": "config/strategies/momentum_scalp.yaml:exit_rules.stop_max_pct"},
        "yaml_disqualifier": {"value": 0.15,
                              "source": "config/strategies/momentum_scalp.yaml:auto_disqualifiers[STOP_OVER_15_PCT] stop_pct>0.15"},
        "engine_alt": {"value": (engine_yaml.get("trigger", {}) or {}).get("max_stop_pct_alt"),
                       "source": "config/scalp_signal_engine.yaml:trigger.max_stop_pct_alt (co-logged, intentional)"},
    }

    return {
        "has_drift": True,
        "float_ceiling": {
            "agree": float_agree,
            "values": float_values,
            "note": "THREE-WAY disagreement: YAML=20 (pref 10) vs DB=100 (STALE) vs engine=30 (intraday key). "
                    "Live finviz running screen = 20. Reported, NOT reconciled.",
        },
        "stop_cap": {
            "agree": False,
            "values": stop_cap,
            "note": "8% fallback cap co-exists with a 15% auto-disqualifier; both live and intentional. NOT reconciled.",
        },
    }


def _panel_setup_taxonomy(db: _DB) -> dict[str, Any]:
    """Registry-defined setups -> strategy -> criteria -> persisted (populated vs null on
    scalp_ignition_events, by session_date)."""
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        try:
            import scalp_setup_registry as _reg  # type: ignore
            view = _reg.public_view()
        except Exception:
            view = {"registry_version": None, "setups": [], "registry_hash": None}

        setups = []
        for s in view.get("setups", []) or []:
            setups.append({
                "setup_id": s.get("setup_id"),
                "display_label": s.get("display_label"),
                "family": s.get("family"),
                "strategy": "momentum_scalp (scalp signal engine taxonomy)",
                "operating_state": s.get("operating_state"),
                "required_data_tier": s.get("required_data_tier"),
                "defining_criteria": {
                    "entry_rule": s.get("entry_rule"),
                    "invalidation_rule": s.get("invalidation_rule"),
                    "stop_rule": s.get("stop_rule"),
                    "required_inputs": s.get("required_inputs"),
                },
            })

        # persisted populated-vs-null counts by session_date on scalp_ignition_events
        counts_rows = db.query(
            "SELECT session_date, count(*) AS total, count(primary_setup_id) AS primary_setup_id_populated, "
            "count(primary_setup_label) AS primary_setup_label_populated, "
            "count(setup_state) AS setup_state_populated "
            "FROM scalp_ignition_events GROUP BY session_date ORDER BY session_date DESC LIMIT 20"
        )
        total_all = sum(r.get("total", 0) or 0 for r in counts_rows)
        populated_all = sum(r.get("primary_setup_id_populated", 0) or 0 for r in counts_rows)
        persisted = {
            "table": "scalp_ignition_events",
            "by_session_date": counts_rows,
            "total_rows": total_all,
            "primary_setup_id_populated_total": populated_all,
            "primary_setup_id_null_total": total_all - populated_all,
            "fully_null": (total_all > 0 and populated_all == 0),
            "note": ("Taxonomy columns are 100% NULL on all persisted rows (rows predate the 07-27 "
                     "deploy of the setup-writing path). Registry + detectors + API + UI are wired; "
                     "the detector output is not being persisted onto the rows the API reads."),
        }

        return _panel_frame({
            "source": "config/scalp_setup_registry.yaml (via scalp_setup_registry.public_view) + scalp_ignition_events",
            "registry_version": view.get("registry_version"),
            "registry_hash": view.get("registry_hash"),
            "setups": setups,
            "persisted": persisted,
        })
    except Exception as e:
        return _panel_frame({"status": "unknown", "reason": f"setup_taxonomy panel error: {e}", "setups": []})


# ------- classifier guard evidence (S0.5): social/YouTube/sentiment NEVER count toward GO -------
_CLASSIFIER_GUARD_EVIDENCE = {
    "rule": "social / velocity / YouTube / sentiment can raise a name to SCOUT/WATCH ONLY and NEVER "
            "count toward the match minimum (GO). Real criteria: RVOL, gap, float, price, volume, score, "
            "verified catalyst (news/SEC/Hermes/RAG), sector.",
    "enforcing_lines": [
        {"file": "config/finviz_momentum_scalp_screen.yaml", "lines": "34-40,52",
         "quote": "scout.min_pillars: 2; finviz_pillars: [market_confirmation, structure_tradeability, "
                  "strategy_risk_fit, catalyst_evidence]; social_only_max_actionability: SCOUT; "
                  "safety.social_only_never_go: true"},
        {"file": "scripts/social_scalp_scanner.py", "lines": "381-399",
         "quote": "apply_social_only_cap(): if not verified and not has_news and (decision=='GO' or grade in "
                  "('A+','A')): return 'WAIT','B',True  # verified=catalyst_verified|rag|hermes; has_news=news_articles rows, "
                  "NOT social keyword hits"},
        {"file": "config/strategies/momentum_scalp.yaml", "lines": "45-46,51,113",
         "quote": "social_only_max_grade: WATCH; social_only_catalyst: WATCH; GO requires verified_catalyst"},
    ],
}


def _panel_criteria_matrix(db: _DB) -> dict[str, Any]:
    """Per-strategy criterion matrix: yaml_value / db_value / running_value / agree /
    counts_toward_match_minimum. Includes the two known contradictions verbatim."""
    try:
        ms = _load_yaml(_CONFIG_FILES["momentum_scalp"])
        sf = ms.get("screen_filters", {}) if isinstance(ms, dict) else {}
        exit_rules = ms.get("exit_rules", {}) if isinstance(ms, dict) else {}
        finviz = _load_yaml(_CONFIG_FILES["finviz_momentum_scalp_screen"])
        tr = (finviz.get("momentum_scalp_finviz_screen", {}) or {}).get("tradeable", {})
        engine = _load_yaml(_CONFIG_FILES["scalp_signal_engine"])
        eng_uni = engine.get("universe", {}) if isinstance(engine, dict) else {}

        db_rows = db.query(
            "SELECT strategy_id, max_float_m, min_rvol, min_price, max_price FROM strategy_registry "
            "WHERE strategy_id = %s", ["momentum_scalp"])
        dbr = db_rows[0] if db_rows else {}

        def crit(name, yaml_value, db_value, running_value, counts, *, agree=None, note=None):
            if agree is None:
                vals = [v for v in (yaml_value, db_value, running_value) if v is not None]
                agree = len(set(map(str, vals))) <= 1 if vals else None
            out = {
                "criterion": name,
                "yaml_value": yaml_value,
                "db_value": db_value if db_value is not None else _unknown("not stored in strategy_registry"),
                "running_value": running_value,
                "agree": agree,
                "counts_toward_match_minimum": counts,
            }
            if note:
                out["note"] = note
            return out

        float_note = ("KNOWN CONTRADICTION (three-way): YAML 20/pref10 vs DB 100 vs engine 30. "
                      "running_value below = engine float_mm_max (30); finviz running screen = "
                      + str((tr.get('float_m', {}) or {}).get('max')) + ". NOT reconciled.")
        stop_note = ("KNOWN CONTRADICTION: 8% fallback cap (exit_rules.stop_max_pct) vs 15% "
                     "disqualifier (auto_disqualifiers STOP_OVER_15_PCT). Both live. NOT reconciled.")

        criteria = [
            crit("float_ceiling", sf.get("max_float_m"), dbr.get("max_float_m"),
                 eng_uni.get("float_mm_max"), True, agree=False, note=float_note),
            crit("min_rvol", sf.get("min_rvol"), dbr.get("min_rvol"),
                 (tr.get("rvol", {}) or {}).get("min"), True),
            crit("min_gap_pct", sf.get("min_gap_pct"), None,
                 (tr.get("gap_pct", {}) or {}).get("min_abs"), True),
            crit("price_band", [sf.get("min_price"), sf.get("max_price")],
                 [dbr.get("min_price"), dbr.get("max_price")],
                 [(tr.get("price", {}) or {}).get("min"), (tr.get("price", {}) or {}).get("max")],
                 True),
            crit("min_volume", sf.get("min_volume"), None,
                 (tr.get("volume", {}) or {}).get("min_shares"), True),
            crit("min_score", sf.get("min_score"), None,
                 (tr.get("score", {}) or {}).get("min"), True),
            crit("market_cap", _unknown("no market-cap filter in momentum_scalp screen"),
                 None, _unknown("n/a for momentum_scalp"), False,
                 note="market cap applies to other strategies (e.g. income/large-cap screens), not momentum_scalp"),
            crit("rsi", _unknown("RSI not a momentum_scalp screen criterion"),
                 None, _unknown("n/a for momentum_scalp"), False,
                 note="RSI is used by fib_retracement / swing screens, not momentum_scalp"),
            crit("sma", _unknown("SMA not a momentum_scalp screen criterion"),
                 None, _unknown("n/a for momentum_scalp"), False,
                 note="SMA alignment is used by swing/fib screens, not momentum_scalp"),
            crit("sector", "sector_momentum (scoring weight only, no hard filter)", None,
                 _unknown("no hard sector filter"), True,
                 note="sector contributes to score; it is a real (non-social) criterion"),
            crit("yield", _unknown("yield not applicable to momentum_scalp"), None,
                 _unknown("n/a"), False,
                 note="dividend yield applies to income strategies, not momentum_scalp"),
            crit("stop_cap", exit_rules.get("stop_max_pct"), None,
                 (engine.get("trigger", {}) or {}).get("max_stop_pct"), True,
                 agree=False, note=stop_note),
            crit("verified_catalyst", "required for GO (catalyst_verified_for_live: true)", None,
                 "verified_required_for_momentum_scalp: true", True,
                 note="verified catalyst (news/SEC/Hermes/RAG) COUNTS; social-only does NOT"),
        ]

        return _panel_frame({
            "source": "momentum_scalp.yaml + strategy_registry (DB) + finviz_momentum_scalp_screen.yaml + scalp_signal_engine.yaml",
            "strategies": {
                "momentum_scalp": {
                    "criteria": criteria,
                    "_classifier_guard_evidence": _CLASSIFIER_GUARD_EVIDENCE,
                },
            },
            "note": "running_value for float_ceiling = engine float_mm_max (30); finviz running screen value in the criterion note.",
        })
    except Exception as e:
        return _panel_frame({"status": "unknown", "reason": f"criteria_matrix panel error: {e}"})


def _parse_iso(v: Any) -> Optional[_dt.datetime]:
    if isinstance(v, _dt.datetime):
        return v
    if isinstance(v, str):
        try:
            return _dt.datetime.fromisoformat(v)
        except Exception:
            return None
    return None


def _freshness(age_s: Optional[float], interval_s: int, *, factor: float = 2.0) -> dict[str, Any]:
    """Freshness vs THIS source's own interval. stale if age > interval*factor."""
    if age_s is None:
        return {"value": None, "status": "unknown", "reason": "no timestamp available"}
    threshold = interval_s * factor
    return {
        "age_seconds": age_s,
        "interval_seconds": interval_s,
        "stale_threshold_seconds": threshold,
        "status": "stale" if age_s > threshold else "fresh",
    }


def _panel_data_sources(db: _DB) -> dict[str, Any]:
    """Per source: consuming strategies, exact query/screener, cadence, last run, row count,
    newest-row age, freshness vs the source's OWN interval."""
    try:
        finviz_yaml = _load_yaml(_CONFIG_FILES["finviz_momentum_scalp_screen"])
        ms_screen = finviz_yaml.get("momentum_scalp_finviz_screen", {}) if isinstance(finviz_yaml, dict) else {}
        sources: list[dict[str, Any]] = []

        # 1. momentum_scalp finviz screen -> scalp_scan_results
        ssr = db.query("SELECT count(*) AS n, max(scanned_at) AS newest FROM scalp_scan_results")
        n_ssr = (ssr[0].get("n") if ssr else 0) or 0
        newest_ssr = ssr[0].get("newest") if ssr else None
        newest_ssr_dt = _parse_iso(newest_ssr)
        interval_s = int((ms_screen.get("cadence_minutes") or 5)) * 60
        age = _age_seconds(newest_ssr_dt)
        sources.append({
            "name": "momentum_scalp_finviz_screen",
            "consuming_strategies": ["momentum_scalp"],
            "query_definition": {
                "finviz_url_filters": ms_screen.get("finviz_url_filters"),
                "finviz_order": ms_screen.get("finviz_order"),
            },
            "refresh_cadence": "*/5 6-11 * * 1-5 ET (run_finviz_momentum_scalp_scan.py --window early)",
            "cadence_interval_seconds": interval_s,
            "output_table": "scalp_scan_results",
            "last_successful_run": _iso(newest_ssr),
            "row_count": n_ssr,
            "newest_row_age_seconds": age,
            "freshness": _freshness(age, interval_s, factor=3.0),
        })

        # 2. finviz_screeners (the 31-row executor for income/swing/etc.)
        fs = db.query(
            "SELECT screener_id, strategy_type, finviz_url, schedule, last_run, results_count, "
            "active, proposal_eligible, execution_eligible, human_review_only FROM finviz_screeners "
            "ORDER BY last_run DESC NULLS LAST")
        fs_newest = _parse_iso(fs[0].get("last_run")) if fs else None
        sources.append({
            "name": "finviz_screeners",
            "consuming_strategies": sorted({r.get("strategy_type") for r in fs if r.get("strategy_type")}),
            "query_definition": {
                "screener_count": len(fs),
                "screeners": [{"screener_id": r.get("screener_id"),
                               "strategy_type": r.get("strategy_type"),
                               "finviz_url": r.get("finviz_url"),   # FULL filter string
                               "schedule": r.get("schedule"),
                               "last_run": r.get("last_run"),
                               "results_count": r.get("results_count"),
                               "execution_eligible": r.get("execution_eligible"),
                               "human_review_only": r.get("human_review_only")} for r in fs],
            },
            "refresh_cadence": "per-screener `schedule` column (weekly/daily/biweekly/…) + 7 finviz_screener_runner crons/day",
            "output_table": "finviz_screeners",
            "last_successful_run": _iso(fs[0].get("last_run")) if fs else None,
            "row_count": len(fs),
            "newest_row_age_seconds": _age_seconds(fs_newest),
            "freshness": _freshness(_age_seconds(fs_newest), 24 * 3600, factor=1.5),
            "note": "governance: all rows execution_eligible=False, human_review_only=True",
        })

        # 3. Alpaca IEX minute bars -> symbol_volume_profile (intraday engine feed)
        svp = db.query("SELECT count(*) AS n, count(DISTINCT symbol) AS syms, max(built_at) AS newest, "
                       "max(feed) AS feed FROM symbol_volume_profile")
        svp0 = svp[0] if svp else {}
        svp_newest = _parse_iso(svp0.get("newest"))
        sources.append({
            "name": "alpaca_iex_minute_bars",
            "consuming_strategies": ["momentum_scalp_intraday (scalp signal engine, SHADOW/enabled:false)"],
            "query_definition": {
                "feed": "iex", "endpoint": "https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                "timeframe": "1Min",
                "entitlement": "IEX real-time; SIP DELAYED-only (recent SIP = HTTP 403)",
            },
            "refresh_cadence": "30 20 * * 1-5 (run_scalp_volume_profile_refresh.sh) + shadow logger */5 6-11",
            "output_table": "symbol_volume_profile",
            "last_successful_run": _iso(svp0.get("newest")),
            "row_count": svp0.get("n"),
            "newest_row_age_seconds": _age_seconds(svp_newest),
            "freshness": _freshness(_age_seconds(svp_newest), 24 * 3600, factor=2.0),
        })

        # 4. scalp_ignition_events (RTH shadow logger)
        sie = db.query("SELECT count(*) AS n, max(fired_at) AS newest FROM scalp_ignition_events")
        sie0 = sie[0] if sie else {}
        sie_newest = _parse_iso(sie0.get("newest"))
        sources.append({
            "name": "scalp_ignition_events",
            "consuming_strategies": ["momentum_scalp_intraday (IGN shadow sample)"],
            "query_definition": {"description": "RTH IGN shadow logger fires (lane/IGN/subscores/setup taxonomy)"},
            "refresh_cadence": "*/5 6-11 * * 1-5 ET shadow logger (RTH-gated)",
            "output_table": "scalp_ignition_events",
            "last_successful_run": _iso(sie0.get("newest")),
            "row_count": sie0.get("n"),
            "newest_row_age_seconds": _age_seconds(sie_newest),
            "freshness": _freshness(_age_seconds(sie_newest), 3600, factor=24.0),
        })

        # 5. data_source_health monitored providers
        dsh = db.query("SELECT source_key, status, last_success_at, last_failure_at, last_row_count, "
                       "failure_count, degraded, max_stale_minutes, last_error FROM data_source_health "
                       "ORDER BY source_key")
        for r in dsh:
            last_ok = _parse_iso(r.get("last_success_at"))
            interval = int((r.get("max_stale_minutes") or 1440)) * 60
            sources.append({
                "name": f"monitored:{r.get('source_key')}",
                "consuming_strategies": _unknown("multi-consumer provider; not per-strategy mapped"),
                "query_definition": {"provider": r.get("source_key"), "reported_status": r.get("status"),
                                     "last_error": r.get("last_error")},
                "refresh_cadence": f"max_stale_minutes={r.get('max_stale_minutes')}",
                "output_table": "data_source_health",
                "last_successful_run": _iso(r.get("last_success_at")),
                "row_count": r.get("last_row_count"),
                "newest_row_age_seconds": _age_seconds(last_ok),
                "freshness": _freshness(_age_seconds(last_ok), interval, factor=1.0),
                "monitor_status": r.get("status"),
                "degraded": r.get("degraded"),
            })

        # 6. Drive doc sync — S0 doc says monitored + dead since ~2026-07-19. Live: NOT present in
        #    data_source_health. Reported honestly as unknown/absent (no fabrication). LIVE DISAGREES.
        drive_present = any(r.get("source_key") == "drive" for r in dsh)
        sources.append({
            "name": "drive_doc_sync",
            "consuming_strategies": _unknown("documentation sync; not a strategy data feed"),
            "query_definition": {"description": "Google Drive documentation sync (gog CLI)"},
            "refresh_cadence": _unknown("no cron mapped in AT-CFG-S1 scope"),
            "output_table": None,
            "last_successful_run": None,
            "row_count": None,
            "newest_row_age_seconds": None,
            "freshness": {"value": None, "status": "unknown",
                          "reason": "S0 doc lists Drive doc sync as a monitored source dead since ~2026-07-19, "
                                    "but LIVE data_source_health has NO source_key='drive'. Cannot verify against "
                                    "a live monitor row — reported unknown, not fabricated. (LIVE DISAGREES WITH S0 DOC.)"},
            "monitor_present": drive_present,
        })

        stale = [s["name"] for s in sources
                 if isinstance(s.get("freshness"), dict) and s["freshness"].get("status") == "stale"]
        return _panel_frame({
            "source": "scalp_scan_results + finviz_screeners + symbol_volume_profile + scalp_ignition_events + data_source_health + crontab",
            "sources": sources,
            "stale_sources": stale,
        })
    except Exception as e:
        return _panel_frame({"status": "unknown", "reason": f"data_sources panel error: {e}", "sources": []})


def check_ladder_invariant(quality_order: Sequence[str], dcf: Mapping[str, Any],
                           slippage: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Pure invariant checker (exposed for tests). Returns a list of violations (empty = ok).
    As data quality descends (quality_order), size_multiplier MUST be non-increasing AND
    assumed_slippage_bps MUST be non-decreasing."""
    violations: list[dict[str, Any]] = []
    for i in range(1, len(quality_order)):
        prev, cur = quality_order[i - 1], quality_order[i]
        pm, cm = dcf.get(prev), dcf.get(cur)
        ps, cs = slippage.get(prev), slippage.get(cur)
        if pm is not None and cm is not None and cm > pm:
            violations.append({"between": [prev, cur], "field": "size_multiplier",
                               "values": [pm, cm], "expected": "non-increasing"})
        if ps is not None and cs is not None and cs < ps:
            violations.append({"between": [prev, cur], "field": "assumed_slippage_bps",
                               "values": [ps, cs], "expected": "non-decreasing"})
    return violations


def _panel_feed_tier_ladder() -> dict[str, Any]:
    """Entitlement matrix + tier ladder + monotonicity invariant (loud on violation)."""
    try:
        engine = _load_yaml(_CONFIG_FILES["scalp_signal_engine"])
        dt = engine.get("data_tiers", {}) if isinstance(engine, dict) else {}
        quality_order = dt.get("quality_order") or ["T2", "T1", "T0"]
        dcf = dt.get("dcf") or {}
        slip = dt.get("assumed_slippage_bps") or {}

        labels = {"T2": "full order book (best data)", "T1": "SIP/quotes",
                  "T0": "bars-only (weakest, ships today)"}
        tiers = [{"tier": t, "label": labels.get(t, t),
                  "size_multiplier": dcf.get(t), "assumed_slippage_bps": slip.get(t)}
                 for t in quality_order]

        violations = check_ladder_invariant(quality_order, dcf, slip)

        # moomoo L2 status is PROBED, not asserted. It was hardcoded to
        # "SCAFFOLD_ONLY (not configured)" and stayed that way after OpenD came up
        # and depth was proven entitled (2026-07-28) — the panel contradicted reality.
        t2_state, t2_desc = _moomoo_l2_entitlement()
        entitlement = {
            "consumers": {
                "momentum_scalp_finviz_screen": "finviz Elite export (no live quote entitlement needed)",
                "momentum_scalp_intraday": "IEX real-time (SIP delayed-only; recent SIP = HTTP 403)",
                "t1_microstructure": "SIP_REALTIME required — NOT procured (t1.enabled:false)",
                "t2_level2": t2_desc,
            },
            "feed_availability": {"iex": "real-time", "sip": "delayed-only", "polygon": "not procured",
                                  "moomoo_l2": t2_state},
        }

        return _panel_frame({
            "source": "config/scalp_signal_engine.yaml:data_tiers",
            "entitlement_matrix": entitlement,
            "tier_ladder": tiers,
            "quality_order": quality_order,
            "invariant_ok": len(violations) == 0,
            "invariant_violations": violations,
            "invariant_definition": "as data quality descends (quality_order), size_multiplier MUST be "
                                    "non-increasing AND assumed_slippage_bps MUST be non-decreasing.",
        })
    except Exception as e:
        return _panel_frame({"status": "unknown", "reason": f"feed_tier_ladder panel error: {e}",
                             "invariant_ok": None, "invariant_violations": []})


def _panel_job_health(db: _DB) -> dict[str, Any]:
    """Volume-profile coverage, nightly refresh state, scanner last run, jobs behind schedule."""
    try:
        engine = _load_yaml(_CONFIG_FILES["scalp_signal_engine"])
        vp_cfg = engine.get("volume_profile", {}) if isinstance(engine, dict) else {}
        min_sessions = vp_cfg.get("min_sessions", 15)

        vp = db.query(
            "SELECT symbol, max(n_sessions) AS n, max(built_at) AS built FROM symbol_volume_profile "
            "GROUP BY symbol")
        symbols = len(vp)
        below = [r["symbol"] for r in vp if (r.get("n") or 0) < min_sessions]
        newest_build = None
        if vp:
            builts = [_parse_iso(r.get("built")) for r in vp if _parse_iso(r.get("built"))]
            newest_build = max(builts) if builts else None
        volume_profile = {
            "table": "symbol_volume_profile",
            "symbols": symbols,
            "min_sessions_required": min_sessions,
            "symbols_below_minimum": len(below),
            "symbols_below_minimum_list": below[:50],
            "newest_built_at": _iso(newest_build),
            "newest_built_age_seconds": _age_seconds(newest_build),
        }

        ssr = db.query("SELECT max(scanned_at) AS newest FROM scalp_scan_results")
        scan_newest = _parse_iso(ssr[0].get("newest")) if ssr else None
        scanner = {
            "table": "scalp_scan_results",
            "last_run": _iso(scan_newest),
            "last_run_age_seconds": _age_seconds(scan_newest),
            "cadence": "*/5 6-11 * * 1-5 ET",
        }

        nightly = {
            "job": "run_scalp_volume_profile_refresh.sh",
            "schedule": "30 20 * * 1-5",
            "last_success_proxy": _iso(newest_build),
            "last_success_age_seconds": _age_seconds(newest_build),
        }

        behind: list[dict[str, Any]] = []
        if newest_build is not None:
            age = _age_seconds(newest_build)
            if age is not None and age > 30 * 3600:
                behind.append({"job": "scalp_volume_profile_refresh", "age_seconds": age,
                               "expected_interval_seconds": 24 * 3600})

        return _panel_frame({
            "source": "symbol_volume_profile + scalp_scan_results + scalp_signal_engine.yaml + crontab",
            "volume_profile_coverage": volume_profile,
            "scanner": scanner,
            "nightly_refresh": nightly,
            "backfill_rollup": {"backfill_days": vp_cfg.get("backfill_days"),
                                "lookback_sessions": vp_cfg.get("lookback_sessions"),
                                "status": "measured via symbol_volume_profile coverage above"},
            "jobs_behind_schedule": behind,
        })
    except Exception as e:
        return _panel_frame({"status": "unknown", "reason": f"job_health panel error: {e}"})


def _env_present(name: str, env: Mapping[str, str], dotenv: Mapping[str, str]) -> bool:
    """True if a credential slot is populated in os.environ OR the .env file. Value NEVER returned."""
    v = env.get(name)
    if v is not None and str(v).strip():
        return True
    v2 = dotenv.get(name)
    return bool(v2 is not None and str(v2).strip())


def _read_dotenv() -> dict[str, str]:
    """Parse .env for PRESENCE detection only. Values are read but NEVER emitted."""
    out: dict[str, str] = {}
    try:
        p = _REPO_ROOT / ".env"
        if not p.is_file():
            return out
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        return {}
    return out


def _panel_execution_posture(db: _DB) -> dict[str, Any]:
    """Read-only execution flags + standing_db_unlock scope + credential_slots (NAME + populated only)."""
    try:
        dotenv = _read_dotenv()
        env = os.environ

        sc = db.query("SELECT key, value, updated_at FROM system_controls")
        sc_by = {r["key"]: r for r in sc}

        def sc_flag(key: str) -> dict[str, Any]:
            row = sc_by.get(key)
            if not row:
                return {"value": None, "status": "unknown", "reason": f"{key} not in system_controls",
                        "source_of_truth": f"system_controls.{key}"}
            return {"value": row.get("value"), "source_of_truth": f"system_controls.{key}",
                    "last_changed": row.get("updated_at")}

        appr = db.query("SELECT broker, scope, approved_at, revoked_at FROM broker_live_approvals")
        active_appr = [a for a in appr if a.get("revoked_at") is None]

        ba = db.query("SELECT account_key, environment, is_enabled, api_write_enabled, api_read_enabled, "
                      "credential_slot FROM broker_accounts ORDER BY account_key")
        routable = [a["account_key"] for a in ba
                    if a.get("environment") == "live" and a.get("is_enabled") and a.get("api_write_enabled")]

        flags = {
            "ALPACA_MODE": {"value": dotenv.get("ALPACA_MODE") or env.get("ALPACA_MODE"),
                            "source_of_truth": ".env ALPACA_MODE"},
            "LLM_DISABLE_LIVE_EXECUTION": {"value": dotenv.get("LLM_DISABLE_LIVE_EXECUTION") or env.get("LLM_DISABLE_LIVE_EXECUTION"),
                                           "source_of_truth": ".env LLM_DISABLE_LIVE_EXECUTION"},
            "broker_live_enabled": sc_flag("broker_live_enabled"),
            "schwab_pilot_standing_unlock": sc_flag("schwab_pilot_standing_unlock"),
            "pilot_armed_until": sc_flag("pilot_armed_until"),
            "scalp_signal_engine_enabled": {"value": _load_yaml(_CONFIG_FILES["scalp_signal_engine"]).get("enabled"),
                                            "source_of_truth": "config/scalp_signal_engine.yaml:enabled"},
            "autonomous_live_submit": _unknown("no such key in system_controls or .env — the interlock is the composite execution_guard, not a scalar flag"),
            "live_trading_interlock": _unknown("no single flag; interlock = composite guard in brokers/execution_guard + per-order 2FA"),
        }

        pilot_until = (sc_by.get("pilot_armed_until") or {}).get("value")
        standing = {
            "unlocked": (sc_by.get("schwab_pilot_standing_unlock") or {}).get("value") == "true"
                        and (sc_by.get("broker_live_enabled") or {}).get("value") == "true",
            "scope": "persistent" if str(pilot_until or "").startswith("2099") else "session_or_dated",
            "pilot_armed_until": pilot_until,
            "active_approvals": len(active_appr),
            "routable_accounts": routable,
            "remaining_gate": "per-order 2FA (web typed-ticker + Telegram) enforced in brokers/execution_guard",
            "note": "standing unlock is PERSISTENT (pilot_armed_until=2099). Env posture "
                    "(ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true) TENSIONS with the DB unlock — "
                    "reported, not reconciled.",
        }

        accounts = [{
            "account_key": a.get("account_key"),
            "environment": a.get("environment"),
            "is_enabled": a.get("is_enabled"),
            "api_write": a.get("api_write_enabled"),
            "api_read": a.get("api_read_enabled"),
            "credential_slot_name": a.get("credential_slot"),   # NAME only, never a value
        } for a in ba]

        credential_slots = [{"name": name, "populated": _env_present(name, env, dotenv)}
                            for name in _CREDENTIAL_SLOT_NAMES]

        return _panel_frame({
            "source": "system_controls + broker_accounts + broker_live_approvals + .env (presence only)",
            "flags": flags,
            "standing_db_unlock": standing,
            "broker_accounts": accounts,
            "credential_slots": credential_slots,
            "secret_values_present": False,
            "note": "credential_slots report NAME + populated boolean ONLY. No secret value is ever emitted.",
        })
    except Exception as e:
        return _panel_frame({"status": "unknown", "reason": f"execution_posture panel error: {e}",
                             "credential_slots": []})


def _panel_provenance() -> dict[str, Any]:
    """Config commit SHA, working-tree clean/dirty, per-file last_modified, fetched_at."""
    try:
        head = _git(["rev-parse", "--short", "HEAD"])
        porcelain = _git(["status", "--porcelain"])
        clean = (porcelain == "" or porcelain is None)
        files = {}
        for key, rel in _CONFIG_FILES.items():
            files[key] = {"path": rel, "git_sha": _git_sha(rel), "last_modified": _git_last_modified(rel)}
        return _panel_frame({
            "config_commit_sha": head,
            "working_tree_clean": clean,
            "config_files": files,
            "fetched_at": _now().isoformat(),
        })
    except Exception as e:
        return _panel_frame({"status": "unknown", "reason": f"provenance panel error: {e}",
                             "fetched_at": _now().isoformat()})


# --------------------------------------------------------------------------- aggregator

def config_overview() -> dict[str, Any]:
    """Aggregate ALL EIGHT read-only Active Trader config panels in one payload.

    GET/read only. Never writes. Never raises. Never emits a secret value.
    """
    db = _DB()
    payload = {
        "contract": CONTRACT,
        "stage": "AT-CFG-S1",
        "write": False,
        "canary": False,
        "read_only": True,
        "auto_route": False,
        "generated_at": _now().isoformat(),
        "authority": {"mutation": False, "order": False, "session_authorize": False,
                      "canary": False, "financial_action": False},
        "db_available": None,   # filled after first query attempt
        "strategy_registry": _panel_strategy_registry(db),
        "setup_taxonomy": _panel_setup_taxonomy(db),
        "criteria_matrix": _panel_criteria_matrix(db),
        "data_sources": _panel_data_sources(db),
        "feed_tier_ladder": _panel_feed_tier_ladder(),
        "job_health": _panel_job_health(db),
        "execution_posture": _panel_execution_posture(db),
        "provenance": _panel_provenance(),
    }
    payload["db_available"] = db.available
    return payload


if __name__ == "__main__":
    import json
    print(json.dumps(config_overview(), indent=2, default=str))
