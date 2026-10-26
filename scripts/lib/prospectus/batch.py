"""Watch-list prospectuses through the Message Batches API (operator 2026-10-26: "implement this cost savings right
now; we don't need it immediately").

Holdings and operator-initiated rewrites ("Rewrite now", ``--symbols``) stay synchronous. Queued Watch rows
accumulate; ``submit_due`` sends them when at least ``batch.min_items`` are queued or the oldest has waited
``batch.max_wait_hours`` (config/prospectus_generation.json). For each row, before anything is submitted:

    house inputs → data-quality gate (layers 1-2; HARD_FAIL parks the row as blocked_data, no submit)
    → the bounded web-search planning turn (synchronous, as for every prospectus) → the writer prompt
    → ``AnthropicTransport.submit_batch`` (50% price, Opus 5.5, effort medium, ~5k output tokens)

Each request is its own single-request batch: the transport admits, reserves and journals one request identity, so
the credit book, the per-process cap and the per-request ledger stay exact. ``collect`` polls every pending entry;
a succeeded result is validated and written through the same path as a synchronous report
(``finish_doc`` → ``pipeline.persist_doc``: render, store, index, gate rewrite). Collection is idempotent: the
transport refuses a second ledger row (``ALREADY_COLLECTED``) and the local entry is closed once written. Errored,
expired or lost results put the row back in the queue (bounded by ``batch.max_attempts``).

Governance: the native per-process reservation is opened before submit and settled at the transport's projected
hold right after the batch is accepted (a batch outlives the 30-minute stale-reservation recovery), so the
process daily cap counts the conservative hold; the credit book settles the actual batch cost on collect.
READ_ONLY_ADVISORY (MBI_BEHAVIOR=0). Real data stays in the private store (``<state>/data/prospectus``).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable, Optional
import uuid

from . import store
from .generate import (GenerationFailed, QueueLater, finish_doc, generation_config, max_tokens_for, run_gate,
                       scope_settings, web_loop, writer_prompt, _credit_refusal)
from .inputs import Bundle

STATE_FILE = "batches.json"
PENDING_DIR = "batch_pending"
OPERATOR_REASONS = ("operator_refresh", "operator_cli")


def _dt(v: Any) -> Optional[datetime]:
    try:
        out = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def is_batch_row(row: dict, gen: dict | None = None) -> bool:
    """Watch, full, scheduled work only: holdings and anything the operator asked for stay synchronous."""
    if row.get("scope", "watch") == "holding" or row.get("mode") == "delta":
        return False
    if row.get("reason") in OPERATOR_REASONS or int(row.get("priority", 500)) <= 1:
        return False
    return bool(scope_settings("watch", gen).get("batch"))


def read_state(base: Path) -> dict:
    try:
        doc = json.loads((base / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    return {"schema": "ProspectusBatches@v1", "items": dict(doc.get("items") or {})}


def _write_state(base: Path, doc: dict) -> None:
    store.write_json(base / STATE_FILE, doc)


def _save_bundle(base: Path, sym: str, bundle: Bundle, extra: dict) -> None:
    store.write_json(base / PENDING_DIR / f"{sym}.json", {"bundle": asdict(bundle), **extra})


def _load_bundle(base: Path, sym: str) -> tuple[Bundle, dict]:
    doc = json.loads((base / PENDING_DIR / f"{sym}.json").read_text(encoding="utf-8"))
    b = doc.pop("bundle")
    b["series"] = {k: ([tuple(x) for x in v] if k in ("price_1y", "valuation_vs_peers", "revenue_eps_trend")
                       and isinstance(v, list) else v) for k, v in (b.get("series") or {}).items()}
    return Bundle(**b), doc


# ── governed submit / collect (production) ────────────────────────────────────────────────────────────────────
def _libs():
    try:
        from lib import anthropic_routing as promo, llm_consumption as lc  # type: ignore
    except ImportError:
        from scripts.lib import anthropic_routing as promo, llm_consumption as lc  # type: ignore
    return promo, lc


def governed_submit(prompt: str, *, process_id: str, max_tokens: int, effort: str | None, credit_tier: str,
                    client_request_id: str) -> dict:
    """One explicitly asynchronous request through the credit book, the process cap and the cost ledger."""
    promo, lc = _libs()
    cfg = lc.get_process_config(process_id)
    if not promo.active(process_id, cfg):
        raise RuntimeError("ANTHROPIC_CREDIT_UNAVAILABLE: batch submit; queue and retry")
    try:
        from lib.consumption_run_manual import validate_paid_cap_config  # type: ignore
    except ImportError:
        from scripts.lib.consumption_run_manual import validate_paid_cap_config  # type: ignore
    validate_paid_cap_config(cfg, require_global=False)
    model = promo.load_policy()["models"][credit_tier]
    rid = lc.reserve_projected_cost(process_id, 0, model_id=model, process_config=cfg,
                                    metadata={"funding_source": "anthropic_promotional_credit", "paid_component_usd": 0,
                                              "batch": True})
    ctx = promo.FundingContext(process_id, cfg, rid, global_cap=None, cost_ceiling=None, mode="batch")
    try:
        with promo.funding_context(ctx):
            res = promo.transport().submit_batch(
                [{"role": "user", "content": prompt}], model, client_request_id=client_request_id,
                process_id=process_id, caller_allows_async=True, max_tokens=max_tokens, credit_tier=credit_tier,
                max_input_tokens=int(cfg.get("max_input_tokens") or 40000),
                process_cap=promo.amount(cfg["daily_cost_cap_usd"]), effort=effort)
    except BaseException as exc:
        lc.settle_reservation(rid, float(ctx.credit_total) if ctx.credit_total else None, ok=False,
                              billable_attempt=bool(getattr(exc, "request_sent", False)
                                                    or getattr(exc, "possibly_billable", False)))
        raise
    # Settle the native hold now (conservative: the projected hold), so the 30-minute stale recovery never guesses.
    lc.settle_reservation(rid, float(ctx.credit_total), ok=True, billable_attempt=True)
    return {"batch_id": res["batch_id"], "client_request_id": client_request_id, "reservation_id": rid,
            "model": model, "hold_usd": res.get("promotional_hold_usd")}


def governed_collect(entry: dict) -> dict:
    """PENDING / SUCCEEDED (text + provenance) / ALREADY_COLLECTED / FAILED. Never a second ledger row."""
    promo, lc = _libs()
    cfg = lc.get_process_config(entry["process_id"])
    ctx = promo.FundingContext(entry["process_id"], cfg, entry.get("reservation_id"), global_cap=None,
                               cost_ceiling=None, mode="batch")
    try:
        with promo.funding_context(ctx):
            res = promo.transport().collect_batch(entry["batch_id"], client_request_id=entry["client_request_id"],
                                                  process_id=entry["process_id"])
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "") or str(exc)[:80]
        if code in ("BATCH_RESULT_UNAVAILABLE", "MODEL_MISMATCH"):
            return {"status": "FAILED", "error": code}
        raise
    if res.get("status") != "SUCCEEDED":
        return {"status": res.get("status") or "PENDING"}
    body = res.get("message") or {}
    text = "".join(b.get("text", "") for b in body.get("content") or [] if b.get("type") == "text")
    usage = body.get("usage") or {}
    return {"status": "SUCCEEDED", "text": text,
            "prov": {"returned_model": body.get("model"), "provider": "anthropic", "estimated_cost_usd": float(res["cost_usd"]),
                     "finish_reason": "refusal" if body.get("stop_reason") == "refusal" else body.get("stop_reason"),
                     "usage": {"prompt_tokens": usage.get("input_tokens"), "completion_tokens": usage.get("output_tokens")},
                     "batch": True}}


# ── submit ────────────────────────────────────────────────────────────────────────────────────────────────────
def due(base: Path, *, now: datetime, gen: dict | None = None) -> list[dict]:
    """Queued batch-eligible rows when the size or the wait threshold is met; else []."""
    gen = gen or generation_config()
    cfg = gen.get("batch") or {}
    rows = [r for r in store.read_queue(base)["items"] if r.get("state") in ("queued", None) and is_batch_row(r, gen)]
    if not rows:
        return []
    oldest = min((_dt(r.get("requested_at")) or now) for r in rows)
    if len(rows) >= int(cfg.get("min_items", 10)) or now - oldest >= timedelta(hours=float(cfg.get("max_wait_hours", 6))):
        return rows[: int(cfg.get("max_submit_per_run", 40))]
    return []


def submit_due(base: Path, sources: Any, cfg: dict, *, now: datetime, submit_fn: Callable = governed_submit,
               generate_fn: Callable | None = None, ai_fn: Any = "auto", force: bool = False,
               log: Callable[[str], None] = print, on_blocked: Callable | None = None) -> dict:
    """Gate, plan web searches and submit each due Watch row. Stops for the run when the credit is unavailable."""
    from . import quality_gate as qg
    from .domains import full_assemble
    from .generate import governed_generate
    gen = generation_config()
    bcfg = gen.get("batch") or {}
    generate_fn = generate_fn or governed_generate
    if ai_fn == "auto":
        ai_fn = qg.governed_ai_call if generate_fn is governed_generate else None
    rows = due(base, now=now, gen=gen) if not force else [
        r for r in store.read_queue(base)["items"] if r.get("state") in ("queued", None) and is_batch_row(r, gen)]
    out: dict = {"submitted": [], "blocked_data": [], "failed": [], "stopped_reason": None}
    state = read_state(base)
    procs = cfg["processes"]
    brave = cfg.get("brave") or {}
    for row in rows:
        sym = row["symbol"]
        if (state["items"].get(sym) or {}).get("state") == "pending":
            continue  # already in flight
        bundle = full_assemble(sources, sym, "watch", cfg=cfg, holding=None, now=now, request_refresh=True)
        try:
            gate, _settings = run_gate(bundle, now=now, ai_fn=ai_fn)
        except qg.DataBlocked as exc:
            if on_blocked is not None:
                on_blocked(sym, exc)
            out["blocked_data"].append(sym)
            continue
        process_id = procs["standard"]
        limit_day = int(brave.get("daily_limit", 40))
        try:
            web = web_loop(bundle, process_id=process_id, cfg=cfg, generate_fn=generate_fn,
                           search_fn=getattr(sources, "search", None),
                           allowance_fn=lambda take: store.search_allowance(base, limit_day, take=take),
                           manual=False, now=now)
            prompt = writer_prompt(bundle, cfg, mode="full", previous=None, gen=gen)
            crid = uuid.uuid4().hex
            res = submit_fn(prompt, process_id=process_id, max_tokens=max_tokens_for(bundle, cfg, "full", gen),
                            effort=scope_settings("watch", gen).get("effort"),
                            credit_tier=str(bcfg.get("credit_tier", "long_form")), client_request_id=crid)
        except Exception as exc:  # noqa: BLE001
            if _credit_refusal(exc):
                out["stopped_reason"] = str(exc)[:200]
                log(f"BATCH QUEUED {sym}: credit unavailable ({str(exc)[:120]}) — stopping submits for this run")
                break
            out["failed"].append(sym)
            store.mark(base, sym, state="queued", error=f"batch submit: {type(exc).__name__}: {str(exc)[:160]}")
            log(f"BATCH SUBMIT FAILED {sym}: {str(exc)[:160]}")
            continue
        version = store.stamp(now)
        _save_bundle(base, sym, bundle, {"gate": gate, "web": web, "version": version, "process_id": process_id,
                                         "submitted_at": now.isoformat()})
        state["items"][sym] = {"symbol": sym, "batch_id": res["batch_id"], "client_request_id": res["client_request_id"],
                               "reservation_id": res.get("reservation_id"), "process_id": process_id,
                               "model": res.get("model"), "hold_usd": res.get("hold_usd"),
                               "submitted_at": now.isoformat(), "version": version, "state": "pending",
                               "row": dict({k: row.get(k) for k in ("scope", "premium", "priority", "reason", "mode")},
                                           attempts=int(row.get("attempts") or 0) + 1)}
        _write_state(base, state)
        store.mark(base, sym, state="running")  # counts the attempt
        store.mark(base, sym, state="batch_pending")
        store.update_index(base, sym, status="queued", batch_id=res["batch_id"], batch_submitted_at=now.isoformat())
        out["submitted"].append(sym)
        log(f"BATCH SUBMITTED {sym} {res['batch_id']}")
    return out


# ── collect ───────────────────────────────────────────────────────────────────────────────────────────────────
def _requeue(base: Path, sym: str, entry: dict, why: str, bcfg: dict, now: datetime) -> str:
    attempts = int((entry.get("row") or {}).get("attempts") or 1)
    final = attempts >= int(bcfg.get("max_attempts", 3))
    store.enqueue(base, [{"symbol": sym, **{k: v for k, v in (entry.get("row") or {}).items()
                                            if v is not None and k != "attempts"}, "scope": "watch"}], now=now)
    store.mark(base, sym, state="failed" if final else "queued", error=f"batch: {why}"[:240])
    store.update_index(base, sym, status="failed" if final else "queued", last_error=f"batch: {why}"[:240])
    return "failed" if final else "requeued"


def collect(base: Path, cfg: dict, *, now: datetime, collect_fn: Callable = governed_collect,
            persist_fn: Callable | None = None, log: Callable[[str], None] = print) -> dict:
    """Poll every pending batch entry once; write succeeded reports; re-queue errored / expired / lost ones."""
    gen = generation_config()
    bcfg = gen.get("batch") or {}
    state = read_state(base)
    out: dict = {"written": [], "pending": [], "requeued": [], "failed": [], "cost_usd": 0.0}
    for sym, entry in list(state["items"].items()):
        if entry.get("state") != "pending":
            continue
        try:
            res = collect_fn(entry)
        except Exception as exc:  # noqa: BLE001 - an uncertain collection keeps the entry (never a double row)
            out["pending"].append(sym)
            log(f"BATCH COLLECT UNCERTAIN {sym}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        status = res.get("status")
        if status == "PENDING":
            age = now - (_dt(entry.get("submitted_at")) or now)
            if age > timedelta(hours=float(bcfg.get("lost_after_hours", 30))):
                status, res = "FAILED", {"error": "expired (no result after the batch window)"}
            else:
                out["pending"].append(sym)
                continue
        if status == "SUCCEEDED":
            try:
                bundle, extra = _load_bundle(base, sym)
                doc = finish_doc(bundle, res["text"], res["prov"], gate=extra["gate"], settings=_gate_settings(),
                                 web=extra["web"], mode="full", previous=None, now=_dt(extra.get("submitted_at")) or now,
                                 version=extra["version"], process_id=extra["process_id"],
                                 batch={"batch_id": entry["batch_id"], "submitted_at": entry["submitted_at"],
                                        "collected_at": now.isoformat(), "price_multiplier": bcfg.get("price_multiplier", 0.5)})
            except (GenerationFailed, OSError, ValueError, KeyError) as exc:
                why = f"{type(exc).__name__}: {str(exc)[:160]}"
                entry.update(state="closed", closed_at=now.isoformat(), outcome="invalid_output")
                _write_state(base, state)
                (out["failed"] if _requeue(base, sym, entry, why, bcfg, now) == "failed" else out["requeued"]).append(sym)
                continue
            persist = persist_fn
            if persist is None:
                from .pipeline import persist_doc as persist
            persist(base, sym, "watch", doc, bundle, extra["version"], cfg, entry.get("row") or {}, now=now)
            entry.update(state="closed", closed_at=now.isoformat(), outcome="written")
            _write_state(base, state)
            out["written"].append(sym)
            out["cost_usd"] += float(doc.get("cost_usd") or 0)
            log(f"BATCH READY {sym} {extra['version']} cost=${float(doc.get('cost_usd') or 0):.4f}")
            continue
        why = res.get("error") or ("result already collected but not written (lost)" if status == "ALREADY_COLLECTED"
                                   else str(status))
        entry.update(state="closed", closed_at=now.isoformat(), outcome=str(why)[:120])
        _write_state(base, state)
        (out["failed"] if _requeue(base, sym, entry, why, bcfg, now) == "failed" else out["requeued"]).append(sym)
        log(f"BATCH REQUEUE {sym}: {why}")
    # closed entries are history; keep the last 200 for audit
    closed = sorted((k for k, v in state["items"].items() if v.get("state") == "closed"),
                    key=lambda k: state["items"][k].get("closed_at") or "")
    for k in closed[:-200]:
        state["items"].pop(k, None)
    _write_state(base, state)
    out["cost_usd"] = round(out["cost_usd"], 4)
    return out


def _gate_settings() -> dict:
    from . import quality_gate as qg
    return qg.load_settings()
