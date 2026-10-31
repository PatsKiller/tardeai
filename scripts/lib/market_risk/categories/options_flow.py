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
    today: dict[str, dict] = {}
    history: dict[str, list[dict]] = {}
    for sym, lst in grouped.items():
        lst.sort(key=lambda r: md.ts(r), reverse=True)
        today[sym] = {**lst[0], "as_of": md.iso(md.ts(lst[0]))}
        history[sym] = lst[1:]
    newest = max(md.ts(r) for r in today.values())
    if md.stale(newest, ctx.now, ccfg["stale_after_hours"]):
        return unknown(CATEGORY, ctx.now, f"option snapshots stale (newest {md.iso(newest)})")
    findings = detector.evaluate(today, history, dcfg)
    known = [f for f in findings if f.get("state") != "UNKNOWN"]
    unknowns = [f for f in findings if f.get("state") == "UNKNOWN"]
    if unknowns and len(unknowns) == len(today):
        return unknown(CATEGORY, ctx.now, "; ".join(f"{f['symbol']} {f['reason']}" for f in unknowns))
    states = {f["state"] for f in known}
    state = "STRESS" if "STRESS" in states else "WARN" if "WARN" in states else "CALM"
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
        ev.append(Evidence(f"{f['symbol']} put/call", "UNKNOWN", None, SOURCE, f"{f['symbol']} {f['reason']}"))
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
        observed_at=md.iso(newest) or "",
        headline=f"Options flow: {head}",
        evidence=tuple(ev),
        stale_after_hours=float(ccfg["stale_after_hours"]),
    )
    assert_no_behavior_fields(obs.to_dict())
    return obs
