#!/usr/bin/env python3
"""Market Risk Engine evaluator (DSN-20261031-market-risk-engine P2-T1).

  # what the engine says now, from the production reader (default: dry run, nothing written):
  python3 scripts/market_risk_evaluate.py
  # replay an instant from a fixture directory (one JSON list per DataReader method, e.g. fred.json):
  python3 scripts/market_risk_evaluate.py --fixture tests/fixtures/market_risk/x --as-of 2026-10-29T22:15:00Z --json
  # write the assessment (latest.json + a dated receipt) under persistent-state data/runtime/market_risk/:
  python3 scripts/market_risk_evaluate.py --apply

Advisory only (MBI_BEHAVIOR = 0). No sends here: alerting is a separate module that reads the assessment. The DB
table waits for the §7A registry grant; until then --apply writes JSON atomically. Exit codes: 0 ok, 2 no reader.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.atomic_json_store import atomic_write_json  # noqa: E402
from scripts.lib.market_risk import contract as c  # noqa: E402
from scripts.lib.market_risk import explain, registry, scoring  # noqa: E402
from scripts.lib.market_risk.policy import POLICY_PATH, load_policy  # noqa: E402

ET = ZoneInfo("America/New_York")


def state_dir() -> Path:
    root = Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")
    return root / "data" / "runtime" / "market_risk"


def session_of(now: datetime) -> str:
    et = now.astimezone(ET)
    if et.weekday() >= 5:
        return "closed"
    hm = et.hour * 60 + et.minute
    if 4 * 60 <= hm < 9 * 60 + 30:
        return "premarket"
    if 9 * 60 + 30 <= hm < 16 * 60:
        return "regular"
    if 16 * 60 <= hm < 20 * 60:
        return "afterhours"
    return "closed"


class FixtureReader:
    """Replay reader over ``<dir>/<method>.json`` lists. Rows newer than ``end`` are never returned."""

    def __init__(self, directory: Path | str):
        self.dir = Path(directory)
        if not self.dir.is_dir():
            raise FileNotFoundError(f"fixture directory not found: {self.dir}")

    def _rows(self, name: str, end: datetime | None = None, symbols: Iterable[str] | None = None) -> list[dict]:
        f = self.dir / f"{name}.json"
        rows = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        want = {s.upper() for s in symbols} if symbols else None
        out = []
        for r in rows:
            if (
                want is not None
                and str(r.get("symbol", "")).upper() not in want
                and str(r.get("series", "")).upper() not in want
            ):
                continue
            at = scoring._parse(r.get("as_of") or r.get("observed_at") or r.get("date"))
            if end is not None and at is not None and at > end:
                continue
            out.append(r)
        return out

    def quotes(self, symbols, *, start, end):
        return [r for r in self._rows("quotes", end, symbols) if (scoring._parse(r.get("as_of")) or end) >= start]

    def daily_bars(self, symbols, *, sessions, end):
        return self._rows("daily_bars", end, symbols)

    def regime_indicators(self, *, end):
        return self._rows("regime_indicators", end)

    def fred(self, series, *, observations, end):
        return self._rows("fred", end, series)

    def option_snapshots(self, symbols, *, sessions, end):
        return self._rows("option_snapshots", end, symbols)

    def sector_states(self, *, end):
        return self._rows("sector_states", end)

    def earnings_calendar(self, *, start, end):
        return self._rows("earnings_calendar")

    def macro_calendar(self, *, start, end):
        return self._rows("macro_calendar")


def production_reader() -> Any:
    try:
        from scripts.lib.market_risk.reader import PgReader  # builder H
    except ImportError as exc:
        raise SystemExit(
            f"market_risk_evaluate: production reader scripts.lib.market_risk.reader.PgReader is not available ({exc}); "
            "use --fixture DIR for a replay. Refusing to evaluate on an empty reader."
        ) from None
    return PgReader()


def evaluate(now: datetime, reader: Any, policy: dict, prior: dict | None, portfolio: c.PortfolioContext | None = None):
    ctx = c.EvalContext(now=now, reader=reader, policy=policy, session=session_of(now))
    obs = registry.evaluate_all(ctx)
    a = scoring.compose(obs, policy, prior=prior, now=now)
    a = scoring.apply_uplift(a, portfolio, policy)
    a = explain.explain(a, policy)
    return a


def portfolio_context(now: datetime) -> c.PortfolioContext | None:
    """Exposure-aware severity input from the production stores; any failure is an honest unknown, never a crash."""
    try:
        from scripts.lib.market_risk import exposure

        return exposure.context_from_production(now=now)
    except Exception as exc:  # noqa: BLE001 — a missing book is UNKNOWN vulnerability, reported in the card
        print(f"market_risk_evaluate: portfolio context unavailable ({type(exc).__name__}: {exc})", file=sys.stderr)
        return c.PortfolioContext(vulnerability=None, note=f"portfolio unavailable: {type(exc).__name__}")


def run_cycle(
    now: datetime,
    reader: Any,
    policy: dict,
    prior: dict | None,
    *,
    apply: bool,
    portfolio: c.PortfolioContext | None = None,
    episodes_path: Path | None = None,
    call_model: Any = None,
) -> dict[str, Any]:
    """One full evaluation: categories -> compose -> uplift -> explain -> alert intent -> episode -> repeats -> curation
    -> send. Dry run computes every step against a scratch copy of the episode store and sends nothing."""
    import shutil
    import tempfile

    from scripts.lib.market_risk import alerts, escalation

    a = evaluate(now, reader, policy, prior, portfolio)
    doc = a.to_dict()
    real_store = episodes_path or escalation.store_path()
    store = real_store
    if not apply:  # never touch the live episode ledger in a dry run
        tmpdir = Path(tempfile.mkdtemp(prefix="mre-dry-"))
        store = tmpdir / "episodes.json"
        if real_store.exists():
            shutil.copy2(real_store, store)
    out: dict[str, Any] = {"assessment": doc, "object": a, "mode": "apply" if apply else "dry_run", "sends": []}
    ep = escalation.observe(doc, now=now, policy=policy, path=store)
    out["episode_event"] = ep["event"]
    out["episode_id"] = (ep.get("episode") or {}).get("id")
    pending: list[tuple[str, dict, str, str | None]] = []
    intent = alerts.intent_for(doc, prior, policy)
    if intent:
        pending.append((alerts.render(doc), intent, "initial", out["episode_id"]))
    for rep in escalation.due_repeats(now=now, policy=policy, path=store):
        if intent and rep["episode_id"] == out["episode_id"] and ep["event"] in ("opened", "upgraded", "reopened"):
            continue  # the initial card of this episode is already in this cycle
        rintent = {
            "priority": "P1",
            "dedupe_minutes": 0,
            "dedupe_key": f"market_risk:repeat:{rep['episode_id']}:{rep['repeat_number']}",
            "tier": rep["tier"],
            "transition": rep["kind"],
        }
        pending.append((alerts.render(doc, repeat=rep), rintent, rep["kind"], rep["episode_id"]))
    for text, it, kind, ep_id in pending:
        cur = _curate(text, doc, call_model=call_model, live=apply)
        res = alerts.deliver(cur["text"], it, policy, dry_run=not apply)
        res.update(kind=kind, curated=cur["curated"], curation_reason=cur["reason"], text=cur["text"])
        if ep_id:
            escalation.record_send(ep_id, now=now, kind=kind, ok=bool(res.get("sent")) or not apply, path=store)
        out["sends"].append(res)
    out["stalled"] = escalation.stalled(now=now, policy=policy, path=store)
    return out


def _curate(text: str, doc: dict, *, call_model: Any, live: bool) -> dict[str, Any]:
    """LLM may rephrase only the why sentence (curation.py); a dry run never calls a model unless one is injected."""
    from scripts.lib.market_risk import curation

    if not live and call_model is None:
        return {"text": text, "curated": False, "reason": "dry run: model not called"}
    try:
        return curation.curate(text, doc, call_model=call_model)
    except Exception as exc:  # noqa: BLE001 — curation can never block a card; the deterministic text is sent
        print(f"market_risk_evaluate: curation failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return {"text": text, "curated": False, "reason": f"curation error: {type(exc).__name__}"}


def _read_prior(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write latest.json + dated receipt")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    ap.add_argument("--as-of", help="ISO-8601 instant to evaluate (replay)")
    ap.add_argument("--fixture", help="fixture directory for a replay reader")
    ap.add_argument("--prior", help="prior assessment JSON (default: latest.json when not replaying)")
    ap.add_argument("--policy", default=str(POLICY_PATH))
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--no-portfolio", action="store_true", help="market tier only (no exposure uplift)")
    a = ap.parse_args(argv)
    apply = a.apply and not a.dry_run
    now = scoring._parse(a.as_of) if a.as_of else datetime.now(timezone.utc)
    if now is None:
        ap.error(f"--as-of {a.as_of!r} is not ISO-8601")
    policy = load_policy(a.policy)
    try:
        reader = FixtureReader(a.fixture) if a.fixture else production_reader()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    prior_path = Path(a.prior) if a.prior else (None if a.as_of else state_dir() / "latest.json")
    prior = _read_prior(prior_path) if prior_path else None
    portfolio = None if a.no_portfolio else portfolio_context(now)
    cycle = run_cycle(now, reader, policy, prior, apply=apply, portfolio=portfolio)
    doc = cycle["assessment"]
    assessment = cycle["object"]
    doc["cycle"] = {k: v for k, v in cycle.items() if k not in ("assessment", "object")}
    doc["mode"] = "apply" if apply else "dry_run"
    doc["session"] = session_of(now)
    if apply:
        d = state_dir()
        stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        atomic_write_json(d / "receipts" / f"{stamp}.json", doc)
        atomic_write_json(d / "latest.json", doc)
        doc["written"] = str(d / "latest.json")
    if a.as_json:
        print(json.dumps(doc, indent=2, default=str))
    else:
        print(f"[market-risk] {doc['mode']} as_of {doc['as_of']} session {doc['session']}")
        for line in explain.card_lines(assessment):
            print("  " + line)
        for snd in doc["cycle"]["sends"]:
            print(f"  send[{snd['kind']}] {snd['intent']['priority']} sent={snd.get('sent')} curated={snd['curated']}")
            for line in snd["text"].splitlines():
                print("    | " + line)
        print(f"  episode: {doc['cycle']['episode_event']} {doc['cycle']['episode_id'] or ''}")
        print(
            f"  hysteresis: raw {assessment.hysteresis.get('raw_tier')} -> {assessment.tier} "
            f"(bootstrap={assessment.hysteresis.get('bootstrap')})"
        )
        if apply:
            print(f"  wrote {doc['written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
