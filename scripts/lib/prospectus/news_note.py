"""Prospectus news review: the classifier, the CIO news note, the per-symbol news log and the rewrite decision
(operator 2026-10-27: "Implement these fixes … I need this to execute quickly").

Runs only inside a run window (``scripts/prospectus_window.py``; 07:00 and 17:45 ET), for holdings and the watch list
that already have a prospectus:

1. ``news_gate.review`` labels every item since the report (deterministic, free).
2. Uncertain items: ONE cheap classifier read per symbol (``prospectus_news_classify`` — Claude Haiku 5.5, Anthropic
   credit only, daily cap $0.25; never DeepSeek). Unavailable credit → the item is rejected
   ``classifier_unavailable`` this window and re-read at the next.
3. A material, relevant item: a short CIO note (``prospectus_cio_news_note`` — Claude Sonnet 5.5, Anthropic credit only,
   <= $0.10/day per symbol here, <= $1.50/day for the process) reads the item against the latest prospectus (thesis
   breakers, house stop plan, scenarios) and returns ``{impact: none|watch|thesis|breaker|stop, which_breaker,
   one_line}``. The note lands in CIO memory through the existing governed write
   (``security_research_spine.upsert_research_memory``, silo ``cio``, kind ``prospectus_news_note``,
   ``thesis_patch=None``).
4. impact in {thesis, breaker, stop} → a rewrite reason for the window (``news_thesis`` / ``news_breaker`` /
   ``news_stop``); none / watch → note only. At most one news-driven rewrite per symbol per day. A news rewrite is a
   DELTA (``delta_max_output_tokens``) except a breaker hit or an earnings item, which are FULL; Watch rows are written
   through the batch (which writes full reports).

The per-symbol log ``<prospectus base>/<SYM>/news.json`` (written only by the window lane) carries the gate verdicts,
the notes, the price and stop snapshot the "Since this report" strip reads, and the day's note spend.

READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): a note never sizes, orders, stops or weights; it can only ask for a rewrite.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable

from . import news_gate, store

LOG_SCHEMA = "ProspectusNewsLog@v1"
NOTE_SCHEMA = "ProspectusNewsNote@v1"
PROCESS_CLASSIFY = "prospectus_news_classify"
PROCESS_NOTE = "prospectus_cio_news_note"
IMPACTS = ("none", "watch", "thesis", "breaker", "stop")
REWRITE_IMPACTS = ("thesis", "breaker", "stop")
IMPACT_PRIORITY = {"breaker": 0, "stop": 1, "thesis": 2}
SPINE_KIND = "prospectus_news_note"
SPINE_TAGS = ("prospectus", "news", "cio_note")
DEFAULTS = {"per_symbol_note_usd_per_day": 0.10, "max_notes_per_symbol_per_day": 3, "max_news_rewrites_per_day": 1,
            "classify_max_items": 12, "classify_max_output_tokens": 600, "note_max_output_tokens": 400,
            "timeout_s": 90, "scopes": ["holding", "watch"], "log_keep": 60}
BEHAVIOR_RE = re.compile(
    r"(?i)\b(?:buy|sell|trim|add to|reduce|exit|short|cover)\b[^.]{0,40}\b(?:shares?|position|stake|units?)\b|"
    r"\b(?:place|submit|enter)\b[^.]{0,20}\border\b|\b(?:move|set|raise|lower|tighten|widen)\b[^.]{0,20}\bstop\b|"
    r"\bposition siz\w+|\ballocat\w+ \d")


class CreditUnavailable(RuntimeError):
    """The governed credit refused (cap, pause, outage): nothing is spent; the item waits for the next window."""


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **((cfg or {}).get("news") or {})}


def today(now: datetime) -> str:
    return now.astimezone(timezone.utc).date().isoformat()


# ── the log ───────────────────────────────────────────────────────────────────────────────────────────────────
def log_path(base: Path, symbol: str) -> Path:
    return Path(base) / str(store.norm_symbol(symbol)) / "news.json"


def read_log(base: Path, symbol: str) -> dict:
    doc = store._read_json(log_path(base, symbol), None)
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
        doc = {"schema": LOG_SCHEMA, "symbol": store.norm_symbol(symbol), "items": {}}
    for k in ("spend", "rewrites", "notes_count"):
        doc.setdefault(k, {})
    return doc


def write_log(base: Path, symbol: str, doc: dict, keep: int = 60) -> None:
    items = sorted(doc["items"].values(), key=lambda r: str(r.get("at") or ""), reverse=True)[:keep]
    doc["items"] = {r["id"]: r for r in items}
    for k in ("spend", "rewrites", "notes_count"):
        doc[k] = {d: v for d, v in sorted(doc[k].items())[-14:]}
    store.write_json(log_path(base, symbol), doc)


# ── model calls (injected in tests; production goes through the governed credit path) ─────────────────────────
def _governed(prompt: str, *, process_id: str, max_tokens: int, timeout: float) -> tuple[str, dict]:
    from .generate import _credit_refusal, governed_generate  # noqa: PLC0415
    try:
        return governed_generate(prompt, process_id=process_id, max_tokens=max_tokens, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        if _credit_refusal(exc):
            raise CreditUnavailable(str(exc)[:200]) from exc
        raise


def _json_obj(text: str) -> Any:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw)
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"[\[{].*[\]}]", raw, re.S)
        if not m:
            raise ValueError("MODEL_OUTPUT_NOT_JSON")
        return json.loads(m.group(0))


def classify_prompt(symbol: str, name: str, rows: list[dict]) -> str:
    lines = [f'{r["id"]} | {str(r.get("source") or "")[:40]} | {str(r.get("title") or "")[:240]}' for r in rows]
    return (
        f"You label news items for ONE security: ticker {symbol}, issuer \"{name}\" (a US listing).\n"
        "For each item decide (1) relevant: is it about THIS issuer — not another company that shares the ticker on "
        "another exchange, not a passing mention; (2) material: could it change an investment thesis — earnings, "
        "guidance, rating up/downgrade, M&A, dividend change, a major contract, regulatory action, a filing, "
        "management change. Market-wrap lists, price-move recaps and promotional articles are not material.\n"
        'Return ONLY JSON: {"items": [{"id": "<id>", "relevant": true|false, "material": true|false, '
        '"why": "<= 15 words"}]}\n\nITEMS (id | source | title):\n' + "\n".join(lines))


def classify(symbol: str, name: str, rows: list[dict], *, cfg: dict, generate_fn: Callable | None = None) -> tuple[dict, dict]:
    """({id: {relevant, material, why}}, provenance). Raises CreditUnavailable when the credit refuses."""
    s = settings(cfg)
    rows = rows[: int(s["classify_max_items"])]
    if not rows:
        return {}, {}
    gen = generate_fn or _governed
    text, prov = gen(classify_prompt(symbol, name, rows), process_id=PROCESS_CLASSIFY,
                     max_tokens=int(s["classify_max_output_tokens"]), timeout=float(s["timeout_s"]))
    doc = _json_obj(text)
    out = {}
    ids = {r["id"] for r in rows}
    for r in (doc.get("items") if isinstance(doc, dict) else doc) or []:
        if isinstance(r, dict) and r.get("id") in ids:
            out[r["id"]] = {"relevant": bool(r.get("relevant")), "material": bool(r.get("material")),
                            "why": str(r.get("why") or "")[:160]}
    return out, dict(prov or {})


def prospectus_context(doc: dict | None) -> dict:
    """What the note reads: verdict, thesis breakers, the house stop plan and the scenarios (ProspectusMemory@v1)."""
    from .cio_memory import memory_record  # noqa: PLC0415
    rec = memory_record(doc or {}) if doc else {}
    return {"verdict_line": rec.get("verdict_line"), "thesis_breakers": rec.get("thesis_breakers") or [],
            "key_risks": (rec.get("key_risks") or [])[:4], "house_stop_plan": rec.get("house_stop_plan"),
            "scenarios": rec.get("scenarios") or [], "version": rec.get("version"), "written_at": rec.get("written_at")}


def note_prompt(symbol: str, name: str, item: dict, ctx: dict) -> str:
    breakers = "\n".join(f"  B{i + 1}. {b}" for i, b in enumerate(ctx.get("thesis_breakers") or [])) or "  (none listed)"
    scen = "; ".join(f"{c.get('case')}: {c.get('price')} ({c.get('probability_pct')}%)" for c in ctx.get("scenarios") or [])
    sp = ctx.get("house_stop_plan") or {}
    stop = (f"house advisory level {sp.get('recommended_level')} ({sp.get('method')}); broker level "
            f"{sp.get('broker_level')} ({sp.get('broker_state')})") if sp else "no stop plan recorded"
    return (
        f"You are the CIO reading ONE new item against the latest research prospectus for {symbol} ({name}).\n"
        f"Prospectus verdict ({str(ctx.get('written_at') or '')[:10]}): {ctx.get('verdict_line') or 'n/a'}\n"
        f"Thesis breakers:\n{breakers}\nScenarios: {scen or 'n/a'}\nStop plan: {stop}\n\n"
        f"NEW ITEM ({str(item.get('at') or '')[:16]}, {item.get('source')}, type {item.get('catalyst_type') or 'headline'}):\n"
        f"  {str(item.get('title') or '')[:400]}\n\n"
        "Classify its impact on THIS prospectus: none (noise for the thesis), watch (worth tracking, thesis intact), "
        "thesis (changes a thesis assumption or scenario), breaker (hits or nearly hits a listed thesis breaker — name "
        "it), stop (makes the stop plan's assumption about price or volatility wrong). Research only: never recommend "
        "buying, selling, sizing, orders or moving a stop.\n"
        'Return ONLY JSON: {"impact": "none|watch|thesis|breaker|stop", "which_breaker": "B<n> or null", '
        '"one_line": "<= 25 words, why"}')


def parse_note(text: str) -> dict:
    doc = _json_obj(text)
    if not isinstance(doc, dict):
        raise ValueError("NOTE_SCHEMA_INVALID")
    impact = str(doc.get("impact") or "").strip().lower()
    if impact not in IMPACTS:
        raise ValueError(f"NOTE_IMPACT_INVALID:{impact[:20]}")
    one = " ".join(str(doc.get("one_line") or "").split())[:240]
    guarded = bool(BEHAVIOR_RE.search(one))
    if guarded:  # MBI_BEHAVIOR=0: a note that reads as an instruction is withheld, the impact label is kept
        one = "(note text withheld: it read as a trading instruction; research only)"
    wb = doc.get("which_breaker")
    return {"impact": impact, "which_breaker": str(wb)[:40] if wb not in (None, "", "null") else None,
            "one_line": one, "behavior_guarded": guarded}


def cio_note(symbol: str, name: str, item: dict, doc: dict | None, *, cfg: dict,
             generate_fn: Callable | None = None) -> dict:
    """One governed Sonnet read. Raises CreditUnavailable when the credit refuses."""
    s = settings(cfg)
    gen = generate_fn or _governed
    ctx = prospectus_context(doc)
    text, prov = gen(note_prompt(symbol, name, item, ctx), process_id=PROCESS_NOTE,
                     max_tokens=int(s["note_max_output_tokens"]), timeout=float(s["timeout_s"]))
    note = parse_note(text)
    prov = dict(prov or {})
    note.update(schema=NOTE_SCHEMA, model=prov.get("model") or prov.get("model_id"),
                cost_usd=float(prov.get("cost_usd") or prov.get("cost") or 0.0),
                against_version=ctx.get("version"), advisory="READ_ONLY_ADVISORY: research note; never an order")
    return note


def spine_write(symbol: str, item: dict, note: dict, *, root: Path, spine_path: Path | None = None) -> dict:
    """The note into CIO memory via the existing governed write (silo cio). Never raises."""
    try:
        from scripts.lib.cross_asset.events import spine_write_enabled  # noqa: PLC0415
        if not spine_write_enabled():
            return {"outcome": "skipped", "reason": "CROSS_ASSET_SPINE_off"}
        from .cio_memory import _spine  # noqa: PLC0415
        summary = (f"Prospectus news note {symbol} ({note.get('at', '')[:10]}): impact {note['impact']}"
                   + (f" ({note['which_breaker']})" if note.get("which_breaker") else "")
                   + f" — {note.get('one_line')} · item: {str(item.get('title') or '')[:200]}")
        res = _spine().upsert_research_memory(
            symbol, silo="cio", kind=SPINE_KIND, summary=summary[:800], artifact_id=f"prospectus_news:{symbol}:{item['id']}",
            refs=[r for r in (item.get("url"), f"/v3/prospectus/{symbol}") if r], tags=list(SPINE_TAGS),
            thesis_patch=None, root=Path(root), path=spine_path,
            llm={"source": PROCESS_NOTE, "model": note.get("model"), "kind": SPINE_KIND, "as_of": note.get("at"),
                 "note": "prospectus_news_note_not_tip_thesis"})
        return {"outcome": "written" if res.get("ok") else "refused", "reason": res.get("error")}
    except Exception as exc:  # noqa: BLE001 - memory never takes the window down
        return {"outcome": "error", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}


# ── one symbol, one window ────────────────────────────────────────────────────────────────────────────────────
def _last_close(sources: Any, sym: str) -> dict | None:
    try:
        bars = [b for b in (sources.bars(sym) or []) if b.get("close")]
    except Exception:  # noqa: BLE001
        return None
    if not bars:
        return None
    b = bars[-1]
    return {"close": float(b["close"]), "date": str(b.get("price_date") or b.get("date") or "")[:10]}


def _report_close(doc: dict | None) -> float | None:
    for f in (doc or {}).get("facts") or []:
        if re.match(r"(?i)^last close", str(f.get("label") or "")):
            try:
                return float(f.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def review_symbol(base: Path, row: dict, entry: dict, sources: Any, cfg: dict, *, now: datetime, apply: bool,
                  holding: dict | None = None, classify_fn: Callable | None = None, note_fn: Callable | None = None,
                  spine_fn: Callable | None = None, root: Path | None = None) -> dict:
    """Gate, classify, note and decide for one symbol. Returns ``{symbol, decision, audit, cost_usd}`` where
    ``decision`` is None or ``{reason, mode}``. Dry runs (``apply=False``) call no model and write nothing."""
    s = settings(cfg)
    sym, scope = row["symbol"], row.get("scope", "watch")
    out: dict[str, Any] = {"symbol": sym, "scope": scope, "decision": None, "audit": [], "cost_usd": 0.0}
    gen = news_gate.since(entry.get("generated_at"))
    if gen is None or scope not in s["scopes"]:
        return out
    log = read_log(base, sym)
    if log.get("report_version") != entry.get("version"):
        log.update(report_version=entry.get("version"), report_written_at=entry.get("generated_at"), items={})
    name = str(entry.get("name") or sym)
    identity = {"name": name, "cik": entry.get("cik"), "exchange": entry.get("exchange")}
    try:
        cats = sources.catalysts(sym) or []
    except Exception:  # noqa: BLE001 - an unreadable feed is an empty one for this window
        cats = []
    try:
        news = sources.news(sym) or []
    except Exception:  # noqa: BLE001
        news = []
    rows = news_gate.review(sym, news_gate.normalise(cats, news), since=gen, identity=identity, known=log["items"])
    day = today(now)
    uncertain = [r for r in rows if r.get("verdict") == "uncertain"]
    labels: dict = {}
    if uncertain and apply:
        try:
            labels, prov = (classify_fn or (lambda *a, **k: classify(*a, cfg=cfg, **k)))(sym, name, uncertain)
            out["cost_usd"] += float((prov or {}).get("cost_usd") or 0)
        except CreditUnavailable as exc:
            out["classifier_error"] = str(exc)[:160]
        except Exception as exc:  # noqa: BLE001 - a bad read leaves the items for the next window
            out["classifier_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    if apply:
        news_gate.apply_classification(rows, labels)
    doc = None
    rewrite_impacts: list[dict] = []
    for r in rows:
        if r.get("verdict") != "accepted":
            continue
        if r.get("note"):
            if r["note"].get("impact") in REWRITE_IMPACTS and not r.get("rewrite_requested"):
                rewrite_impacts.append(r)
            continue
        if not apply:
            r["status"] = "would_note"
            continue
        if float(log["spend"].get(day, 0)) >= float(s["per_symbol_note_usd_per_day"]) \
                or int(log["notes_count"].get(day, 0)) >= int(s["max_notes_per_symbol_per_day"]):
            r.update(status="note_deferred", reason="note_cap")
            continue
        if doc is None:
            doc = store.read_prospectus(base, sym) or {}
        try:
            note = (note_fn or (lambda *a, **k: cio_note(*a, cfg=cfg, **k)))(sym, name, r, doc)
        except CreditUnavailable as exc:
            r.update(status="note_deferred", reason="note_cap", note_error=str(exc)[:160])
            continue
        except Exception as exc:  # noqa: BLE001
            r.update(status="note_failed", note_error=f"{type(exc).__name__}: {str(exc)[:120]}")
            continue
        note["at"] = now.isoformat()
        r["note"] = note
        cost = float(note.get("cost_usd") or 0)
        out["cost_usd"] += cost
        log["spend"][day] = round(float(log["spend"].get(day, 0)) + cost, 6)
        log["notes_count"][day] = int(log["notes_count"].get(day, 0)) + 1
        r["memory"] = (spine_fn or (lambda *a, **k: spine_write(*a, root=root or Path("."), **k)))(sym, r, note)
        if note["impact"] in REWRITE_IMPACTS:
            rewrite_impacts.append(r)
        else:
            r.update(status="cio_no_impact", reason="cio_no_impact")
    if rewrite_impacts:
        first = sorted(rewrite_impacts, key=lambda r: IMPACT_PRIORITY[r["note"]["impact"]])[0]
        if len(log["rewrites"].get(day) or []) >= int(s["max_news_rewrites_per_day"]):
            for r in rewrite_impacts:
                r.update(status="coalesced", reason="coalesced")
        else:
            impact = first["note"]["impact"]
            full = impact == "breaker" or str(first.get("catalyst_type") or "") in news_gate.FULL_TYPES
            mode = "full" if full or scope == "watch" else "delta"  # Watch goes through the batch (full reports)
            out["decision"] = {"reason": f"news_{impact}", "mode": mode, "item": first["id"]}
            if apply:
                log["rewrites"].setdefault(day, []).append({"reason": f"news_{impact}", "item": first["id"], "mode": mode})
            for r in rewrite_impacts:
                r.update(status="queued", rewrite_requested=now.isoformat() if apply else None)
                if r is not first:
                    r["reason"] = "coalesced"
    for r in rows:
        r.setdefault("status", {"accepted": "accepted", "uncertain": "would_classify"}.get(r.get("verdict"), "rejected"))
        out["audit"].append({"symbol": sym, "id": r["id"], "title": str(r.get("title") or "")[:160],
                             "verdict": r.get("verdict"), "reason": r.get("reason"), "status": r.get("status"),
                             "impact": (r.get("note") or {}).get("impact")})
    if apply:
        for r in rows:
            log["items"][r["id"]] = r
        last = _last_close(sources, sym)
        then = _report_close(store.read_prospectus(base, sym) if doc is None else doc)
        log["price"] = {"at_report": then, **(last or {}),
                        "move_pct": round((last["close"] / then - 1) * 100, 2) if last and then else None}
        digest = entry.get("inputs_digest") or {}
        if scope == "holding" and holding is not None and digest.get("stop_levels") is not None:
            try:
                now_levels = sorted(float(x["stop_price"]) for x in sources.stops(sym, holding.get("accounts") or [])
                                    if x.get("stop_price") is not None)
            except Exception:  # noqa: BLE001
                now_levels = None
            if now_levels is not None:
                then_levels = [float(x) for x in digest["stop_levels"]]
                log["stops"] = {"at_report": then_levels, "now": now_levels,
                                "changed": [round(x, 4) for x in now_levels] != [round(x, 4) for x in then_levels]}
        log["checked_at"] = now.isoformat()
        write_log(base, sym, log, keep=int(s["log_keep"]))
    return out


def review_universe(base: Path, universe: list[dict], index: dict, sources: Any, cfg: dict, *, now: datetime,
                    apply: bool, holdings: dict | None = None, scopes: list[str] | None = None, **fns: Any) -> dict:
    """Every symbol of a window. Returns ``{decisions: {SYM: {reason, mode}}, audit: {...}, cost_usd}``."""
    items = (index or {}).get("items") or {}
    decisions: dict[str, dict] = {}
    audit: list[dict] = []
    cost = 0.0
    errors = []
    for row in universe:
        if scopes and row.get("scope") not in scopes:
            continue
        entry = items.get(row["symbol"]) or {}
        if not entry.get("generated_at"):
            continue
        try:
            res = review_symbol(base, row, entry, sources, cfg, now=now, apply=apply,
                                holding=(holdings or {}).get(row["symbol"]), **fns)
        except Exception as exc:  # noqa: BLE001 - one symbol never stops the window
            errors.append({"symbol": row["symbol"], "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue
        if res.get("decision"):
            decisions[row["symbol"]] = res["decision"]
        audit += res["audit"]
        cost += float(res.get("cost_usd") or 0)
        if res.get("classifier_error"):
            errors.append({"symbol": row["symbol"], "error": res["classifier_error"]})
    return {"decisions": decisions, "summary": summarize(audit, decisions), "cost_usd": round(cost, 6),
            "errors": errors}


def summarize(audit: list[dict], decisions: dict) -> dict:
    """The receipt / email audit block: counts by reason, accepted rows, rejected rows (capped)."""
    counts: dict[str, int] = {}
    for a in audit:
        key = "accepted" if a["verdict"] == "accepted" and not a.get("reason") else (a.get("reason") or a.get("status") or a["verdict"])
        counts[key] = counts.get(key, 0) + 1
    accepted = [a for a in audit if a["verdict"] == "accepted"]
    rejected = [a for a in audit if a["verdict"] != "accepted"]
    return {"counts": counts, "rewrites": {s: d["reason"] for s, d in decisions.items()},
            "accepted": accepted[:40], "rejected": rejected[:60], "rejected_total": len(rejected)}


# ── the strip (API read side; no model, no DB) ────────────────────────────────────────────────────────────────
def since_report(base: Path, symbol: str, doc: dict, *, cfg: dict, queue_row: dict | None = None,
                 next_window: dict | None = None, max_items: int = 8) -> dict:
    """``since_report`` for GET /api/v2/prospectus/{sym}: what happened after this version was written, read from the
    news log the window lane keeps. Cheap: one small JSON file."""
    log = read_log(base, symbol)
    written = doc.get("generated_at")
    same = log.get("report_version") in (None, doc.get("version"))
    rows = [r for r in log["items"].values() if same and r.get("relevant") is not False
            and r.get("reason") not in ("duplicate", "collision")]
    rows.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    win = (next_window or {})
    label = f"queued for the {win.get('time') or 'next'} run" if win else "queued for the next run"
    items = []
    for r in rows[:max_items]:
        note = r.get("note") or {}
        if r.get("status") == "queued" or (queue_row and str(queue_row.get("reason") or "").startswith("news_")
                                           and queue_row.get("item") == r["id"]):
            status = label
        elif note:
            status = f"CIO note: {'no impact' if note.get('impact') == 'none' else note.get('impact')}"
        elif r.get("verdict") == "accepted":
            status = "CIO note pending (next run)" if r.get("status") != "note_deferred" else "CIO note deferred (daily cap)"
        elif r.get("reason") == "not_material":
            status = "not material"
        else:
            status = "checked at the next run" if r.get("verdict") == "uncertain" or r.get("retry") else "not material"
        items.append({"id": r["id"], "at": r.get("at"), "kind": r.get("kind"), "title": r.get("title"),
                      "source": r.get("source"), "url": r.get("url"), "material": r.get("verdict") == "accepted",
                      "badge": "material" if r.get("verdict") == "accepted" else "not material",
                      "status": status, "note": ({k: note.get(k) for k in ("impact", "which_breaker", "one_line", "at")}
                                                 if note else None)})
    rejected = {}
    for r in log["items"].values() if same else []:
        if r.get("reason") in ("collision", "duplicate"):
            rejected[r["reason"]] = rejected.get(r["reason"], 0) + 1
    price = log.get("price") or {}
    stops = log.get("stops") or {}
    stop_events = []
    if stops.get("changed"):
        stop_events.append({"kind": "stop_change", "at_report": stops.get("at_report"), "now": stops.get("now"),
                            "status": label if queue_row and queue_row.get("reason") == "stop_event" else "stop levels changed"})
    return {"schema": "ProspectusSinceReport@v1", "written_at": written, "checked_at": log.get("checked_at") if same else None,
            "items": items, "item_count": len(rows), "hidden": rejected,
            "price": {"at_report": price.get("at_report"), "last_close": price.get("close"), "as_of": price.get("date"),
                      "move_pct": price.get("move_pct")} if same and price else None,
            "stop_events": stop_events if same else [],
            "rewrite": ({"reason": queue_row.get("reason"), "status": label} if queue_row else None),
            "next_window": win or None,
            "advisory": "READ_ONLY_ADVISORY: news and notes are research; never an order"}
