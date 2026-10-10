"""Scalp list + scalp hot-tier freshness — Data Broker read model (zero provider calls, never writes).

The momentum-scalp list has two writers, one per window, and **each store keeps its single writer**:

- **09:30–16:00 ET** — ``<state_root>/data/trade_ai/scalp_universe_latest.json`` (``TradeAIScalpUniverse@v1``),
  written by L1050 ``run_trade_ai_scalp_live.py`` every 5 min. L1050 is not touched; this module only reads its file.
- **06:00–09:30 ET** — the hot tier: L636's refresh stage pulls the scalp screeners every 2 min through the existing
  ``finviz_screener_runner.py --screener`` (single writer of ``screener_symbol_membership``) and stamps
  ``<state_root>/data/runtime/momentum_scalp_refresh_receipt.json`` (``MomentumScalpRefreshReceipt@v1``, single writer
  ``momentum_scalp_early_lane_runner.py``). The list is the membership rows of those screeners that were present in
  that refresh; its ``as_of`` is the receipt's DONE time.

:func:`get_scalp_list` returns whichever is fresher, with ``as_of`` / ``age_hours`` / ``stale`` (BrokerReadEnvelope@v1)
and both candidates' ages. :func:`get_scalp_enrichment` reads the Finviz enrichment cache for the list's symbols with
the hot-tier ``hot_cached_at`` stamp. :func:`freshness_report` judges the four hot-tier SLOs (list ≤5 min, enrichment
≤10, research ≤30 after arrival, social ≤15) on market days 06:00–16:00 ET; outside that window it says ``NO_SLO``.

Registry status: ``scalp_list`` is a PROPOSED domain (operator decision D.5, ``proposed_registry_rows.json``); until
the operator grants it, the windows are passed explicitly and ``source.registry_status`` says PROPOSED_UNREGISTERED.
READ_ONLY_ADVISORY: a list of names to research, never a trade signal.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from lib import scalp_hot_tier as hot
from lib.data_broker.envelope import envelope

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

DOMAIN = "scalp_list"
PROJECTION = "scalp_list"
UNIVERSE_REL = Path("data") / "trade_ai" / "scalp_universe_latest.json"
RECEIPT_REL = Path("data") / "runtime" / "momentum_scalp_refresh_receipt.json"
RECEIPT_ENV = "MOMENTUM_SCALP_REFRESH_RECEIPT"
SOCIAL_LANE_ID = "social-ingest-scalp-hot"
ENRICH_LANE_ID = "finviz-enrichment-scalp-hot"
CLOSED_STALE_HOURS = 72.0
#: membership rows must have been seen in the refresh that stamped the receipt (minus this slack)
MEMBERSHIP_SLACK_MIN = 5.0
MEMBERSHIP_SQL = (
    "SELECT symbol, screener_id, last_seen_in_screener_at FROM screener_symbol_membership "
    "WHERE screener_id = ANY(%s) AND present_this_run = TRUE AND last_seen_in_screener_at >= %s"
)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive = host-local (the writers stamp datetime.now())
    return dt.astimezone(timezone.utc)


def _parse(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return _utc(ts)
    if not ts:
        return None
    try:
        return _utc(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
    except ValueError:
        return None


def _age_min(as_of: datetime | None, now: datetime) -> float | None:
    return None if as_of is None else round(max(0.0, (now - as_of).total_seconds() / 60.0), 2)


def _now(now: datetime | None) -> datetime:
    return _utc(now) if now is not None else datetime.now(timezone.utc)


def _root(state_root: Path | str | None) -> Path:
    return Path(state_root) if state_root else hot._state_root()


def read_universe(state_root: Path | str | None = None) -> dict[str, Any]:
    """L1050's universe file, read-only. Wrong schema / unreadable -> empty with ``as_of`` None."""
    path = _root(state_root) / UNIVERSE_REL
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"file": str(path), "as_of": None, "symbols": [], "error": "unreadable_or_missing"}
    if not isinstance(doc, dict) or doc.get("schema") != "TradeAIScalpUniverse@v1":
        return {"file": str(path), "as_of": None, "symbols": [], "error": "schema_mismatch"}
    rows = doc.get("rows") if isinstance(doc.get("rows"), list) else []
    syms = []
    for r in rows:
        s = str((r or {}).get("symbol") or "").upper().strip() if isinstance(r, dict) else ""
        if s and s not in syms:
            syms.append(s)
    return {"file": str(path), "as_of": _parse(doc.get("as_of")), "symbols": syms, "writer": doc.get("writer")}


def receipt_path(state_root: Path | str | None = None) -> Path:
    override = os.environ.get(RECEIPT_ENV, "").strip()
    return Path(override) if override else _root(state_root) / RECEIPT_REL


def read_refresh_receipt(state_root: Path | str | None = None) -> dict[str, Any] | None:
    try:
        doc = json.loads(receipt_path(state_root).read_text())
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def _db_rows(screener_ids: list[str], since: datetime) -> list[tuple]:
    """Membership rows through a READ ONLY session (db_adapter; credentials via the existing env bootstrap)."""
    from db_adapter import get_connection

    from lib.lane_last_receipt import enforce_readonly

    conn = get_connection()
    try:
        enforce_readonly(conn)
        cur = conn.cursor()
        cur.execute(MEMBERSHIP_SQL, (list(screener_ids), since))
        return [
            tuple(r) if not isinstance(r, dict) else (r["symbol"], r["screener_id"], r["last_seen_in_screener_at"])
            for r in cur.fetchall()
        ]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def read_premarket(
    *,
    state_root: Path | str | None = None,
    screener_ids: Iterable[str] | None = None,
    rows_fn: Callable[[list[str], datetime], list[tuple]] | None = None,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The hot-tier premarket list: membership rows of the refresh that stamped the DONE receipt."""
    ids = list(screener_ids or hot.scalp_screener_ids())
    rec = receipt if receipt is not None else read_refresh_receipt(state_root)
    out: dict[str, Any] = {"receipt": str(receipt_path(state_root)), "screener_ids": ids, "as_of": None, "symbols": []}
    if not rec or rec.get("state") != "DONE":
        out["error"] = "no_done_receipt"
        return out
    as_of = _parse(rec.get("at"))
    refreshed = [str(x) for x in (rec.get("screener_ids") or [])]
    covered = [s for s in ids if s in refreshed]
    out.update(as_of=as_of, receipt_screener_ids=refreshed, covered_screener_ids=covered)
    if not covered or as_of is None:
        out["error"] = "receipt_not_covering_scalp_screeners"
        return out
    since = as_of - timedelta(minutes=MEMBERSHIP_SLACK_MIN)
    try:
        rows = (rows_fn or _db_rows)(covered, since)
    except Exception as exc:
        out["error"] = f"membership_unreadable: {type(exc).__name__}"
        return out
    syms: list[str] = []
    for r in rows:
        s = str(r[0] or "").upper().strip()
        if s and s not in syms:
            syms.append(s)
    out["symbols"] = syms
    return out


def get_scalp_list(
    *,
    now: datetime | None = None,
    state_root: Path | str | None = None,
    rows_fn: Callable[[list[str], datetime], list[tuple]] | None = None,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The current scalp list: the fresher of L1050's universe and the hot-tier premarket list."""
    ref = _now(now)
    uni = read_universe(state_root)
    pre = read_premarket(state_root=state_root, rows_fn=rows_fn, receipt=receipt)
    cands = []
    for name, c in (("l1050_scalp_universe", uni), ("hot_tier_premarket_screeners", pre)):
        cands.append(
            {
                "list_source": name,
                "as_of": c.get("as_of"),
                "symbols": c.get("symbols") or [],
                "age_min": _age_min(c.get("as_of"), ref),
                "error": c.get("error"),
            }
        )
    usable = [c for c in cands if c["as_of"] is not None]
    pick = max(usable, key=lambda c: c["as_of"]) if usable else {"list_source": None, "as_of": None, "symbols": []}
    in_slo = hot.in_window("slo", ref)
    env = envelope(
        DOMAIN,
        pick["as_of"],
        now=ref,
        stale_after_hours=(hot.SLOS["scalp_list"]["healthy"] / 60.0) if in_slo else CLOSED_STALE_HOURS,
        source={
            "projection": PROJECTION,
            "provider": "finviz",
            "registry_status": "PROPOSED_UNREGISTERED",
            "writers": {
                "l1050_scalp_universe": "scripts/run_trade_ai_scalp_live.py",
                "hot_tier_premarket_screeners": "scripts/finviz_screener_runner.py "
                "(via momentum_scalp_early_lane_runner refresh stage)",
            },
            "file": str(_root(state_root) / UNIVERSE_REL),
        },
    )
    out = {
        "ok": True,
        "provider_calls": 0,
        "list_source": pick["list_source"],
        "symbols": list(pick["symbols"]),
        "in_slo_window": in_slo,
        "candidates": [{**c, "as_of": c["as_of"].isoformat() if c["as_of"] else None} for c in cands],
    }
    out.update(env)
    return out


# ── enrichment for the list (hot stamp) ───────────────────────────────────────


def hot_as_of(record: Any) -> datetime | None:
    """The newer of the hot-tier ``hot_cached_at`` and the full-refresh ``cached_at`` (both naive host-local)."""
    if not isinstance(record, dict):
        return None
    vals = [d for d in (_parse(record.get("hot_cached_at")), _parse(record.get("cached_at"))) if d]
    return max(vals) if vals else None


def get_scalp_enrichment(
    symbols: Iterable[Any],
    *,
    max_age_min: float | None = None,
    now: datetime | None = None,
    cache: dict[str, Any] | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """RVOL/gap/float/price/ATR/RSI freshness per scalp symbol from the enrichment cache (single writer:
    scripts/finviz_enrichment.py). Zero provider calls; never fetches."""
    from lib.data_broker import finviz_enrichment_snapshot as snap

    ref = _now(now)
    window = float(max_age_min if max_age_min is not None else hot.SLOS["scalp_enrichment"]["healthy"])
    data = cache if cache is not None else snap.read_cache(root)
    per: dict[str, Any] = {}
    fresh, stale = [], []
    oldest: datetime | None = None
    newest: datetime | None = None
    worst_age: float | None = None
    for s in symbols or []:
        sym = str(s or "").upper().strip()
        if not sym or sym in per:
            continue
        rec = data.get(sym)
        dt = hot_as_of(rec)
        age = _age_min(dt, ref)
        is_stale = age is None or age > window
        per[sym] = {
            "as_of": dt.isoformat() if dt else None,
            "age_min": age,
            "stale": is_stale,
            "fields": {
                k: (rec or {}).get(k)
                for k in ("price", "rvol", "gap_pct", "float_m", "atr", "rsi", "change_from_open_pct", "volume")
            }
            if isinstance(rec, dict)
            else None,
        }
        (stale if is_stale else fresh).append(sym)
        if dt:
            oldest = dt if oldest is None or dt < oldest else oldest
            newest = dt if newest is None or dt > newest else newest
        worst_age = float("inf") if age is None else max(worst_age or 0.0, age)
    env = envelope(
        "finviz_enrichment",
        oldest,
        now=ref,
        stale_after_hours=window / 60.0,
        source={
            "file": snap.CACHE_REL,
            "writer": snap.WRITER,
            "projection": PROJECTION,
            "provider": "finviz",
            "registry_status": "PROPOSED_UNREGISTERED",
            "as_of_basis": "oldest hot stamp among the requested symbols",
        },
    )
    out = {
        "ok": True,
        "provider_calls": 0,
        "symbols": per,
        "fresh": fresh,
        "stale_or_missing": stale,
        "worst_age_min": None if worst_age in (None, float("inf")) else round(worst_age, 2),
        "missing_any": worst_age == float("inf"),
        "newest_as_of": newest.isoformat() if newest else None,
    }
    out.update(env)
    return out


# ── freshness SLOs ────────────────────────────────────────────────────────────


def _research_records(day: str, root: Path | str | None = None) -> dict[str, datetime]:
    path = Path(root or PROJECT_ROOT) / "data" / "hermes" / "momentum_catalysts" / f"{day}_catalysts.jsonl"
    out: dict[str, datetime] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        sym = str(rec.get("symbol") or "").upper()
        ts = _parse(rec.get("research_timestamp"))
        if sym and ts and (sym not in out or ts > out[sym]):
            out[sym] = ts
    return out


def _receipt_ok_at(lane_id: str, state_root: Path | str | None) -> tuple[datetime | None, dict[str, Any] | None]:
    path = _root(state_root) / "data" / "runtime" / f"{lane_id}_last.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return None, None
    return _parse(doc.get("ok_at")), doc


def freshness_report(
    *,
    now: datetime | None = None,
    state_root: Path | str | None = None,
    project_root: Path | str | None = None,
    list_env: dict[str, Any] | None = None,
    cache: dict[str, Any] | None = None,
    first_seen: dict[str, str] | None = None,
    rows_fn: Callable[[list[str], datetime], list[tuple]] | None = None,
) -> dict[str, Any]:
    """The four hot-tier SLOs. Market days 06:00–16:00 ET only; otherwise every domain is NO_SLO."""
    ref = _now(now)
    in_slo = hot.in_window("slo", ref)
    lst = list_env if list_env is not None else get_scalp_list(now=ref, state_root=state_root, rows_fn=rows_fn)
    symbols = list(lst.get("symbols") or [])
    report: dict[str, Any] = {
        "schema": "ScalpHotTierFreshness@v1",
        "now": ref.isoformat(),
        "in_slo_window": in_slo,
        "hot_tier": hot.flag_state(state_root=state_root),
        "list_source": lst.get("list_source"),
        "list_symbols": len(symbols),
        "domains": {},
    }
    list_age = _age_min(_parse(lst.get("as_of")), ref)
    enr = get_scalp_enrichment(symbols, now=ref, cache=cache, root=project_root)
    enr_age = None if enr.get("missing_any") else enr.get("worst_age_min")
    if not symbols:
        enr_age = list_age  # nothing to enrich: enrichment is as fresh as the (empty) list
    t_et = hot.now_et(ref)
    if first_seen is None:
        try:
            from lib import scalp_list_trigger as trig

            first_seen = trig.first_seen_today(ref, state_root=state_root)
        except Exception:
            first_seen = {}
    researched = _research_records(t_et.date().isoformat(), project_root)
    list_as_of = _parse(lst.get("as_of")) or ref
    lags = {}
    for s in symbols:
        arrival = _parse((first_seen or {}).get(s)) or list_as_of
        r = researched.get(s)
        covered = r is not None and r >= arrival - timedelta(minutes=hot.RESEARCH_STALE_MIN)
        lags[s] = 0.0 if covered else round(max(0.0, (ref - arrival).total_seconds() / 60.0), 2)
    research_lag = max(lags.values()) if lags else 0.0
    social_ok_at, social_doc = _receipt_ok_at(SOCIAL_LANE_ID, state_root)
    social_age = _age_min(social_ok_at, ref)
    measured = {
        "scalp_list": list_age,
        "scalp_enrichment": enr_age,
        "scalp_research": research_lag,
        "scalp_social": social_age,
    }
    # social is polled only 06:00-11:00; the other three domains are judged 06:00-16:00
    slo_on = {d: in_slo for d in measured}
    slo_on["scalp_social"] = hot.in_window("social", ref)
    for dom, age in measured.items():
        report["domains"][dom] = {
            "age_min": age,
            "status": hot.slo_status(dom, age) if slo_on[dom] else "NO_SLO",
            "slo_min": hot.SLOS[dom],
        }
    report["domains"]["scalp_enrichment"].update(fresh=len(enr["fresh"]), stale_or_missing=len(enr["stale_or_missing"]))
    report["domains"]["scalp_research"].update(unresearched=sorted(s for s, v in lags.items() if v > 0)[:25])
    report["domains"]["scalp_social"].update(
        receipt_lane=SOCIAL_LANE_ID, receipt_symbols=len(((social_doc or {}).get("summary") or {}).get("symbols") or [])
    )
    statuses = [d["status"] for d in report["domains"].values()]
    order = ["NO_SLO", "healthy", "late", "degraded", "failed"]
    report["overall"] = max(statuses, key=order.index) if statuses else "NO_SLO"
    return report
