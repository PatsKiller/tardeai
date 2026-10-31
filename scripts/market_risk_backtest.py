#!/usr/bin/env python3
"""Market Risk Engine scenario replay and backtest (design DSN-20261031-market-risk-engine §8; plan §5.15,
tasks P2-T2 / P2-T12).

Walks each scenario's sessions through the real engine — ``scripts.lib.market_risk.scoring.compose`` over the
category modules (``registry.evaluate_all`` when present, else ``categories.<name>.evaluate``) — reading only the
as-of-correct ``FixtureReader``. It never invents a result: when the engine modules are not importable it says
which are missing and exits 3.

  python3 scripts/market_risk_backtest.py --list
  python3 scripts/market_risk_backtest.py --scenario covid2020 --json
  python3 scripts/market_risk_backtest.py --all --report    # writes docs/audits/MARKET_RISK_ENGINE_BACKTEST_<date>.md

Advisory and offline: no database, no network, no sends. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import contract as c  # noqa: E402
from scripts.lib.market_risk.fixture_reader import ET, FIXTURE_ROOT, FixtureReader, close_instant  # noqa: E402

HOLDOUT_START = "2026-01-01"  # out-of-sample: thresholds are calibrated on 2016-2025 only (market_risk_calibrate.py)
OPEN_EVAL = time(9, 31)  # one evaluation just after each open: the overnight gap is known from 09:30 (design §5.14)

SCENARIOS_PATH = FIXTURE_ROOT / "scenarios.json"
SEVERITY = {t: i for i, t in enumerate(c.TIERS)}  # GREEN < NONE < BLUE < YELLOW < ORANGE < RED
ENGINE_CORE = ("scoring",)
DAILY_CATEGORIES = ("technical", "volatility", "cross_asset", "macro_credit", "breadth")


@dataclass
class Engine:
    scoring: Any = None
    registry: Any = None
    analogs: Any = None
    categories: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def ready(self, needed: tuple[str, ...] = DAILY_CATEGORIES) -> bool:
        return not self.pending(needed)

    def pending(self, needed: tuple[str, ...] = DAILY_CATEGORIES) -> list[str]:
        miss = [m for m in self.missing if m.startswith("scoring")]
        if self.registry is None:
            miss += [f"categories.{n}" for n in needed if n not in self.categories]
        return miss


def _try(mod: str) -> Any:
    try:
        return importlib.import_module(mod)
    except ImportError:
        return None


def load_engine() -> Engine:
    e = Engine()
    e.scoring = _try("scripts.lib.market_risk.scoring")
    if e.scoring is None:
        e.missing.append("scoring")
    elif not hasattr(e.scoring, "compose"):
        e.missing.append("scoring.compose")
    e.registry = _try("scripts.lib.market_risk.registry")
    if e.registry is not None and not hasattr(e.registry, "evaluate_all"):
        e.registry = None
    e.analogs = _try("scripts.lib.market_risk.analogs")
    for name in c.CATEGORIES:
        m = _try(f"scripts.lib.market_risk.categories.{name}")
        if m is not None and hasattr(m, "evaluate"):
            e.categories[name] = m
        else:
            e.missing.append(f"categories.{name}")
    return e


def load_scenarios(path: Path = SCENARIOS_PATH) -> dict[str, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["scenarios"]}


def load_policy() -> dict[str, Any]:
    from scripts.lib.market_risk.policy import load_policy as _lp

    return _lp()


def observe(engine: Engine, ctx: c.EvalContext, *, drop: tuple[str, ...] = ()) -> list[c.CategoryObservation]:
    """All nine categories; an absent module or a dropped category is UNKNOWN (never zero, never skipped)."""
    if engine.registry is not None:
        obs = list(engine.registry.evaluate_all(ctx))
    else:
        obs = []
        for name in c.CATEGORIES:
            mod = engine.categories.get(name)
            obs.append(mod.evaluate(ctx) if mod else c.unknown(name, ctx.now, "module not built"))
    return [c.unknown(o.category, ctx.now, "dropped for this replay") if o.category in drop else o for o in obs]


def evaluate_at(
    engine: Engine,
    reader: FixtureReader,
    policy: dict,
    now: datetime,
    *,
    session: str,
    prior: Any = None,
    portfolio: c.PortfolioContext | None = None,
    analogs: bool = True,
    drop: tuple[str, ...] = (),
) -> c.RiskAssessment:
    ctx = c.EvalContext(
        now=now, reader=reader, policy=policy, session=session, extras={"analogs_enabled": analogs, "replay": True}
    )
    a = engine.scoring.compose(observe(engine, ctx, drop=drop), policy, prior=prior, now=now)
    if portfolio is not None and hasattr(engine.scoring, "apply_uplift"):
        a = engine.scoring.apply_uplift(a, portfolio, policy)
    from scripts.lib.market_risk import explain as _explain  # same seam as scripts/market_risk_evaluate.py

    if "points" in (a.hysteresis or {}):  # the real scoring module; stub engines in tests carry no attribution
        a = _explain.explain(a, policy)
    if analogs and engine.analogs is not None and hasattr(engine.analogs, "find"):
        a.analogs = list(engine.analogs.find(a, reader=reader, now=now))
    c.assert_no_behavior_fields(a.to_dict())
    return a


def run_scenario(
    scenario: dict[str, Any],
    *,
    engine: Engine | None = None,
    policy: dict | None = None,
    reader: FixtureReader | None = None,
    extra_times: list[datetime] | None = None,
    portfolio: c.PortfolioContext | None = None,
    analogs: bool = True,
    drop: tuple[str, ...] = (),
    open_evaluations: bool = True,
) -> dict[str, Any]:
    engine = engine or load_engine()
    if engine.pending():
        raise RuntimeError(f"engine modules pending: {', '.join(engine.pending())}")
    policy = policy if policy is not None else load_policy()
    if reader is None:
        overlay = FIXTURE_ROOT / scenario["overlay"] if scenario.get("overlay") else None
        reader = FixtureReader(FIXTURE_ROOT, overlay=overlay)
    start, end = date.fromisoformat(scenario["start"]), date.fromisoformat(scenario["end"])
    sessions = reader.sessions(start=start, end=end)
    times = [(close_instant(d), "close") for d in sessions]
    if open_evaluations:
        times += [(datetime.combine(d, OPEN_EVAL, tzinfo=ET).astimezone(timezone.utc), "regular") for d in sessions]
    times += [(t, "afterhours" if t.astimezone(ET).time() >= time(16) else "premarket") for t in (extra_times or [])]
    times.sort(key=lambda x: x[0])
    prior = None
    timeline = []
    for now, session in times:
        a = evaluate_at(
            engine, reader, policy, now, session=session, prior=prior, portfolio=portfolio, analogs=analogs, drop=drop
        )
        prior = a
        timeline.append(
            {
                "at": now.isoformat(),
                "date": now.astimezone(ET).date().isoformat(),
                "session": session,
                "tier": a.tier,
                "market_tier": a.market_tier,
                "score": a.score,
                "market_score": a.market_score,
                "confirming": a.confirming,
                "states": {o.category: o.state for o in a.observations},
                "contributors": [(k.category, k.points) for k in a.contributors],
            }
        )
    return {"scenario": scenario["id"], "start": scenario["start"], "end": scenario["end"], "timeline": timeline}


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────
def at_least(tier: str, floor: str) -> bool:
    return SEVERITY[tier] >= SEVERITY[floor]


def first_at_least(timeline: list[dict], floor: str) -> dict | None:
    return next((t for t in timeline if at_least(t["tier"], floor)), None)


def daily_returns(reader: FixtureReader, symbol: str, start: date, end: date) -> list[tuple[str, float]]:
    rows = [r for r in reader.daily_bars([symbol], sessions=10**6, end=close_instant(end))]
    out = []
    for prev, cur in zip(rows, rows[1:]):
        if date.fromisoformat(cur["date"]) >= start and prev["close"]:
            out.append((cur["date"], (cur["close"] / prev["close"] - 1) * 100))
    return out


def drawdown_episodes(reader: FixtureReader, symbol: str, start: date, end: date, min_dd_pct: float) -> list[dict]:
    """Peak-to-trough declines of at least ``min_dd_pct`` (negative), split when price recovers the peak."""
    rows = [
        r
        for r in reader.daily_bars([symbol], sessions=10**6, end=close_instant(end))
        if date.fromisoformat(r["date"]) >= start
    ]
    eps, peak, trough = [], None, None
    for r in rows:
        if peak is None or r["close"] >= peak["close"]:
            if peak and trough and (trough["close"] / peak["close"] - 1) * 100 <= min_dd_pct:
                eps.append(
                    {
                        "peak": peak["date"],
                        "trough": trough["date"],
                        "drawdown_pct": round((trough["close"] / peak["close"] - 1) * 100, 2),
                    }
                )
            peak, trough = r, None
        elif trough is None or r["close"] < trough["close"]:
            trough = r
    if peak and trough and (trough["close"] / peak["close"] - 1) * 100 <= min_dd_pct:
        eps.append(
            {
                "peak": peak["date"],
                "trough": trough["date"],
                "drawdown_pct": round((trough["close"] / peak["close"] - 1) * 100, 2),
                "open": True,
            }
        )
    return eps


def lead_sessions(timeline: list[dict], floor: str, anchor_day: str) -> int | None:
    """Sessions between the first evaluation at ``floor``+ and ``anchor_day`` (positive = early)."""
    days = sorted({t["date"] for t in timeline})
    hit = first_at_least(timeline, floor)
    if hit is None or anchor_day not in days:
        return None
    return days.index(anchor_day) - days.index(hit["date"])


def forward_move_table(
    timeline: list[dict],
    reader: FixtureReader,
    symbol: str = "SPY",
    horizons: tuple[int, ...] = (1, 3, 5),
    thresholds: tuple[float, ...] = (1.5, 3.0),
) -> dict:
    """Empirical frequency, by tier, of an absolute ``symbol`` move ≥ threshold within N sessions (P2-T12)."""
    bars = {r["date"]: r["close"] for r in reader.daily_bars([symbol], sessions=10**6, end=datetime.now(timezone.utc))}
    days = sorted(bars)
    idx = {d: i for i, d in enumerate(days)}
    out: dict[str, dict[str, Any]] = {}
    for t in timeline:
        if t["session"] != "close" or t["date"] not in idx:
            continue
        i = idx[t["date"]]
        slot = out.setdefault(t["tier"], {"n": 0})
        slot["n"] += 1
        for h in horizons:
            if i + h >= len(days):
                continue
            path = [bars[days[j]] for j in range(i + 1, i + h + 1)]
            mx = max(abs(p / bars[days[i]] - 1) * 100 for p in path)
            down = path[-1] < bars[days[i]]
            for th in thresholds:
                k = f"P(|move|>={th}%,{h}d)"
                slot[k] = slot.get(k, 0) + (1 if mx >= th else 0)
            slot[f"P(down,{h}d)"] = slot.get(f"P(down,{h}d)", 0) + (1 if down else 0)
    for slot in out.values():
        n = slot["n"]
        for k in list(slot):
            if k != "n":
                slot[k] = round(slot[k] / n, 3)
    return out


def write_report(results: list[dict], reader: FixtureReader, path: Path) -> None:
    lines = [
        "# Market Risk Engine backtest",
        "",
        "```",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')} by scripts/market_risk_backtest.py",
        "Data:      tests/fixtures/market_risk_scenarios (public daily history; see SOURCES.json)",
        "Status:    GENERATED — do not edit by hand; re-run the harness",
        "```",
        "",
        "Each session is evaluated at 09:31 ET (after the open) and at the 16:00 ET close. Session counts are distinct",
        "dates on which the tier was reached. Lead = sessions from the first evaluation at that tier to the SPY",
        "max-drawdown trough inside the window (positive = early); '—' = not reached or no >=5% drawdown.",
        "",
        "Sample: thresholds come from scripts/market_risk_calibrate.py over 2016-2025 (IN); 2026 is held out (OUT).",
        "",
        "| Scenario | Sample | Window | Max tier | First ORANGE+ | First RED | First GREEN | SPY trough | Lead ORANGE | "
        "Lead RED | Orange sessions | Red sessions | Green sessions |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    all_tl = []
    for r in results:
        tl = r["timeline"]
        all_tl += tl
        mx = max((t["tier"] for t in tl), key=lambda x: SEVERITY[x], default="NONE")
        fo, fr = first_at_least(tl, "ORANGE"), first_at_least(tl, "RED")
        fg = next((t for t in tl if t["tier"] == "GREEN"), None)
        eps = drawdown_episodes(reader, "SPY", date.fromisoformat(r["start"]), date.fromisoformat(r["end"]), -5.0)
        trough = min(eps, key=lambda e: e["drawdown_pct"])["trough"] if eps else None
        lo = lead_sessions(tl, "ORANGE", trough) if trough else None
        lr = lead_sessions(tl, "RED", trough) if trough else None

        def days_at(tier: str) -> int:
            return len({t["date"] for t in tl if t["tier"] == tier})

        lines.append(
            f"| {r['scenario']} | {'OUT' if r['start'] >= HOLDOUT_START else 'IN'} | {r['start']}..{r['end']} | {mx} | "
            f"{fo['date'] if fo else '—'} | "
            f"{fr['date'] if fr else '—'} | {fg['date'] if fg else '—'} | {trough or '—'} | "
            f"{lo if lo is not None else '—'} | {lr if lr is not None else '—'} | "
            f"{days_at('ORANGE')} | {days_at('RED')} | {days_at('GREEN')} |"
        )
    lines += [
        "",
        "## Forward SPY move frequency by tier (all scenario sessions)",
        "",
        "```",
        json.dumps(forward_move_table(all_tl, reader), indent=1, sort_keys=True),
        "```",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--scenario")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)
    sc = load_scenarios()
    if a.list:
        for s in sc.values():
            print(f"{s['id']:20} {s['start']}..{s['end']}  expect={json.dumps(s['expect'])}")
        return 0
    engine = load_engine()
    if engine.pending():
        print(f"ENGINE PENDING — not run, no results invented. Missing: {', '.join(engine.pending())}")
        return 3
    ids = list(sc) if a.all else [a.scenario] if a.scenario else []
    if not ids:
        ap.error("--scenario ID or --all")
    results = [run_scenario(sc[i], engine=engine) for i in ids]
    if a.json:
        print(json.dumps(results, indent=1, default=str))
    else:
        for r in results:
            tiers = [t["tier"] for t in r["timeline"]]
            print(f"{r['scenario']}: {len(tiers)} evaluations, max {max(tiers, key=lambda x: SEVERITY[x])}")
    if a.report:
        out = ROOT / "docs" / "audits" / f"MARKET_RISK_ENGINE_BACKTEST_{date.today():%Y%m%d}.md"
        write_report(results, FixtureReader(FIXTURE_ROOT), out)
        print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
