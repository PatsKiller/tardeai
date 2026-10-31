"""CIO memory, watchlist-first candidate tiers and research fan-out for market-risk events (rotation advisor follow-up).

Operator 2026-10-31, verbatim: "We also want to make sure that the CIO is memorizing all of this. And when stuff is
pivoting to a new sector, I would think logically we're going to look first for stuff that we already researched that's
on the watch list or our short list and then go to what else is leading in the industry. It should also click off
separate Hermes searches and Brave and you.com searches related to all of this. I'll let you architect it."

Architecture: no new store, no new queue, no new provider. Everything goes through paths that already exist:

* **Market-level memory.** Tier episodes and shock-type changes go to the governed durable memory
  (``agent_memory_admission.admit_candidate`` into ``data/cio/aif_memory.jsonl``, EPISODIC). Admission refuses
  forbidden-authoritative subjects (price, holdings, policy...), so the text names states, groups and dates only.
* **Group-level memory.** A leadership transition goes onto the CIO's ``SECTOR:<label>`` InstrumentRecord via
  ``apply_cognition``. It sets ``next_research_question`` (``MBI_COGNITION = 1``) and appends a lesson.
  ``InstrumentRecordStore.upsert`` is the only writer (AGENTS.md §26.1).
* **Per-symbol memory.** A name's event (an exit during a shock, a re-entry flip, a leadership tier) becomes a
  ``silo="cio"`` contribution on its SecurityResearchSpine, tagged ``market_risk``. Ask-the-CIO recalls those for that
  security (``cio_ask_memory.SpineAskMemory.recall``). The symbol's existing InstrumentRecord also gets the next research
  question; nothing is minted here.
* **Hermes and TradeAI research.** ``watch_directives`` rows go through the single writer
  ``lib.writers.watch_directives_writer`` (``hermes_enabled``), the same queue the rotation digest seeds.
* **Brave.** Targets for ``governed_research_producer.produce_research``, which reaches Brave only through the governed
  router and its budget ledger. Results land in the wake research feed, where corroboration rules apply.
* **you.com.** No provider, client or registry row exists. Jobs are reported as ``unavailable`` and a §7A provider
  proposal is recorded in docs; no client is built.

Advisory only (``MBI_BEHAVIOR = 0``): no plan carries a size, order, price, weight or stop; ``BehaviorWriteRefused``
guards the InstrumentRecord path. Every function here PLANS; only ``apply`` writes, and only when called with
``apply=True`` from the CLI.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from scripts.lib.market_risk import contract as c

PRODUCER = "market_risk_rotation"
SPINE_SILO = "cio"


def _cfg(policy: dict[str, Any]) -> dict[str, Any]:
    return dict((policy or {}).get("leadership") or {})


def _age_days(ts: Any, now: datetime) -> Optional[float]:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return round((now - t).total_seconds() / 86400.0, 1)


def trigger_id(kind: str, key: str, frm: Any, to: Any, as_of: Any) -> str:
    raw = f"{kind}|{key}|{frm}|{to}|{as_of}"
    return f"mrt_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


# --------------------------------------------------------------------------- triggers


def triggers(prev: dict[str, Any], cur: dict[str, Any]) -> list[dict[str, Any]]:
    """Transitions since the last recorded state. ``prev``/``cur`` = {"leadership": {key: class}, "shock_type": str,
    "tier": str, "reentry": {symbol: stance}, "as_of": str}."""
    out: list[dict[str, Any]] = []
    as_of = cur.get("as_of")
    pl, cl = prev.get("leadership") or {}, cur.get("leadership") or {}
    for key, cls in sorted(cl.items()):
        if pl.get(key) != cls and cls in ("LEADERSHIP_CONFIRMED", "LEADERSHIP_EMERGING", "LEADERSHIP_FADING"):
            out.append(
                {
                    "kind": "leadership_transition",
                    "key": key,
                    "from": pl.get(key),
                    "to": cls,
                    "id": trigger_id("leadership", key, pl.get(key), cls, as_of),
                }
            )
    if cur.get("shock_type") and prev.get("shock_type") != cur.get("shock_type"):
        out.append(
            {
                "kind": "shock_type_change",
                "key": "market",
                "from": prev.get("shock_type"),
                "to": cur["shock_type"],
                "id": trigger_id("shock", "market", prev.get("shock_type"), cur["shock_type"], as_of),
            }
        )
    if cur.get("tier") and prev.get("tier") != cur.get("tier"):
        out.append(
            {
                "kind": "tier_change",
                "key": "market",
                "from": prev.get("tier"),
                "to": cur["tier"],
                "id": trigger_id("tier", "market", prev.get("tier"), cur["tier"], as_of),
            }
        )
    pr, cr = prev.get("reentry") or {}, cur.get("reentry") or {}
    for sym, st in sorted(cr.items()):
        if pr.get(sym) != st and st == "RE_ENTER":
            out.append(
                {
                    "kind": "reentry_flip",
                    "key": sym,
                    "from": pr.get(sym),
                    "to": st,
                    "id": trigger_id("reentry", sym, pr.get(sym), st, as_of),
                }
            )
    return out


# --------------------------------------------------------------------------- watchlist-first candidate tiers

MARKET_INPUTS = ("quote", "stats", "price", "bars")


def research_as_of(item: dict[str, Any]) -> Optional[str]:
    """When the CIO last RESEARCHED a name: the newest research input (analyst, entry plan, thesis, Hermes ...), not
    the projection run time and not market-data inputs (quote, stats), which refresh every run."""
    ins = item.get("inputs_as_of") or {}
    if not isinstance(ins, dict):
        return None
    vals = [str(v) for k, v in ins.items() if v and k not in MARKET_INPUTS]
    return max(vals) if vals else None


def tiered_candidates(
    group_key: str,
    *,
    group_symbols: list[str],
    opportunity_items: list[dict[str, Any]],
    watchlist: dict[str, Any],
    instrument_records: dict[str, dict[str, Any]],
    group_of: Callable[[dict[str, Any]], list[str]],
    policy: dict[str, Any],
    now: datetime,
) -> dict[str, list[dict[str, Any]]]:
    """Tier 1: researched AND on the watchlist (or carrying a CIO WATCH/HELD record, the short list).
    Tier 2: researched, not on the watchlist. Tier 3: other leaders in the group with no research (momentum >= floor,
    no conviction), queued for new research. Research age is shown; stale research is flagged for re-research."""
    cfg = (_cfg(policy).get("candidate_tiers")) or {}
    stale = float(cfg.get("research_stale_days") or 30)
    mom_min = float(cfg.get("tier3_min_momentum") or 60)
    per = int(cfg.get("per_tier") or 5)
    wl = {str(s).upper() for s in (watchlist or {})}
    short = {s for s, r in instrument_records.items() if str(r.get("kind") or "") in ("WATCH", "HELD")}
    tiers: dict[str, list[dict[str, Any]]] = {"tier1": [], "tier2": [], "tier3": []}
    seen: set[str] = set()
    for it in opportunity_items:
        sym = str(it.get("symbol") or "").upper()
        if not sym or sym in seen or group_key not in group_of(it):
            continue
        seen.add(sym)
        rec = instrument_records.get(sym) or {}
        researched = isinstance(it.get("conviction"), (int, float)) or bool(rec)
        age = _age_days(research_as_of(it) or rec.get("updated_ts"), now)
        row = {
            "symbol": sym,
            "cio_conviction": it.get("conviction"),
            "cio_stance": it.get("stance"),
            "research_age_days": age,
            "research_stale": bool(age is not None and age > stale),
            "on_watchlist": sym in wl,
            "on_short_list": sym in short,
        }
        if researched and (sym in wl or sym in short):
            tiers["tier1"].append(row)
        elif researched:
            tiers["tier2"].append(row)
        elif float(it.get("momentum_score") or 0) >= mom_min:
            row["momentum_score"] = it.get("momentum_score")
            row["needs_research"] = True
            tiers["tier3"].append(row)
    for sym in group_symbols:  # the group's own members are "leaders in the group" even with no opportunity row
        if sym.upper() not in seen and len(group_symbols) > 1:
            tiers["tier3"].append({"symbol": sym.upper(), "needs_research": True, "research_age_days": None})

    def key(r: dict[str, Any]) -> tuple:
        return (-(r.get("cio_conviction") or r.get("momentum_score") or 0), r["symbol"])

    return {t: sorted(rows, key=key)[:per] for t, rows in tiers.items()}


# --------------------------------------------------------------------------- research fan-out


def plan_research(
    trigs: list[dict[str, Any]],
    *,
    groups: dict[str, Any],
    tiers_by_group: dict[str, dict[str, list[dict[str, Any]]]],
    policy: dict[str, Any],
    brave_status: Optional[dict[str, Any]],
    already: set[str] | None = None,
) -> dict[str, Any]:
    """Jobs per provider. Deduped per trigger id; capped per day and by the provider's own budget headroom."""
    fc = (_cfg(policy).get("fanout")) or {}
    hc, bc, yc = fc.get("hermes") or {}, fc.get("brave") or {}, fc.get("youcom") or {}
    already = already or set()
    hermes: list[dict[str, Any]] = []
    brave: list[dict[str, Any]] = []
    youcom: list[dict[str, Any]] = []
    for t in trigs:
        if t["id"] in already or t["kind"] not in set(fc.get("triggers") or []) | {"tier_change"}:
            continue
        if t["kind"] == "tier_change":
            continue  # tier changes are remembered, not researched
        if t["kind"] == "leadership_transition":
            g = groups.get(t["key"]) or {}
            label = g.get("label") or t["key"]
            q = f"Why is {label} {'leading' if t['to'] != 'LEADERSHIP_FADING' else 'losing leadership'}; durability; catalysts"
            hermes.append(
                {
                    "kind": "sector",
                    "label": label,
                    "spec": {"term": label},
                    "rationale": q,
                    "trigger_id": t["id"],
                }
            )
            tiers = tiers_by_group.get(t["key"]) or {}
            for r in (tiers.get("tier3") or []) + [
                x for x in tiers.get("tier1", []) + tiers.get("tier2", []) if x.get("research_stale")
            ]:
                hermes.append(
                    {
                        "kind": "ticker",
                        "label": r["symbol"],
                        "spec": {"symbol": r["symbol"]},
                        "rationale": f"{label} {t['to'].lower()}: "
                        + ("new research" if r.get("needs_research") else "research is stale; re-research"),
                        "trigger_id": t["id"],
                    }
                )
            etf = next(iter(g.get("symbols") or []), None)
            if etf:
                brave.append({"symbol": etf, "query": q, "trigger_id": t["id"]})
            youcom.append({"query": q, "trigger_id": t["id"], "status": "unavailable: no registered provider"})
        elif t["kind"] == "shock_type_change":
            q = f"Market selloff type changed to {t['to']}: what is driving it and which groups are affected"
            hermes.append(
                {
                    "kind": "trend",
                    "label": f"market shock {t['to'].lower()}",
                    "spec": {"term": q},
                    "rationale": q,
                    "trigger_id": t["id"],
                }
            )
            brave.append({"symbol": "SPY", "query": q, "trigger_id": t["id"]})
            youcom.append({"query": q, "trigger_id": t["id"], "status": "unavailable: no registered provider"})
        elif t["kind"] == "reentry_flip":
            q = f"{t['key']} re-entry conditions met: confirm the catalyst and the trend repair"
            hermes.append(
                {
                    "kind": "ticker",
                    "label": t["key"],
                    "spec": {"symbol": t["key"]},
                    "rationale": q,
                    "trigger_id": t["id"],
                }
            )
            brave.append({"symbol": t["key"], "query": q, "trigger_id": t["id"]})
            youcom.append({"query": q, "trigger_id": t["id"], "status": "unavailable: no registered provider"})
    # dedupe by (kind,label) and cap
    seen, hj = set(), []
    for j in hermes:
        k = (j["kind"], j["label"].upper())
        if k not in seen:
            seen.add(k)
            hj.append(j)
    hermes = hj[: int(hc.get("daily_cap") or 12)] if hc.get("enabled", True) else []
    headroom = None
    if brave_status:
        headroom = int(brave_status.get("daily_limit") or 0) - int(brave_status.get("daily_used") or 0)
    bcap = int(bc.get("daily_cap") or 10)
    if headroom is not None:
        bcap = max(0, min(bcap, headroom - int(bc.get("min_daily_headroom") or 0)))
    elif brave_status is None:
        bcap = 0  # budget unknown -> no Brave jobs (fail closed)
    bseen, bj = set(), []
    for j in brave:
        if j["symbol"] not in bseen:
            bseen.add(j["symbol"])
            bj.append(j)
    brave = bj[:bcap] if bc.get("enabled", True) else []
    plan = {
        "hermes": hermes,
        "brave": brave,
        "youcom": youcom if not yc.get("registered") else [],
        "brave_budget": {"headroom_today": headroom, "cap_applied": bcap, "status": brave_status},
    }
    c.assert_no_behavior_fields(plan)
    return plan


# --------------------------------------------------------------------------- memory plans


def plan_memory(
    trigs: list[dict[str, Any]],
    *,
    groups: dict[str, Any],
    cur: dict[str, Any],
    exits: list[dict[str, Any]],
    tiers_by_group: dict[str, dict[str, list[dict[str, Any]]]],
    snapshot_ref: str,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Records to write. Text names states, groups, symbols and dates only (memory admission refuses price, holdings,
    policy and other canonical-truth subjects)."""
    mc = (_cfg(policy).get("memory")) or {}
    as_of = cur.get("as_of")
    out: list[dict[str, Any]] = []
    shock = cur.get("shock_type")
    for t in trigs:
        if t["kind"] in ("tier_change", "shock_type_change"):
            what = "Market risk tier" if t["kind"] == "tier_change" else "Market selloff type"
            leaders = sorted(
                (g.get("label") or k) for k, g in groups.items() if g.get("class") == "LEADERSHIP_CONFIRMED"
            )
            out.append(
                {
                    "target": "aif_memory",
                    "trigger_id": t["id"],
                    "record": {
                        "memory_type": mc.get("aif_memory_type") or "EPISODIC",
                        "subject": "market regime episode",
                        "content": f"{what} changed from {t['from'] or 'none'} to {t['to']} as of {as_of}. "
                        f"Selloff type: {shock or 'unknown'}. Confirmed leading groups: {', '.join(leaders) or 'none'}.",
                        "symbols": ["SPY", "QQQ"],
                        "source_refs": [f"{snapshot_ref}#{as_of}"],
                        "source_kind": "agent_run",
                        "confidence": 0.6,
                    },
                }
            )
        elif t["kind"] == "leadership_transition":
            g = groups.get(t["key"]) or {}
            label = g.get("label") or t["key"]
            tiers = tiers_by_group.get(t["key"]) or {}
            names = [r["symbol"] for r in (tiers.get("tier1") or []) + (tiers.get("tier2") or [])][:5]
            out.append(
                {
                    "target": "sector_record",
                    "trigger_id": t["id"],
                    "sector": label,
                    "next_research_question": f"Why is {label} now {t['to'].replace('LEADERSHIP_', '').lower()} "
                    f"(was {str(t['from'] or 'none').replace('LEADERSHIP_', '').lower()}); is it durable; which "
                    f"researched names lead it ({', '.join(names) or 'none yet'})?",
                    "lesson": {
                        "event": "leadership_transition",
                        "from": t["from"],
                        "to": t["to"],
                        "as_of": as_of,
                        "evidence": list(g.get("evidence") or [])[:3],
                        "trigger_id": t["id"],
                    },
                }
            )
    for e in exits or []:
        sym = str(e.get("symbol") or "").upper()
        if not sym:
            continue
        out.append(
            {
                "target": "spine",
                "trigger_id": trigger_id("exit", sym, None, e.get("date"), as_of),
                "symbol": sym,
                "kind": mc.get("spine_kind") or "market_risk.event",
                "tags": [mc.get("spine_tag") or "market_risk"],
                "summary": f"{sym} exited on {e.get('date')} during a {shock or 'unknown'} selloff "
                f"({', '.join(e.get('stressed_groups') or []) or 'groups not recorded'}). Re-entry is watched.",
                "next_research_question": f"{sym}: has the reason for the {e.get('date')} exit resolved, and are the "
                "re-entry conditions forming?",
            }
        )
    for p in out:
        c.assert_no_behavior_fields(p)
    return out


# --------------------------------------------------------------------------- apply (CLI --apply only)


def apply_memory(plans: list[dict[str, Any]], *, root: Any = None) -> list[dict[str, Any]]:
    """Write the planned memories through the existing CIO paths. Returns one receipt per plan; never raises for one
    failed item (the receipt says why)."""
    receipts = []
    for p in plans:
        try:
            if p["target"] == "aif_memory":
                from scripts.lib.agent_durable_memory import get_durable_provider
                from scripts.lib.agent_memory_admission import admit_candidate

                r = admit_candidate(p["record"], provider=get_durable_provider(root), admitted_by=PRODUCER)
                receipts.append(
                    {
                        "trigger_id": p["trigger_id"],
                        "target": "aif_memory",
                        "accepted": r.get("accepted"),
                        "reason": r.get("reason"),
                        "memory_id": r.get("memory_id"),
                    }
                )
            elif p["target"] == "sector_record":
                from scripts.lib import cio_instrument_record as ir

                st = ir._store_for_root(root)  # noqa: SLF001 — the registered store resolver
                key = ir.subject_key("SECTOR", p["sector"])
                rec = st.load(key) or ir.new_record("SECTOR", p["sector"])
                rec2, changed = ir.apply_cognition(
                    rec, next_research_question=p["next_research_question"], lesson=p["lesson"], strict=False
                )
                st.upsert(rec2)
                receipts.append({"trigger_id": p["trigger_id"], "target": key, "changed": changed})
            elif p["target"] == "spine":
                from scripts.lib.cross_asset.security_research_spine import upsert_research_memory

                r = upsert_research_memory(
                    p["symbol"],
                    silo=SPINE_SILO,
                    kind=p["kind"],
                    summary=p["summary"],
                    artifact_id=p["trigger_id"],
                    refs=[p["trigger_id"]],
                    tags=p["tags"],
                )
                rr = {
                    "trigger_id": p["trigger_id"],
                    "target": f"spine:{p['symbol']}",
                    "ok": r.get("ok"),
                    "error": r.get("error"),
                }
                from scripts.lib import cio_instrument_record as ir

                st = ir._store_for_root(root)  # noqa: SLF001
                key = ir.subject_key_for_symbol(p["symbol"], store=st)
                if key:  # never mint here
                    rec2, changed = ir.apply_cognition(
                        st.load(key), next_research_question=p["next_research_question"], strict=False
                    )
                    st.upsert(rec2)
                    rr["record"] = {"key": key, "changed": changed}
                receipts.append(rr)
        except Exception as exc:  # noqa: BLE001 — one failed memory never blocks the others; the receipt says why
            receipts.append(
                {"trigger_id": p.get("trigger_id"), "target": p.get("target"), "error": f"{type(exc).__name__}: {exc}"}
            )
    return receipts


def apply_research(plan: dict[str, Any], *, conn_factory: Callable[[], Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Enqueue Hermes/TradeAI directives through the single writer and Brave targets through the governed producer."""
    fc = (_cfg(policy).get("fanout")) or {}
    hc = fc.get("hermes") or {}
    out: dict[str, Any] = {"hermes": None, "brave": None, "youcom": "unavailable: no registered provider"}
    if plan.get("hermes"):
        from scripts.lib.writers.watch_directives_writer import write_watch_directives

        conn = conn_factory()
        try:
            cur = conn.cursor()
            rows = [
                {
                    "kind": j["kind"],
                    "label": j["label"],
                    "spec": j["spec"],
                    "rationale": f"{j['rationale']} [trigger {j['trigger_id']}]",
                    "created_by": hc.get("created_by") or PRODUCER,
                    "priority": hc.get("priority") or "normal",
                    "ttl_days": int(hc.get("ttl_days") or 21),
                    "hermes_enabled": True,
                    "trade_ai_enabled": True,
                }
                for j in plan["hermes"]
            ]
            rec = write_watch_directives(cur, rows, source=PRODUCER, on_duplicate="reuse")
            conn.commit()
            out["hermes"] = {
                "rows_in": rec.rows_in,
                "written": getattr(rec, "rows_written", None),
                "rejected": len(getattr(rec, "rejects", []) or []),
            }
        finally:
            conn.close()
    if plan.get("brave"):
        from scripts.lib.governed_research_producer import produce_research

        r = produce_research(targets=[{"symbol": j["symbol"], "query": j["query"]} for j in plan["brave"]])
        out["brave"] = {"ok": r.ok, "outcome": r.outcome, "errors": list(r.errors or [])}
    return out


def to_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)
