#!/usr/bin/env python3
"""Market Risk Engine evaluator (DSN-20261031-market-risk-engine P2-T1).

  # what the engine says now, from the production reader (default: dry run, nothing written):
  python3 scripts/market_risk_evaluate.py
  # replay an instant from a fixture directory (one JSON list per DataReader method, e.g. fred.json):
  python3 scripts/market_risk_evaluate.py --fixture tests/fixtures/market_risk/x --as-of 2026-10-29T22:15:00Z --json
  # evaluate, write, alert: the assessment (data/runtime/market_risk/latest.json + a dated receipt), the snapshot every
  # consumer reads (data/runtime/market_risk_latest.json, market_risk_projection.SNAPSHOT_REL), then the sends:
  python3 scripts/market_risk_evaluate.py --apply
  # shadow: evaluate and write the receipt + the snapshot Home/API read, with no alert path at all:
  python3 scripts/market_risk_evaluate.py --shadow

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


SHADOW_PRIOR = "shadow_latest.json"


def persist(doc: dict, now: datetime, *, shadow: bool = False) -> str:
    """Write the assessment (prior for the next run + dated receipt) and the consumers' snapshot. Atomic.

    ``shadow``: the receipt is ``<stamp>-shadow.json`` and ``shadow_latest.json`` is both the shadow prior and what
    the API serves when no live snapshot exists. A shadow run never becomes the live prior and never overwrites the
    live snapshot (the first live --apply still announces its tier as a transition)."""
    from scripts.lib.market_risk_projection import snapshot_from_assessment

    d = state_dir()
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = {k: v for k, v in doc.items() if k != "cycle"}
    atomic_write_json(d / "receipts" / f"{stamp}{'-shadow' if shadow else ''}.json", body)
    atomic_write_json(d / (SHADOW_PRIOR if shadow else "latest.json"), body)
    if shadow:
        # never the snapshot Home/API/CIO read (review of #2425): the API serves the live snapshot when one exists
        # and falls back to shadow_latest.json, labelled, only when none does (market_risk_projection.load_snapshot)
        return str(d / SHADOW_PRIOR)
    prev = _read_prior(snapshot_path()) or {}
    hist = [h for h in (prev.get("history") or []) if isinstance(h, dict) and h.get("as_of") != doc.get("as_of")]
    hist.append(
        {
            "as_of": doc.get("as_of"),
            "score": doc.get("score"),
            "tier": doc.get("tier"),
            "mode": "shadow" if shadow else "live",
        }
    )
    hist.sort(key=lambda h: scoring._parse(h.get("as_of")) or datetime.min.replace(tzinfo=timezone.utc))
    atomic_write_json(snapshot_path(), snapshot_from_assessment(body, history=hist))  # carries mode: live|shadow
    return str(d / (SHADOW_PRIOR if shadow else "latest.json"))


RUN_RECEIPT_NAME = "run_last.json"


def run_receipt_path() -> Path:
    """``data/runtime/market_risk/run_last.json``: written by EVERY scheduled run, dry or apply (not by a replay), so
    the lane's output signal and the stalled-escalation check see the evaluator alive during the shadow period."""
    return state_dir() / RUN_RECEIPT_NAME


def write_run_receipt(doc: dict, *, started: datetime, finished: datetime) -> str:
    receipt = {
        "schema": "MarketRiskRunReceipt@v1",
        "lane_id": "market-risk-evaluate",
        "started_at": started.astimezone(timezone.utc).isoformat(),
        "finished_at": finished.astimezone(timezone.utc).isoformat(),
        "mode": doc.get("mode"),
        "session": doc.get("session"),
        "as_of": doc.get("as_of"),
        "tier": doc.get("tier"),
        "score": doc.get("score"),
        "sends": len(((doc.get("cycle") or {}).get("sends")) or []),
    }
    atomic_write_json(run_receipt_path(), receipt)
    return str(run_receipt_path())


def session_of(now: datetime) -> str:
    """US equity session of ``now`` (sessions.session_label): premarket / regular / afterhours / overnight (the 24/5
    session, Sunday 20:00 to Friday 04:00 ET) / closed. Weekends and exchange holidays are ``closed`` outside the
    overnight session, and an early-close day's regular session ends at its early close (review of #2383)."""
    from scripts.lib.market_risk import sessions

    return sessions.session_label(now)


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
        try:  # B3: per-session {tier, sectors} history carried in the assessment, read by the multi-session conditions
            from scripts.lib.market_risk import book_precision

            d0 = a.to_dict()
            a.session_history = book_precision.session_history(
                prior, now=now, tier=d0.get("tier"), sectors_block=d0.get("sectors")
            )
        except Exception as exc:  # noqa: BLE001 — additive; an empty history only delays the multi-session conditions
            print(f"market_risk_evaluate: session history unavailable ({type(exc).__name__}: {exc})", file=sys.stderr)
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
    try:  # rotation advisor: durable leadership turns (additive; never blocks the tier)
        from scripts.lib.market_risk import leadership

        a.leadership = leadership.measure(ctx)
    except Exception as exc:  # noqa: BLE001 — additive layer; an error is an honest unknown in the payload
        a.leadership = {"state": "UNKNOWN", "reason_unknown": f"{type(exc).__name__}: {exc}"}


def portfolio_context(now: datetime) -> c.PortfolioContext | None:
    """Exposure-aware severity input from the production stores; any failure is an honest unknown, never a crash."""
    try:
        from scripts.lib.market_risk import exposure

        return exposure.context_from_production(now=now)
    except Exception as exc:  # noqa: BLE001 — a missing book is UNKNOWN vulnerability, reported in the card
        print(f"market_risk_evaluate: portfolio context unavailable ({type(exc).__name__}: {exc})", file=sys.stderr)
        return c.PortfolioContext(vulnerability=None, note=f"portfolio unavailable: {type(exc).__name__}")


def _prior_from_open_episode(prior: dict | None, store: Path) -> dict | None:
    """An open episode in the ledger means the operator was already alerted: never a first reading (review of
    PR 2431 round 6, FIX 2). With no prior (latest.json, the snapshot and the receipts all lost), the open episode's
    tier is the prior, so the tier is held, the CARRIED-ONLY mark is never set and the episode's repeats keep
    draining. A torn ledger is left to escalation.observe, which quarantines it."""
    if prior:
        return prior
    from scripts.lib.market_risk import escalation

    try:
        ep = escalation.open_episode(escalation.load(store))
    except Exception:  # noqa: BLE001 — EpisodeStoreCorrupt or unreadable: observe() handles and reports it
        return prior
    if not ep or ep.get("tier") not in ("ORANGE", "RED"):
        return prior
    return {"tier": ep["tier"], "hysteresis": {}, "prior_source": f"open episode {ep.get('id')}"}


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

    prior = _prior_from_open_episode(prior, episodes_path or escalation.store_path())
    a = evaluate(now, reader, policy, prior, portfolio)
    doc = a.to_dict()
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
        return _cycle(now, doc, a, prior, policy, apply, store, ledger, call_model, on_assessed)
    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _cycle(now, doc, a, prior, policy, apply, store, ledger, call_model, on_assessed=None) -> dict[str, Any]:
    """Crash-safe order (review of #2383, B5d):

    1. ``observe`` folds the evaluation into the episode store;
    2. every card this cycle owes (the transition card and any due repeat) is queued in the outbox (``outbox_put``);
    3. only then are the prior and the snapshot persisted (``on_assessed``) — a crash before this point leaves the
       prior unpersisted, so the next cycle recomputes the same transition and queues the same deterministic key;
    4. the outbox is drained: pending and stale-claimed cards are sent, and sent cards are recorded in the episode
       store idempotently (``record_send(key=...)``), so a crash at any step delays a card by one cycle at most and
       never loses or wedges it. A crash between the transport accepting a card and ``settle`` can send it twice;
       at-least-once is the chosen trade for a RED alarm."""
    from scripts.lib.market_risk import alerts, escalation

    esc_cfg = policy.get("escalation") or {}
    ttl = float(esc_cfg.get("claim_ttl_min") or 10)
    out: dict[str, Any] = {"assessment": doc, "object": a, "mode": "apply" if apply else "dry_run", "sends": []}
    hy = doc.get("hysteresis") or {}
    # a first reading, or a tier that rests only on data carried across a closure (CARRIED-ONLY, PR 2431), never pages
    bootstrap = bool(hy.get("bootstrap")) or bool(hy.get("carried_only"))
    if bootstrap:
        # a first reading never pages (review of PR 2425 round 4, finding 2): no episode opens (an ORANGE/RED episode
        # schedules P1 repeats) and no repeat is drained this cycle; the next evaluation, with this one as its prior,
        # opens the episode if the tier holds
        ep: dict[str, Any] = {
            "event": "carried_only_no_episode" if hy.get("carried_only") else "bootstrap_no_episode",
            "episode": None,
        }
    else:
        ep = escalation.observe(doc, now=now, policy=policy, path=store)
    out["episode_event"] = ep["event"]
    out["episode_id"] = (ep.get("episode") or {}).get("id")
    intent = alerts.intent_for(doc, prior, policy)
    if intent:
        if out["episode_id"]:
            intent["dedupe_key"] = f"{intent['dedupe_key']}:{out['episode_id']}"  # deterministic for this episode
        alerts.outbox_put(
            {
                "key": intent["dedupe_key"],
                "text": alerts.render(doc),
                "intent": intent,
                "kind": "initial",
                "episode_id": out["episode_id"],
            },
            now=now,
            path=ledger,
        )
    for rep in [] if bootstrap else escalation.due_repeats(now=now, policy=policy, path=store):
        if intent and rep["episode_id"] == out["episode_id"] and ep["event"] in ("opened", "upgraded", "reopened"):
            continue  # the initial card of this episode is already queued this cycle
        rintent = {
            "priority": str(esc_cfg.get("repeat_priority") or "P1"),
            "dedupe_minutes": int(esc_cfg.get("repeat_dedupe_minutes") or 0),
            "dedupe_key": f"market_risk:repeat:{rep['episode_id']}:{rep['repeat_number']}",
            "tier": rep["tier"],
            "transition": rep["kind"],
        }
        alerts.outbox_put(
            {
                "key": rintent["dedupe_key"],
                "text": alerts.render(doc, repeat=rep),
                "intent": rintent,
                "kind": rep["kind"],
                "episode_id": rep["episode_id"],
            },
            now=now,
            path=ledger,
        )
    # RE-ENTRY WATCH: one P2 card when a watched symbol flips to RE_ENTER (dedupe per symbol and exit date). Queued in
    # the same outbox as every other card (review round 3, H5), never curated, never tied to an episode.
    from scripts.lib.market_risk import reentry_watch as _rw

    prior_watch = (prior or {}).get("reentry_watch") or {}
    rcfg = policy.get("reentry_watch") or {}
    for sym, w in (doc.get("reentry_watch") or {}).items():
        if str(sym).startswith("_") or not isinstance(w, dict) or w.get("status") != "RE_ENTER":
            continue
        if (prior_watch.get(sym) or {}).get("status") == "RE_ENTER":
            continue
        rkey = f"market_risk:reentry:{sym}:{w.get('exit_date')}"
        alerts.outbox_put(
            {
                "key": rkey,
                "text": _rw.render(w),
                "intent": {
                    "priority": str(rcfg.get("card_priority") or "P2"),
                    "dedupe_minutes": int(rcfg.get("card_dedupe_minutes") or 1440),
                    "dedupe_key": rkey,
                    "tier": "REENTRY",
                    "transition": "reentry",
                },
                "kind": "reentry",
                "episode_id": None,
            },
            now=now,
            path=ledger,
        )
    if apply and on_assessed is not None:
        on_assessed(doc)
    for ent in alerts.outbox_due(now=now, path=ledger, claim_ttl_min=ttl):
        try:  # one bad entry never stops the others or crashes the cycle (review round 3, H2)
            res = _drain_one(ent, now, doc, policy, apply, store, ledger, call_model, esc_cfg)
        except Exception as exc:  # noqa: BLE001 — logged and reported; the entry stays queued for the next cycle
            print(
                f"market_risk_evaluate: outbox entry {ent.get('key')} failed ({type(exc).__name__}: {exc})",
                file=sys.stderr,
            )
            res = {
                "key": ent.get("key"),
                "kind": ent.get("kind"),
                "sent": False,
                "error": f"drain raised {type(exc).__name__}",
            }
        if res is not None:
            out["sends"].append(res)
    out["stalled"] = escalation.stalled(now=now, policy=policy, path=store)
    return out


def _drain_one(ent, now, doc, policy, apply, store, ledger, call_model, esc_cfg) -> dict[str, Any] | None:
    """Send or reconcile one outbox entry. Returns the send result, or None when the entry was only reconciled."""
    from scripts.lib.market_risk import alerts, escalation

    key, ep_id, kind = ent["key"], ent.get("episode_id"), ent.get("kind") or "initial"
    data = escalation.load(store) if store.exists() else {"episodes": []}
    episodes = {e.get("id"): e for e in data.get("episodes") or []}
    current = escalation.open_episode(data)
    orphan = bool(ep_id) and ep_id not in episodes
    if ent.get("status") == "sent":  # sent before a crash, never recorded: record it now, idempotently
        if ep_id and not orphan:
            escalation.record_send(
                ep_id,
                now=now,
                kind=kind,
                ok=True,
                path=store,
                policy_escalation=esc_cfg,
                key=key,
                detail="recorded after restart",
            )
            alerts.mark_recorded(key, path=ledger)
        else:
            alerts.mark_superseded(key, path=ledger, reason="episode no longer in the ledger")
        return None
    if kind not in ("initial", "reentry"):
        # a repeat ("acknowledgment required") is owed only while its episode is the OPEN one (H4): an ACK, a
        # resolution or a replaced ledger retires it instead of paging the operator after they acknowledged
        ep = episodes.get(ep_id)
        if ep is None or current is None or current.get("id") != ep_id or ep.get("status") != "OPEN":
            why = "episode acknowledged or closed" if ep is not None else "episode no longer in the ledger"
            alerts.mark_superseded(key, path=ledger, reason=why)
            return None
    if kind == "reentry":  # deterministic advisory card: never curated
        cur = {"text": ent["text"], "curated": False, "reason": "re-entry card is deterministic"}
    else:
        cur = _curate(ent["text"], doc, call_model=call_model, live=apply)
    res = alerts.deliver(
        cur["text"], dict(ent["intent"], dedupe_key=key), policy, dry_run=not apply, now=now, ledger=ledger
    )
    res.update(kind=kind, curated=cur["curated"], curation_reason=cur["reason"], text=cur["text"], key=key)
    if not apply and not res.get("deduped"):
        alerts.settle(key, True, path=ledger, now=now)  # scratch ledger only: a dry run behaves as if delivered
    if res.get("deduped"):
        return res
    delivered = bool(res.get("sent")) or not apply
    if ep_id and not orphan:
        escalation.record_send(
            ep_id,
            now=now,
            kind=kind,
            ok=delivered,
            path=store,
            policy_escalation=esc_cfg,
            key=key if delivered else None,
            detail="" if delivered else str(res.get("error") or ""),
        )
        if delivered:
            alerts.mark_recorded(key, path=ledger)
    elif delivered and orphan:
        alerts.mark_superseded(key, path=ledger, reason="sent; its episode was replaced (torn ledger)")
    return res


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


def _shadow(
    now: datetime, reader: Any, policy: dict, prior: dict | None, portfolio, *, as_json: bool, replay: bool = False
) -> int:
    """--shadow: evaluate, then persist the receipt, the shadow prior and the consumers' snapshot. The alert path
    (outbox, episode store, sent-key ledger, curation, send_telegram) is never imported or called."""
    assessment = evaluate(now, reader, policy, prior, portfolio)
    doc = assessment.to_dict()
    doc["mode"] = "shadow"
    doc["session"] = session_of(now)
    doc["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    doc["replay"] = replay
    if replay:
        # a replay (--as-of) is never what the market looks like now: it writes only its own receipt, never the
        # snapshot Home/API/CIO read, its history, or the shadow prior (review of #2415, F3)
        stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = state_dir() / "receipts" / f"{stamp}-shadow-replay.json"
        atomic_write_json(path, doc)
        doc["written"], doc["snapshot"] = str(path), None
    else:
        doc["written"] = persist(doc, now, shadow=True)
        doc["snapshot"] = None  # served from shadow_latest.json only while no live snapshot exists
    if as_json:
        print(json.dumps(doc, indent=2, default=str))
    else:
        print(f"[market-risk] shadow as_of {doc['as_of']} session {doc['session']} (no alert path)")
        for line in explain.card_lines(assessment):
            print("  " + line)
        print(
            f"  hysteresis: raw {assessment.hysteresis.get('raw_tier')} -> {assessment.tier} "
            f"(bootstrap={assessment.hysteresis.get('bootstrap')})"
        )
        print(
            f"  wrote {doc['written']}"
            + (" (replay: receipt only)" if replay else " (the live snapshot is never touched by a shadow run)")
        )
    return 0


def _receipt_time(r: dict, name: str) -> datetime | None:
    """When a receipt was evaluated: its ``evaluated_at`` (wall clock, written since PR 2431), else its ``as_of``,
    else (a receipt with neither) the stamp in its file name."""
    t = scoring._parse(r.get("evaluated_at")) or scoring._parse(r.get("as_of"))
    if t is None:
        try:
            t = datetime.strptime(name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return t


def _resolve_prior(path: Path, *, shadow: bool, now: datetime | None = None) -> dict | None:
    """The previous assessment.

    A first reading (bootstrap, None) only when there is no trace of an earlier evaluation at all: ``path`` absent AND
    no live snapshot (live runs) AND no usable receipt of the same mode. A torn, unreadable or DELETED prior with any
    such trace is never a bootstrap (review of PR 2425 round 4 and PR 2431): fall back to the tier in the live
    snapshot, then to the newest usable receipt of the same mode, dated by its content (``evaluated_at``/``as_of``,
    never the file name) and skipping replays (``--as-of``: flagged ``replay``, named ``-shadow-replay``, or dated
    after now); then, if a prior file existed but nothing is readable, a NONE prior that escalates through the normal
    two-evaluation path and never pages as a first reading."""
    now = now or datetime.now(timezone.utc)
    existed = path.exists()
    if existed:
        p = _read_prior(path)
        if isinstance(p, dict) and p.get("tier"):
            return p
    if not shadow:
        snap = _read_prior(snapshot_path())
        if isinstance(snap, dict) and snap.get("tier") and snap.get("mode") != "shadow":
            return {
                "tier": snap["tier"],
                "as_of": snap.get("as_of"),
                "hysteresis": {},
                "prior_source": "market_risk_latest.json",
            }
    rdir = state_dir() / "receipts"
    best: tuple[datetime, str, dict] | None = None
    for n in os.listdir(rdir) if rdir.is_dir() else []:
        if not n.endswith(".json") or n.endswith("-shadow-replay.json") or n.endswith("-shadow.json") != shadow:
            continue
        r = _read_prior(rdir / n)
        if not isinstance(r, dict) or not r.get("tier") or r.get("replay"):
            continue
        t = _receipt_time(r, n)
        if t is None or t > now:
            continue  # undatable, or a replay of a future instant
        if best is None or t > best[0]:
            best = (t, n, r)
    if best is not None:
        return dict(best[2], prior_source=f"receipts/{best[1]}")
    if not existed:
        return None  # nothing anywhere: a genuine first reading
    print(f"market_risk_evaluate: prior {path} unreadable and nothing to fall back to; NONE prior", file=sys.stderr)
    return {"tier": "NONE", "hysteresis": {}, "prior_source": "unreadable prior, no fallback"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write latest.json + dated receipt")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply and --shadow")
    ap.add_argument(
        "--shadow",
        action="store_true",
        help="evaluate and write the receipt + the snapshot Home/API read (mode shadow, prior shadow_latest.json); "
        "no outbox, no episode, no Telegram/email/SMS, never the live prior",
    )
    ap.add_argument("--as-of", help="ISO-8601 instant to evaluate (replay)")
    ap.add_argument("--fixture", help="fixture directory for a replay reader (scripts/lib/market_risk/fixture_reader)")
    ap.add_argument("--overlay", help="overlay fixture directory (e.g. tests/fixtures/market_risk_scenarios/oct2026)")
    ap.add_argument("--prior", help="prior assessment JSON (default: latest.json when not replaying)")
    ap.add_argument("--policy", default=str(POLICY_PATH))
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--no-portfolio", action="store_true", help="market tier only (no exposure uplift)")
    ap.add_argument(
        "--scheduled",
        action="store_true",
        help="this run was launched by the scheduler (the market-risk-evaluate cron lines): write the run receipt "
        "data/runtime/market_risk/run_last.json that the stalled-escalation check reads; manual runs never write it",
    )
    a = ap.parse_args(argv)
    apply = a.apply and not a.dry_run and not a.shadow
    shadow = a.shadow and not a.dry_run
    if apply or shadow:
        # one evaluator at a time (review round 3, H5): an overlapping cron/manual --apply exits cleanly instead of
        # racing the first one into a second RED initial
        import fcntl

        lock_path = state_dir() / "evaluate.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lock_fd)
            print("market_risk_evaluate: another --apply run holds the lock; exiting", file=sys.stderr)
            return 0
    started = datetime.now(timezone.utc)
    now = scoring._parse(a.as_of) if a.as_of else started
    if now is None:
        ap.error(f"--as-of {a.as_of!r} is not ISO-8601")
    policy = load_policy(a.policy)
    try:
        reader = FixtureReader(a.fixture, overlay=a.overlay) if a.fixture else production_reader()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    prior_name = SHADOW_PRIOR if shadow else "latest.json"
    if a.prior:
        prior = _read_prior(Path(a.prior))
    elif a.as_of:
        prior = None
    else:
        prior = _resolve_prior(state_dir() / prior_name, shadow=shadow)
    portfolio = None if a.no_portfolio else portfolio_context(now)
    if shadow:
        return _shadow(now, reader, policy, prior, portfolio, as_json=a.as_json, replay=bool(a.as_of))
    written: dict[str, str] = {}

    def _persist(d: dict) -> None:
        d["mode"] = "apply"
        d["session"] = session_of(now)
        d["evaluated_at"] = datetime.now(timezone.utc).isoformat()  # wall clock: dates the receipt (PR 2431)
        d["replay"] = bool(a.as_of)
        written["latest"] = persist(d, now)

    cycle = run_cycle(now, reader, policy, prior, apply=apply, portfolio=portfolio, on_assessed=_persist)
    doc = cycle["assessment"]
    assessment = cycle["object"]
    doc["cycle"] = {k: v for k, v in cycle.items() if k not in ("assessment", "object")}
    doc["mode"] = "apply" if apply else "dry_run"
    doc["session"] = session_of(now)
    if apply:
        doc["written"] = written.get("latest") or str(state_dir() / "latest.json")
    if a.scheduled and not a.as_of and not a.fixture:
        # only a scheduler-launched run (dry or apply) leaves the receipt; a manual or replay run never does, so a
        # hand-run cannot mask a dead schedule (review of #2411, M8)
        doc["run_receipt"] = write_run_receipt(doc, started=started, finished=datetime.now(timezone.utc))
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
