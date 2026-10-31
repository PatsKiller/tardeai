#!/usr/bin/env python3
"""Market Risk Engine evaluator (DSN-20261031-market-risk-engine P2-T1).

  # what the engine says now, from the production reader (default: dry run, nothing written):
  python3 scripts/market_risk_evaluate.py
  # replay an instant from a fixture directory (one JSON list per DataReader method, e.g. fred.json):
  python3 scripts/market_risk_evaluate.py --fixture tests/fixtures/market_risk/x --as-of 2026-10-29T22:15:00Z --json
  # evaluate, write, alert: the assessment (data/runtime/market_risk/latest.json + a dated receipt), the snapshot every
  # consumer reads (data/runtime/market_risk_latest.json, market_risk_projection.SNAPSHOT_REL), then the sends:
  python3 scripts/market_risk_evaluate.py --apply

Advisory only (MBI_BEHAVIOR = 0). On --apply the assessment and the snapshot are written BEFORE any card is sent, and
every card's dedupe key is claimed in the sent-key ledger before the send, so a crash cannot re-send (review of #2362,
B5d). The DB table waits for the §7A registry grant; until then JSON is written atomically. Exit codes: 0 ok, 2 no
reader.
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
from scripts.lib.market_risk.fixture_reader import FixtureReader  # noqa: E402  (as-of-correct; review of #2362, M1)
from scripts.lib.market_risk import explain, registry, scoring  # noqa: E402
from scripts.lib.market_risk.policy import POLICY_PATH, load_policy  # noqa: E402

ET = ZoneInfo("America/New_York")


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def state_dir() -> Path:
    return state_root() / "data" / "runtime" / "market_risk"


def snapshot_path() -> Path:
    """The one file Home, Risk, the CIO and Ask-the-CIO read (market_risk_projection.SNAPSHOT_REL)."""
    from scripts.lib.market_risk_projection import SNAPSHOT_REL

    return state_root() / SNAPSHOT_REL


def persist(doc: dict, now: datetime) -> str:
    """Write the assessment (prior for the next run + dated receipt) and the consumers' snapshot. Atomic."""
    from scripts.lib.market_risk_projection import snapshot_from_assessment

    d = state_dir()
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = {k: v for k, v in doc.items() if k != "cycle"}
    atomic_write_json(d / "receipts" / f"{stamp}.json", body)
    atomic_write_json(d / "latest.json", body)
    prev = _read_prior(snapshot_path()) or {}
    hist = [h for h in (prev.get("history") or []) if isinstance(h, dict)]
    hist.append({"as_of": doc.get("as_of"), "score": doc.get("score"), "tier": doc.get("tier")})
    atomic_write_json(snapshot_path(), snapshot_from_assessment(body, history=hist))
    return str(d / "latest.json")


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
    attach_precision(a, ctx, policy)
    if portfolio is not None and os.environ.get("MRE_BOOK_PRECISION", "1") == "1":
        try:  # live only: the backtests and replays pass no portfolio context
            from scripts.lib.market_risk import book_precision
            from scripts.lib.market_risk.reader import _default_conn

            book_precision.attach(a, now=now, reader=reader, policy=policy, prior=prior, conn_factory=_default_conn)
        except Exception as exc:  # noqa: BLE001 — the book layer is additive; the tier stands without it
            a.positions = {"_note": f"book precision unavailable: {type(exc).__name__}: {exc}"}
        try:  # the re-entry watch is independent of the held book: a failure here never hides the stances
            from scripts.lib.market_risk import book_precision
            from scripts.lib.market_risk.reader import _default_conn

            book_precision.reentry_watch_block(
                a, now=now, reader=reader, policy=policy, prior=prior, conn_factory=_default_conn
            )
        except Exception as exc:  # noqa: BLE001
            a.reentry_watch = {"_note": f"re-entry watch unavailable: {type(exc).__name__}: {exc}"}
    return a


def attach_precision(a: Any, ctx: c.EvalContext, policy: dict) -> None:
    """Sector attribution, shock type and the heat map (precision PR). A failure here is reported in the block and never
    blocks the tier: the market assessment stands on its own."""
    from scripts.lib.market_risk import sectors, shock_type

    try:
        block = sectors.measure(ctx)
        a.sectors = block
        a.shock_type = shock_type.classify(block, [o.to_dict() for o in a.observations], policy)
        a.heatmap = sectors.heatmap(block)
    except Exception as exc:  # noqa: BLE001 — precision is additive; an error is an honest unknown in the payload
        a.sectors = {"state": "UNKNOWN", "reason_unknown": f"{type(exc).__name__}: {exc}"}
        a.shock_type = {"class": "UNKNOWN", "reason_unknown": f"{type(exc).__name__}: {exc}"}


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
    on_assessed: Any = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """One full evaluation: categories -> compose -> uplift -> explain -> ``on_assessed`` (apply: persist the prior
    and the snapshot BEFORE any send) -> alert intent -> episode -> repeats -> curation -> claim key -> send. Dry run
    computes every step against scratch copies of the episode store and sent-key ledger and sends nothing."""
    import shutil
    import tempfile

    from scripts.lib.market_risk import alerts, escalation

    a = evaluate(now, reader, policy, prior, portfolio)
    doc = a.to_dict()
    if apply and on_assessed is not None:
        on_assessed(doc)
    real_store = episodes_path or escalation.store_path()
    real_ledger = ledger_path or alerts.sent_ledger_path()
    store, ledger, tmpdir = real_store, real_ledger, None
    if not apply:  # never touch the live episode ledger or sent keys in a dry run; scratch on disk, removed after
        base = os.environ.get("TMPDIR") or str(Path.home() / ".cache" / "agent-tmp")
        Path(base).mkdir(parents=True, exist_ok=True)
        tmpdir = Path(tempfile.mkdtemp(prefix="mre-dry-", dir=base))
        store, ledger = tmpdir / "episodes.json", tmpdir / "sent_keys.json"
        for src, dst in ((real_store, store), (real_ledger, ledger)):
            if src.exists():
                shutil.copy2(src, dst)
    try:
        return _cycle(now, doc, a, prior, policy, apply, store, ledger, call_model)
    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _cycle(now, doc, a, prior, policy, apply, store, ledger, call_model) -> dict[str, Any]:
    from scripts.lib.market_risk import alerts, escalation

    esc_cfg = policy.get("escalation") or {}
    out: dict[str, Any] = {"assessment": doc, "object": a, "mode": "apply" if apply else "dry_run", "sends": []}
    ep = escalation.observe(doc, now=now, policy=policy, path=store)
    out["episode_event"] = ep["event"]
    out["episode_id"] = (ep.get("episode") or {}).get("id")
    pending: list[tuple[str, dict, str, str | None]] = []
    intent = alerts.intent_for(doc, prior, policy)
    if intent:
        if out["episode_id"] and ep["event"] in ("opened", "upgraded", "reopened"):
            intent["dedupe_key"] = f"{intent['dedupe_key']}:{out['episode_id']}"  # once per episode transition
        pending.append((alerts.render(doc), intent, "initial", out["episode_id"]))
    for rep in escalation.due_repeats(now=now, policy=policy, path=store):
        if intent and rep["episode_id"] == out["episode_id"] and ep["event"] in ("opened", "upgraded", "reopened"):
            continue  # the initial card of this episode is already in this cycle
        rintent = {
            "priority": str(esc_cfg.get("repeat_priority") or "P1"),
            "dedupe_minutes": int(esc_cfg.get("repeat_dedupe_minutes") or 0),
            "dedupe_key": f"market_risk:repeat:{rep['episode_id']}:{rep['repeat_number']}",
            "tier": rep["tier"],
            "transition": rep["kind"],
        }
        pending.append((alerts.render(doc, repeat=rep), rintent, rep["kind"], rep["episode_id"]))
    # RE-ENTRY WATCH: one P2 card when a watched symbol flips to RE_ENTER (dedupe per symbol and exit date)
    from scripts.lib.market_risk import reentry_watch as _rw

    prior_watch = (prior or {}).get("reentry_watch") or {}
    for sym, w in (doc.get("reentry_watch") or {}).items():
        if str(sym).startswith("_") or not isinstance(w, dict) or w.get("status") != "RE_ENTER":
            continue
        if (prior_watch.get(sym) or {}).get("status") == "RE_ENTER":
            continue
        rcfg = policy.get("reentry_watch") or {}
        pending.append(
            (
                _rw.render(w),
                {
                    "priority": str(rcfg.get("card_priority") or "P2"),
                    "dedupe_minutes": int(rcfg.get("card_dedupe_minutes") or 1440),
                    "dedupe_key": f"market_risk:reentry:{sym}:{w.get('exit_date')}",
                    "tier": "REENTRY",
                    "transition": "reentry",
                },
                "reentry",
                None,
            )
        )
    for text, it, kind, ep_id in pending:
        cur = _curate(text, doc, call_model=call_model, live=apply)
        res = alerts.deliver(cur["text"], it, policy, dry_run=not apply, now=now, ledger=ledger)
        res.update(kind=kind, curated=cur["curated"], curation_reason=cur["reason"], text=cur["text"])
        if ep_id and not res.get("deduped"):
            escalation.record_send(
                ep_id,
                now=now,
                kind=kind,
                ok=bool(res.get("sent")) or not apply,
                path=store,
                policy_escalation=esc_cfg,
            )
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
    """The previous assessment, or None. A torn file is treated as "no prior" (bootstrap), logged, never a crash."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        print(f"market_risk_evaluate: prior {path} unreadable ({type(exc).__name__}); bootstrapping", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write latest.json + dated receipt")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    ap.add_argument("--as-of", help="ISO-8601 instant to evaluate (replay)")
    ap.add_argument("--fixture", help="fixture directory for a replay reader (scripts/lib/market_risk/fixture_reader)")
    ap.add_argument("--overlay", help="overlay fixture directory (e.g. tests/fixtures/market_risk_scenarios/oct2026)")
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
        reader = FixtureReader(a.fixture, overlay=a.overlay) if a.fixture else production_reader()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    prior_path = Path(a.prior) if a.prior else (None if a.as_of else state_dir() / "latest.json")
    prior = _read_prior(prior_path) if prior_path else None
    portfolio = None if a.no_portfolio else portfolio_context(now)
    written: dict[str, str] = {}

    def _persist(d: dict) -> None:
        d["mode"] = "apply"
        d["session"] = session_of(now)
        written["latest"] = persist(d, now)

    cycle = run_cycle(now, reader, policy, prior, apply=apply, portfolio=portfolio, on_assessed=_persist)
    doc = cycle["assessment"]
    assessment = cycle["object"]
    doc["cycle"] = {k: v for k, v in cycle.items() if k not in ("assessment", "object")}
    doc["mode"] = "apply" if apply else "dry_run"
    doc["session"] = session_of(now)
    if apply:
        doc["written"] = written.get("latest") or str(state_dir() / "latest.json")
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
