"""Options-flow category: wraps the P0 detector (scripts/lib/market_risk/options_flow.evaluate) as a scored
CategoryObservation. The detector owns the WARN/STRESS rules (policy key ``options_flow``); this module only groups
the reader's snapshot rows into today/history and maps the worst finding to a category score
(policy key ``options_flow_category``). RCA: 10-29 10:00 ET QQQ put/call volume 3.31 (3.4x median) -> STRESS.
"""

from __future__ import annotations

from scripts.lib.market_risk import options_flow as detector
from scripts.lib.market_risk.categories import _marketdata as md
from scripts.lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, assert_no_behavior_fields
from scripts.lib.market_risk.contract import unknown

CATEGORY = "options_flow"
SOURCE = "option_chain_snapshots"


def _allowance(newest, ctx: EvalContext, ccfg: dict) -> float:
    """Market hours a snapshot taken at ``newest`` stays current. With ``expected_slots_et`` it lasts until the second
    expected snapshot slot after it is due (+ ``late_slack_minutes``): one missed or late slot is tolerated, two are
    not, so a Monday or post-holiday 10:00 snapshot that lands late does not blank the category, and a feed that stops
    still goes UNKNOWN (review of #2425). Without slots: the fixed ``stale_after_hours``."""
    slots = ccfg.get("expected_slots_et")
    if not slots:
        return float(ccfg["stale_after_hours"])
    from scripts.lib.market_risk import scoring, sessions as mr_sessions

    deadline = mr_sessions.slot_deadline(
        newest,
        list(slots),
        float(ccfg.get("late_slack_minutes", 45)),
        missed_allowed=int(ccfg.get("missed_slots_allowed", 1)),
    )
    return scoring._age_hours(newest, deadline, ctx.policy.get("decay") or {})


def _latest_inputs(
    ctx: EvalContext, ccfg: dict, grouped: dict[str, list[dict]]
) -> tuple[dict[str, dict], dict[str, list[dict]], list[dict]]:
    """Split rows into each symbol's LATEST usable input and its history.

    A symbol's latest row is usable only while that row's own timestamp is current. The slot allowance is measured
    from the row, never from the newest row across symbols: a symbol that stopped updating (a failed collection)
    cannot inherit another symbol's fresh timestamp, and a row past its own allowance is excluded instead of being
    shown as "today" (provenance defect D1, audit 2026-11-02). ``missed_slots_allowed`` and every threshold are
    unchanged; a row still inside the tolerance stays in ``today`` carrying its TRUE ``as_of``.
    """
    today: dict[str, dict] = {}
    history: dict[str, list[dict]] = {}
    expired: list[dict] = []
    for sym, lst in grouped.items():
        lst.sort(key=lambda r: md.ts(r), reverse=True)
        at = md.ts(lst[0])
        latest = {**lst[0], "as_of": md.iso(at)}
        allowance = _allowance(at, ctx, ccfg)
        if md.stale(at, ctx.now, allowance, ctx.policy.get("decay")):
            expired.append({**latest, "limit_hours": allowance})
            history[sym] = [latest] + lst[1:]  # its prior rows still inform the trailing median
        else:
            today[sym] = latest
            history[sym] = lst[1:]
    return today, history, expired


def _determining_symbols(state: str, today: dict[str, dict], findings: list[dict]) -> list[str]:
    """Symbols whose latest input determines the category state: the findings at the state's severity for
    WARN/STRESS, and every evaluated (non-UNKNOWN) symbol for CALM. These are the readings the headline shows, so the
    observation's ``observed_at`` is the OLDEST of their true timestamps: the contributor then carries the evidence
    time of the reading shown and decay reflects the weakest input that set the state, not another symbol's newest."""
    if state in ("WARN", "STRESS"):
        return [f["symbol"] for f in findings if f.get("state") == state and f.get("symbol") in today]
    unknown = {f["symbol"] for f in findings if f.get("state") == "UNKNOWN"}
    return [sym for sym in today if sym not in unknown]


def evaluate(ctx: EvalContext) -> CategoryObservation:
    dcfg, ccfg = ctx.policy["options_flow"], ctx.policy["options_flow_category"]
    sessions = int(dcfg["lookback_sessions"]) + int(ccfg["history_extra_sessions"])
    rows = ctx.reader.option_snapshots(dcfg["index_symbols"], sessions=sessions, end=ctx.now)
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("symbol") and md.ts(r) is not None:
            grouped.setdefault(str(r["symbol"]), []).append(r)
    if not grouped:
        return unknown(CATEGORY, ctx.now, "no option-chain snapshots")
    today, history, expired = _latest_inputs(ctx, ccfg, grouped)
    if not today:
        detail = "; ".join(
            f"{e['symbol']} {e['as_of']} expired (limit {e['limit_hours']:.1f} market hours)" for e in expired
        )
        return unknown(CATEGORY, ctx.now, f"option snapshots stale ({detail})")
    findings = detector.evaluate(today, history, dcfg)
    known = [f for f in findings if f.get("state") != "UNKNOWN"]
    unknowns = [f for f in findings if f.get("state") == "UNKNOWN"]
    if unknowns and len(unknowns) == len(today):
        return unknown(CATEGORY, ctx.now, "; ".join(f"{f['symbol']} {f['reason']}" for f in unknowns))
    states = {f["state"] for f in known}
    state = "STRESS" if "STRESS" in states else "WARN" if "WARN" in states else "CALM"
    # Provenance: date the category to the evidence the contributor shows (oldest determining input), not to the
    # newest row of another symbol. With the day's QQQ collection failed, Friday's QQQ reading keeps Friday's as_of,
    # so the Home card cannot stamp it with Monday's timestamp and decay follows the reading actually used.
    determining = _determining_symbols(state, today, findings)
    observed = min((md.ts(today[sym]) for sym in determining), default=None) or max(
        md.ts(r) for r in today.values()
    )
    stale_after = _allowance(observed, ctx, ccfg)
    missing = [str(s) for s in dcfg["index_symbols"] if str(s) not in grouped]
    ev: list[Evidence] = []
    for f in known:
        bits = []
        if f.get("pc_vol_state"):
            bits.append(f"P/C vol {f['pc_vol_ratio']:.2f} ({f['pc_vol_factor']}x median)")
        if f.get("pc_oi_state"):
            bits.append(f"P/C OI {f['pc_oi_ratio']:.2f} ({f['pc_oi_factor']}x median)")
        ev.append(
            Evidence(
                f"{f['symbol']} put/call vs trailing median",
                f["state"],
                f.get("as_of"),
                SOURCE,
                f"{f['symbol']} " + ", ".join(bits),
            )
        )
    for f in unknowns:
        row = today.get(f["symbol"]) or {}
        ev.append(
            Evidence(f"{f['symbol']} put/call", "UNKNOWN", row.get("as_of"), SOURCE, f"{f['symbol']} {f['reason']}")
        )
    for e in expired:
        ev.append(
            Evidence(
                f"{e['symbol']} put/call",
                "UNKNOWN",
                e["as_of"],
                SOURCE,
                f"{e['symbol']} snapshot {e['as_of']} expired (limit {e['limit_hours']:.1f} market hours)",
            )
        )
    for sym in missing:
        ev.append(Evidence(f"{sym} put/call", "UNKNOWN", None, SOURCE, f"{sym} no option-chain snapshot"))
    for sym, r in sorted(today.items()):
        ev.append(
            Evidence(
                f"{sym} put/call today",
                {"pc_oi": md.num(r.get("pc_oi_ratio")), "pc_vol": md.num(r.get("pc_vol_ratio"))},
                r["as_of"],
                SOURCE,
                "",
            )
        )
    head = " · ".join(e.detail for e in ev if e.value in ("WARN", "STRESS")) or "index put/call near its median"
    obs = CategoryObservation(
        category=CATEGORY,
        state=state,
        score=float(ccfg["score"][state]),  # type: ignore[arg-type]
        observed_at=md.iso(observed) or "",
        headline=f"Options flow: {head}",
        evidence=tuple(ev),
        stale_after_hours=stale_after,
    )
    assert_no_behavior_fields(obs.to_dict())
    return obs
