#!/usr/bin/env python3
"""Watch-list prospectus model evaluation: Claude Sonnet 5.5 against the stored Claude Opus 5.5 reports.

Operator 2026-10-27 (coordinator session): "Yes, ... let me test." Watch reports move to Sonnet only if Sonnet matches
Opus on accuracy and the operator likes the reading; holdings stay on Opus and the top 5 on Fable. This script only
measures; it changes no production routing.

What it does, per symbol (Watch scope only, never a holding):

* assembles the inputs with the production path (``domains.full_assemble``) and writes the report with the production
  writer (``generate.write``: data-quality gate first, then the web planning turn, then the writer turn, the same
  prompt, the Watch generation settings from config/prospectus_generation.json: 5,000 output tokens, effort medium);
* the only change is the writer's credit tier: tier ``mid`` (claude-sonnet-5-5), synchronous, recorded as process
  ``prospectus_writer`` through ``llm_consumption.gate_and_generate`` (the governed Anthropic credit path: credit
  journal, DB backstop, process caps). ``eval_route()`` applies that override inside this process only;
* scores the new Sonnet report and the stored Opus report the same way: the data-quality gate
  (``quality_gate.review_doc``, layer 2 Haiku when ``--ai-gate``), the standing accuracy auditor
  (``accuracy_audit.audit``), a prose spot check (numbers and dates against the cited facts and the house data now),
  completeness, specificity, length, tokens and cost;
* renders the Sonnet report with the production renderer and writes ``comparison.json``, ``SCORECARD.md``,
  ``comparison.html`` and the PDF pairs to ``--out`` (a private directory: never the prospectus store, index or queue).

    python3 scripts/prospectus_model_eval.py candidates --hours 48            # free: READY Opus Watch reports
    python3 scripts/prospectus_model_eval.py run --symbols A,B --out DIR      # dry run: assemble, gate, size, limits
    python3 scripts/prospectus_model_eval.py run --symbols A,B --out DIR --apply --ai-gate   # paid, <= --cap-usd
    python3 scripts/prospectus_model_eval.py score --out DIR                  # free: rescore the saved reports

Every limit is read before a paid run (AGENTS.md section 29): the credit journal, the DB backstop, the process cost and
request caps, the per-call cap and the search budget. The run is sized under the lowest of them and under the
harness's own hard cap (``--cap-usd``, default $3); a refusal stops the run cleanly and the scores cover what finished.
READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): research text only; no sizing, orders, stops or weights.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import html as _html
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Callable, Iterator, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import load_config, sections_for, store  # noqa: E402

SCHEMA = "ProspectusModelEval@v1"
WRITER_PROCESS = "prospectus_writer"     # recorded as the production writer (coordinator brief 2026-10-27)
EVAL_TIER = "mid"                        # config/anthropic_credit_policy.json models.mid
EVAL_MODEL = "claude-sonnet-5-5"
BASELINE_MODEL = "claude-opus-5-5"
#: The writer turn reserves 2 attempts x (prompt bytes + framing at the cache-write price + 5,000 output tokens):
#: ~$0.24 on Sonnet for a ~23 KB Watch prompt, over the $0.10 per-call cap of tier ``mid`` (sized for the CIO news
#: note). Inside this process only, tier ``mid`` gets this ceiling (long_form, the Opus writer tier, has $2.00).
EVAL_PER_CALL_CAP_USD = "0.50"
EVAL_EFFORT = "medium"                   # config/prospectus_generation.json generation.watch.effort
DEFAULT_CAP_USD = 3.0                    # the operator-approved ceiling for the whole test
SEARCHES_PER_SYMBOL = 3                  # config/prospectus.json web.max_uses.watch
VAGUE_RE = re.compile(r"\b(?:significant(?:ly)?|substantial(?:ly)?|strong(?:ly)?|robust|solid|meaningful(?:ly)?|"
                      r"considerabl[ey]|various|several|numerous|many|potentially|somewhat|relatively|notabl[ey])\b", re.I)
SENT_RE = re.compile(r"(?<=[.!?])\s+")
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
WORD_DATE_RE = re.compile(r"\b(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?"
                          r"(?:,?\s+(\d{4}))?\b", re.I)
PLACEHOLDER = "No statement in this section survived source validation"
KIND_WORDS = (("target", ("target",)), ("date", ("date", "earnings")), ("return", ("return", "change", "%")),
              ("price", ("close", "price", "high", "low", "average")))


class BudgetStop(RuntimeError):
    """The harness's own hard cap would be crossed by the next call. The message carries COST_CAP so the production
    writer classifies it as a credit refusal (QueueLater): the run stops, nothing falls back."""


# ── the eval route: tier mid for the writer, effort medium, this process only ─────────────────────────────────────
def overlay_policy(policy: dict, *, process_id: str = WRITER_PROCESS, tier: str = EVAL_TIER,
                   per_call_cap: str = EVAL_PER_CALL_CAP_USD) -> dict:
    """A copy of the credit policy with ``process_id`` pinned to ``tier``. Additive only: the tier's per-call ceiling
    is raised to ``per_call_cap`` when lower and never lowered; the tier runs with adaptive thinking like the Opus
    writer tier (``thinking_tiers``). Total, daily, process and request caps are untouched."""
    out = deepcopy(policy)
    if (out.get("models") or {}).get(tier) != EVAL_MODEL:
        raise RuntimeError(f"CREDIT_CONFIGURATION_INVALID: tier {tier} is not {EVAL_MODEL}")
    out.setdefault("process_tiers", {})[process_id] = tier
    caps = out.setdefault("per_call_caps_usd", {})
    if Decimal(str(caps.get(tier) or "0")) < Decimal(per_call_cap):
        caps[tier] = per_call_cap
    tiers = list(out.get("thinking_tiers") or [])
    if tier not in tiers:
        out["thinking_tiers"] = tiers + [tier]
    out["_eval_overlay"] = {"process_id": process_id, "tier": tier, "per_call_cap_usd": caps[tier],
                            "effort": EVAL_EFFORT, "by": "scripts/prospectus_model_eval.py"}
    return out


def _credit_modules() -> list[Any]:
    """Every loaded copy of the transport / routing modules (they load as ``lib.*`` and ``scripts.lib.*``)."""
    import importlib
    for name in ("lib.anthropic_transport", "lib.anthropic_routing", "scripts.lib.anthropic_transport",
                 "scripts.lib.anthropic_routing"):
        try:
            importlib.import_module(name)
        except ImportError:
            continue
    return [m for n, m in list(sys.modules.items())
            if m is not None and n.split(".")[-1] in ("anthropic_transport", "anthropic_routing")]


@contextmanager
def eval_route(*, effort: str = EVAL_EFFORT) -> Iterator[dict]:
    """Inside the block, ``prospectus_writer`` resolves to tier ``mid`` (Sonnet 5.5) with output effort ``effort``.

    It wraps ``load_policy`` (the policy every governed call reads) and the transport's per-model reasoning settings,
    and restores both on exit. The call still goes through gate_and_generate → CreditBook journal → DB backstop.
    """
    saved: list[tuple[Any, str, Any]] = []
    for mod in _credit_modules():
        orig = getattr(mod, "load_policy", None)
        if callable(orig) and not getattr(orig, "_eval_overlay", False):
            def wrapped(*a: Any, _orig: Callable = orig, **k: Any) -> dict:
                return overlay_policy(_orig(*a, **k))
            wrapped._eval_overlay = True  # type: ignore[attr-defined]
            saved.append((mod, "load_policy", orig))
            setattr(mod, "load_policy", wrapped)
        rs = getattr(mod, "_reasoning_settings", None)
        if callable(rs) and not getattr(rs, "_eval_overlay", False):
            def settings(model: str, thinking: str, policy: Any, _orig: Callable = rs) -> dict:
                out = _orig(model, thinking, policy)
                if model == EVAL_MODEL and thinking == "enabled":
                    out = dict(out, output_config=dict(out.get("output_config") or {}, effort=effort))
                return out
            settings._eval_overlay = True  # type: ignore[attr-defined]
            saved.append((mod, "_reasoning_settings", rs))
            setattr(mod, "_reasoning_settings", settings)
    try:
        yield {"patched": sorted({f"{m.__name__}.{a}" for m, a, _ in saved})}
    finally:
        for mod, attr, orig in reversed(saved):
            setattr(mod, attr, orig)


# ── budget ────────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Budget:
    """The harness's hard cap. Before each call the worst case (that tier's per-call ceiling) must fit; after it the
    settled cost from the provenance is added. Every call is listed in ``calls``."""
    cap_usd: float
    spent_usd: float = 0.0
    calls: list[dict] = field(default_factory=list)

    def check(self, worst_usd: float, what: str) -> None:
        if self.spent_usd + worst_usd > self.cap_usd + 1e-9:
            raise BudgetStop(f"COST_CAP_EXCEEDED: eval hard cap ${self.cap_usd:.2f} (spent ${self.spent_usd:.4f}, "
                             f"next {what} may hold ${worst_usd:.2f})")

    def add(self, what: str, prov: dict, symbol: str | None) -> None:
        cost = float((prov or {}).get("estimated_cost_usd") or 0.0)
        self.spent_usd = round(self.spent_usd + cost, 6)
        usage = (prov or {}).get("usage") or {}
        self.calls.append({"what": what, "symbol": symbol, "cost_usd": cost,
                           "model": (prov or {}).get("returned_model") or (prov or {}).get("model_id"),
                           "provider": (prov or {}).get("provider"), "fallback": (prov or {}).get("fallback"),
                           "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")})


def budget_writer(fn: Callable, budget: Budget, *, worst_usd: float, symbol_ref: dict) -> Callable:
    """Wrap the writer call (the production ``generate_fn`` signature) with the hard cap and the call log."""
    def call(prompt: str, *, process_id: str, max_tokens: int, timeout: float, manual: bool = False):
        what = "web_plan" if '"searches"' in prompt[-1200:] or "Return ONLY a JSON object {\"searches\"" in prompt else "writer"
        budget.check(worst_usd, what)
        text, prov = fn(prompt, process_id=process_id, max_tokens=max_tokens, timeout=timeout, manual=manual)
        budget.add(what, prov, symbol_ref.get("symbol"))
        return text, prov
    return call


def budget_ai(fn: Callable, budget: Budget, *, worst_usd: float, symbol_ref: dict, what: str) -> Callable:
    def call(prompt: str, *, max_tokens: int, timeout: float):
        budget.check(worst_usd, what)
        text, prov = fn(prompt, max_tokens=max_tokens, timeout=timeout)
        budget.add(what, prov, symbol_ref.get("symbol"))
        return text, prov
    return call


# ── preflight (AGENTS.md section 29) ──────────────────────────────────────────────────────────────────────────────
def _money(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def preflight(*, state_root: Path, n_symbols: int, cap_usd: float, est_per_symbol_usd: float,
              now: datetime | None = None, policy: dict | None = None, lc: Any = None,
              search_status: Callable[[], dict] | None = None, gate_process: str = "prospectus_fact_check") -> dict:
    """Read and quote every limit that can stop the run; size the run under the lowest headroom.

    ``est_per_symbol_usd`` is the worst-case settled spend of one symbol (plan + writer at max output, plus the gate
    reads); the single largest reservation (the per-call ceiling) must also fit on top of what is already spent.
    """
    now = now or datetime.now(timezone.utc)
    from scripts.lib.anthropic_credit import CreditBook
    if policy is None:
        from scripts.lib.anthropic_transport import load_policy
        policy = overlay_policy(load_policy())
    limits: dict[str, Any] = {}
    snap = CreditBook(state_root, policy).snapshot(now=now)
    day_left = _money(snap["daily_cap_usd"]) - _money(snap["today_used_usd"]) - _money(snap["reserved_today_usd"])
    limits["credit_journal"] = {"status": snap["status"], "daily_cap_usd": snap["daily_cap_usd"],
                                "today_used_usd": snap["today_used_usd"], "reserved_today_usd": snap["reserved_today_usd"],
                                "remaining_total_usd": snap["remaining_budget_usd"], "headroom_usd": round(day_left, 4)}
    per_call = _money(policy["per_call_caps_usd"][EVAL_TIER])
    limits["per_call_cap"] = {"tier": EVAL_TIER, "usd": per_call, "bulk_usd": _money(policy["per_call_caps_usd"].get("bulk"))}
    headrooms = {"credit_daily": day_left, "credit_total": _money(snap["remaining_budget_usd"]), "eval_cap": cap_usd}
    if lc is not None:
        for pid in (WRITER_PROCESS, gate_process):
            cfg = lc.get_process_config(pid)
            spent = float(lc.ledger_paid_usd_today(pid) or 0.0)
            calls = int(lc.calls_today(pid) or 0)
            cap = float(cfg.get("daily_cost_cap_usd") or 0)
            soft = int(cfg.get("daily_soft_cap") or 0)
            limits[f"process:{pid}"] = {"daily_cost_cap_usd": cap, "spent_today_usd": round(spent, 4),
                                        "daily_soft_cap": soft, "calls_today": calls}
            if pid == WRITER_PROCESS:
                headrooms["process_cost"] = cap - spent
                headrooms["process_calls"] = (soft - calls) / 2.0 * est_per_symbol_usd  # 2 calls per symbol
        try:
            limits["db_backstop"] = db_backstop(lc, policy)
            headrooms["db_daily"] = limits["db_backstop"]["day_left_usd"]
            headrooms["db_total"] = limits["db_backstop"]["total_left_usd"]
        except Exception as exc:  # noqa: BLE001 - an unreadable backstop refuses the paid run
            limits["db_backstop"] = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
            headrooms["db_daily"] = 0.0
    limits["global_daily_provider_cap"] = {"env": "LLM_GLOBAL_DAILY_USD_CAP",
                                           "set": bool(os.environ.get("LLM_GLOBAL_DAILY_USD_CAP")),
                                           "applies": "no: promotional credit calls run with global_cap=None "
                                                      "(llm_consumption; the credit's own caps bind)"}
    if search_status is not None:
        try:
            limits["search_budget"] = search_status()
        except Exception as exc:  # noqa: BLE001 - search is optional: the writer says the data is house-only
            limits["search_budget"] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    lowest_name, lowest = min(headrooms.items(), key=lambda kv: kv[1])
    usable = lowest - per_call  # the largest single reservation must fit on top
    fit = max(0, min(n_symbols, int(usable // est_per_symbol_usd) if est_per_symbol_usd > 0 else n_symbols))
    if snap["status"] != "OK":
        fit = 0
    return {"checked_at": now.isoformat(), "limits": limits, "headroom_usd": {k: round(v, 4) for k, v in headrooms.items()},
            "lowest": lowest_name, "est_per_symbol_usd": round(est_per_symbol_usd, 4), "symbols_requested": n_symbols,
            "symbols_that_fit": fit, "ok": fit > 0}


def db_backstop(lc: Any, policy: dict) -> dict:
    """The durable promotion caps the DB guard enforces (llm_cost_reservations), read-only."""
    conn = lc._conn()
    cur = conn.cursor()
    cur.execute("""SELECT
        COALESCE(SUM(GREATEST((CASE WHEN status='reserved' THEN projected_usd ELSE actual_usd END)
            - COALESCE((metadata_json->>'paid_component_usd')::numeric,0),0)),0),
        COALESCE(SUM(GREATEST((CASE WHEN status='reserved' THEN projected_usd ELSE actual_usd END)
            - COALESCE((metadata_json->>'paid_component_usd')::numeric,0),0))
            FILTER (WHERE (COALESCE((metadata_json->>'funding_settled_at')::timestamptz,created_at) AT TIME ZONE 'UTC')::date
                = (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date),0)
        FROM llm_cost_reservations WHERE status IN ('reserved','settled') AND metadata_json->>'promotion_id'=%s""",
                (policy["promotion_id"],))
    total, day = cur.fetchone()
    conn.rollback()
    cap_day = float(lc.credit_daily_cap_usd(policy, datetime.now(timezone.utc)))
    return {"used_total_usd": round(float(total), 4), "used_today_usd": round(float(day), 4),
            "total_cap_usd": float(policy["total_cap_usd"]), "daily_cap_usd": cap_day,
            "total_left_usd": round(float(policy["total_cap_usd"]) - float(total), 4),
            "day_left_usd": round(cap_day - float(day), 4)}


def estimate_symbol_usd(prompt_bytes: int, *, pricing: dict, cfg: dict, gen: dict, ai_reads: int) -> float:
    """Worst-case settled cost of one symbol: the plan turn and the writer turn at their max output, plus the gate reads."""
    p = pricing.get(EVAL_MODEL) or {}
    tin = prompt_bytes / float((cfg.get("estimate") or {}).get("chars_per_token", 3.6))
    plan_out = int((cfg.get("web") or {}).get("plan_max_output_tokens", 4000))
    out = int(((gen.get("generation") or {}).get("watch") or {}).get("max_output_tokens") or 5000)
    usd = (2 * tin * _money(p.get("input")) + (plan_out + out) * _money(p.get("output"))) / 1e6
    h = pricing.get("claude-haiku-5-5") or {}
    usd += ai_reads * (8000 * _money(h.get("input")) + 1200 * _money(h.get("output"))) / 1e6
    return round(usd, 4)


# ── scoring ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _words(text: str) -> int:
    return len(re.findall(r"\b\w[\w'%.-]*\b", text or ""))


def _plain(md: str) -> str:
    return re.sub(r"\[(?:[FW]\d+(?:\s*,\s*[FW]\d+)*)\]", "", md or "")


def label_kind(label: str) -> str:
    low = (label or "").lower()
    for kind, words in KIND_WORDS:
        if any(w in low for w in words):
            return kind
    return "other"


def _fact_dates(facts: list[dict]) -> set[str]:
    out: set[str] = set()
    for f in facts:
        for v in (f.get("as_of"), f.get("text"), f.get("label")):
            for m in ISO_DATE_RE.finditer(str(v or "")):
                out.add(m.group(0))
            for m in WORD_DATE_RE.finditer(str(v or "")):
                mon = next(i for i, name in enumerate(MONTHS, 1) if name.startswith(m.group(1).lower()[:3]))
                out.add(f"{m.group(3) or '*'}-{mon:02d}-{int(m.group(2)):02d}")
    return out


def _prose_dates(text: str) -> list[str]:
    out = [m.group(0) for m in ISO_DATE_RE.finditer(text)]
    for m in WORD_DATE_RE.finditer(text):
        mon = next(i for i, name in enumerate(MONTHS, 1) if name.startswith(m.group(1).lower()[:3]))
        out.append(f"{m.group(3) or '*'}-{mon:02d}-{int(m.group(2)):02d}")
    return out


def _date_known(d: str, known: set[str]) -> bool:
    if d in known:
        return True
    y, md = d.split("-", 1)
    return any(k.endswith(md) and (y == "*" or k.startswith(y) or k.startswith("*")) for k in known)


def spot_check(doc: dict, *, house_facts: list[dict] | None = None, settings: dict | None = None) -> dict:
    """Numbers and dates in the prose against the facts the sentence cites, then the key facts against the house data
    now (``house_facts``: a fresh assembly of the same symbol).

    Per number: ``ok`` (matches a cited fact), ``uncited`` (matches a fact the sentence does not cite) or
    ``unsupported`` (matches no fact). Each is tagged price / return / target / date / other by the cited labels.
    """
    from scripts.lib.prospectus import quality_gate as qg
    s = settings or qg.load_settings()
    rel = float(s["post_write_rel_tol"])
    facts = doc.get("facts") or []
    by_id = {f["id"]: f for f in facts}
    all_vals = [v for f in facts for v in qg._fact_values(f)]
    known_dates = _fact_dates(facts)
    rows, dates = [], []
    for sec in doc.get("sections") or []:
        body = sec.get("body_md") or ""
        if PLACEHOLDER in body:
            continue
        for sent in SENT_RE.split(body.replace("\n", " ")):
            cited = {i.strip() for g in re.findall(r"\[([FW]\d+(?:\s*,\s*[FW]\d+)*)\]", sent) for i in g.split(",")}
            vals = [v for i in cited if i in by_id for v in qg._fact_values(by_id[i])]
            kinds = sorted({label_kind(by_id[i]["label"]) for i in cited if i in by_id}) or ["other"]
            for x, unit, raw in qg._numbers(sent):
                if qg._matches(x, unit, vals, rel, raw):
                    status = "ok"
                elif qg._matches(x, unit, all_vals, rel, raw):
                    status = "uncited"
                else:
                    status = "unsupported"
                rows.append({"section": sec.get("id"), "number": raw, "status": status, "kind": kinds[0],
                             "excerpt": sent.strip()[:200]})
            for d in _prose_dates(sent):
                dates.append({"section": sec.get("id"), "date": d, "status": "ok" if _date_known(d, known_dates) else "unsupported",
                              "excerpt": sent.strip()[:200]})
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "uncited", "unsupported")}
    by_kind: dict[str, dict] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], {"ok": 0, "uncited": 0, "unsupported": 0})[r["status"]] += 1
    house = house_check(facts, house_facts) if house_facts is not None else None
    return {"numbers": len(rows), "counts": counts, "by_kind": by_kind,
            "unsupported_rate": round(counts["unsupported"] / len(rows), 4) if rows else 0.0,
            "unsupported": [r for r in rows if r["status"] == "unsupported"][:25],
            "dates": {"total": len(dates), "unsupported": [d for d in dates if d["status"] != "ok"][:15]},
            "house": house}


HOUSE_LABELS = ("Last close", "1-year price change %", "Analyst target low", "Analyst target mean",
                "Analyst target high", "Next earnings date", "Market cap ($B)")


def house_check(facts: list[dict], house_facts: list[dict], *, rel_tol: float = 0.02) -> dict:
    """The key facts the report carried against the same labels in a fresh house assembly. A difference on the
    baseline can be time (it was written earlier); on the new report it must be zero."""
    mine = {f["label"]: f for f in facts}
    now = {f["label"]: f for f in house_facts}
    rows = []
    for label in HOUSE_LABELS:
        a, b = mine.get(label), now.get(label)
        if a is None or b is None:
            continue
        if "value" in a and "value" in b:
            same = abs(float(a["value"]) - float(b["value"])) <= rel_tol * max(abs(float(b["value"])), 1e-9)
            rows.append({"label": label, "report": a["value"], "house_now": b["value"], "same": same})
        else:
            rows.append({"label": label, "report": a.get("text"), "house_now": b.get("text"),
                         "same": str(a.get("text")) == str(b.get("text"))})
    return {"checked": len(rows), "differs": [r for r in rows if not r["same"]], "rows": rows}


def measure(doc: dict) -> dict:
    """Completeness, specificity and length of the written parts."""
    expected = sections_for(doc.get("scope") or "watch")
    secs = {s.get("id"): s for s in doc.get("sections") or []}
    per = {}
    total_words = numbers = cites = vague = sentences = specific = 0
    for sid in expected:
        body = (secs.get(sid) or {}).get("body_md") or ""
        empty = not body.strip() or PLACEHOLDER in body
        plain = _plain(body)
        w = _words(plain)
        sents = [x for x in SENT_RE.split(body.replace("\n", " ")) if x.strip()]
        n_num = sum(len(re.findall(r"\d[\d,]*(?:\.\d+)?", _plain(x))) for x in sents)
        n_cite = len(re.findall(r"\[(?:[FW]\d+)", body))
        spec = sum(1 for x in sents if re.search(r"\d", _plain(x)) or re.search(r"\[[FW]\d+", x))
        per[sid] = {"words": w, "empty": empty, "numbers": n_num, "citations": n_cite}
        total_words += w
        numbers += n_num
        cites += n_cite
        vague += len(VAGUE_RE.findall(plain))
        sentences += len(sents)
        specific += spec
    blocks = doc.get("blocks") or {}
    cases = ((blocks.get("scenarios") or {}).get("cases")) or []
    macro = ((blocks.get("macro_sensitivity") or {}).get("effects")) or {}
    call = blocks.get("earnings_call") or {}
    notes_filled = sum(1 for v in macro.values() if v) + sum(
        1 for k in ("guidance", "demand_margin", "tone", "hard_questions") if call.get(k))
    guard = doc.get("guard_log") or []
    drops: dict[str, int] = {}
    for g in guard:
        drops[g.get("reason") or "other"] = drops.get(g.get("reason") or "other", 0) + 1
    per100 = (lambda n: round(100.0 * n / total_words, 2) if total_words else 0.0)
    return {"sections_expected": len(expected), "sections_written": sum(1 for v in per.values() if not v["empty"]),
            "sections": per, "verdict_line": bool((doc.get("verdict_line") or "").strip()),
            "scenarios": len(cases), "scenario_probabilities": all(c.get("probability_pct") is not None for c in cases) if cases else False,
            "notes_filled": notes_filled, "notes_expected": 10,
            "words": total_words, "numbers": numbers, "citations": cites, "vague_words": vague,
            "numbers_per_100w": per100(numbers), "citations_per_100w": per100(cites), "vague_per_100w": per100(vague),
            "specific_sentence_pct": round(100.0 * specific / sentences, 1) if sentences else 0.0,
            "guard_drops": drops, "guard_drops_total": len(guard),
            "status": doc.get("status"), "partial_gaps": len(doc.get("partial_gaps") or [])}


def cost_row(doc: dict) -> dict:
    usage = doc.get("usage") or {}
    batch = doc.get("batch") or {}
    mult = float(batch.get("price_multiplier") or 1.0) if batch else 1.0
    cost = doc.get("cost_usd")
    out = {"model": doc.get("model"), "mode": "batch" if batch else "sync", "cost_usd": cost,
           "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
           "price_multiplier": mult}
    if cost is not None:
        # like-for-like: the same report on the synchronous price and on the Batch price (production Watch path)
        out["sync_equivalent_usd"] = round(float(cost) / mult, 6)
        out["batch_equivalent_usd"] = round(float(cost) / mult * 0.5, 6)
    return out


def score_doc(doc: dict, *, settings: dict, primary: Any, house_facts: list[dict] | None,
              ai_fn: Callable | None, now: datetime | None = None) -> dict:
    """Every score for one report: gate, accuracy audit, spot check, completeness/specificity/length, cost."""
    from scripts.lib.prospectus import accuracy_audit as aa
    from scripts.lib.prospectus import quality_gate as qg
    gate = qg.review_doc(doc, settings=settings, ai_fn=ai_fn)
    when = aa._dt(doc.get("generated_at")) or now or datetime.now(timezone.utc)
    audit = aa.audit(doc, primary, now=when)
    return {"symbol": doc.get("symbol"), "version": doc.get("version"), "generated_at": doc.get("generated_at"),
            "gate": {"status": gate["gate_status"], "codes": gate["codes"], "post_write": gate["post_write"],
                     "ai": {k: v for k, v in ((gate["gate"].get("layers") or {}).get("ai") or {}).items()
                            if k in ("ran", "model", "cost_usd", "reason", "fallback")},
                     "ai_findings": [r for r in gate["reasons"] if r.startswith("ai_")][:8]},
            "audit": {"counts": audit["counts"],
                      "defects": [{k: d.get(k) for k in ("code", "severity", "klass", "message")} for d in audit["defects"]][:30]},
            "spot": spot_check(doc, house_facts=house_facts, settings=settings),
            "measure": measure(doc), "cost": cost_row(doc)}


# ── verdict ───────────────────────────────────────────────────────────────────────────────────────────────────────
GATE_RANK = {"pass": 0, "soft_fail": 1, "hard_fail": 2}


def aggregate(rows: list[dict], side: str) -> dict:
    sc = [r[side] for r in rows if r.get(side)]
    if not sc:
        return {}
    tot = lambda f: sum(f(x) for x in sc)  # noqa: E731
    nums = tot(lambda x: x["spot"]["numbers"])
    return {"reports": len(sc),
            "audit_p1": tot(lambda x: x["audit"]["counts"].get("P1", 0)),
            "audit_p2": tot(lambda x: x["audit"]["counts"].get("P2", 0)),
            "audit_p3": tot(lambda x: x["audit"]["counts"].get("P3", 0)),
            "gate_pass": sum(1 for x in sc if x["gate"]["status"] == "pass"),
            "gate_hard_fail": sum(1 for x in sc if x["gate"]["status"] == "hard_fail"),
            "post_write_unmatched": tot(lambda x: x["gate"]["post_write"].get("unmatched_count") or 0),
            "prose_numbers": nums,
            "prose_unsupported": tot(lambda x: x["spot"]["counts"]["unsupported"]),
            "prose_uncited": tot(lambda x: x["spot"]["counts"]["uncited"]),
            "unsupported_rate": round(tot(lambda x: x["spot"]["counts"]["unsupported"]) / nums, 4) if nums else 0.0,
            "dates_unsupported": tot(lambda x: len(x["spot"]["dates"]["unsupported"])),
            "house_differs": tot(lambda x: len((x["spot"].get("house") or {}).get("differs") or [])),
            "guard_drops": tot(lambda x: x["measure"]["guard_drops_total"]),
            "sections_written": tot(lambda x: x["measure"]["sections_written"]),
            "sections_expected": tot(lambda x: x["measure"]["sections_expected"]),
            "words_avg": round(tot(lambda x: x["measure"]["words"]) / len(sc)),
            "numbers_per_100w": round(sum(x["measure"]["numbers_per_100w"] for x in sc) / len(sc), 2),
            "citations_per_100w": round(sum(x["measure"]["citations_per_100w"] for x in sc) / len(sc), 2),
            "vague_per_100w": round(sum(x["measure"]["vague_per_100w"] for x in sc) / len(sc), 2),
            "cost_usd": round(sum(float(x["cost"].get("cost_usd") or 0) for x in sc), 4),
            "sync_equivalent_usd_avg": round(sum(float(x["cost"].get("sync_equivalent_usd") or 0) for x in sc) / len(sc), 4),
            "batch_equivalent_usd_avg": round(sum(float(x["cost"].get("batch_equivalent_usd") or 0) for x in sc) / len(sc), 4),
            "output_tokens_avg": round(sum(float(x["cost"].get("output_tokens") or 0) for x in sc) / len(sc))}


def recommend(opus: dict, sonnet: dict) -> dict:
    """Accuracy parity is a rule; reading quality is the operator's call. Sonnet 'matches' only when every accuracy
    test is no worse than Opus within a small allowance."""
    if not opus or not sonnet or sonnet.get("reports", 0) < opus.get("reports", 0) or sonnet.get("reports", 0) == 0:
        return {"verdict": "INCOMPLETE", "matches_on_accuracy": False,
                "why": ["not every symbol produced a Sonnet report; no recommendation"]}
    tests = [
        ("no more P1 accuracy defects", sonnet["audit_p1"] <= opus["audit_p1"]),
        ("P2 accuracy defects within +1 of Opus", sonnet["audit_p2"] <= opus["audit_p2"] + 1),
        ("no more data-gate hard fails", sonnet["gate_hard_fail"] <= opus["gate_hard_fail"]),
        ("unsupported prose numbers within 1.25x of Opus (+1 pt)",
         sonnet["unsupported_rate"] <= opus["unsupported_rate"] * 1.25 + 0.01),
        ("no more unsupported dates (+1)", sonnet["dates_unsupported"] <= opus["dates_unsupported"] + 1),
        ("guard drops (ungrounded/behaviour sentences) within 1.5x of Opus (+2)",
         sonnet["guard_drops"] <= opus["guard_drops"] * 1.5 + 2),
        ("every section written", sonnet["sections_written"] == sonnet["sections_expected"]),
        ("key facts equal the house data now", sonnet["house_differs"] == 0),
    ]
    failed = [name for name, ok in tests if not ok]
    saving = None
    if opus.get("batch_equivalent_usd_avg") and sonnet.get("batch_equivalent_usd_avg") is not None:
        saving = round(1 - sonnet["batch_equivalent_usd_avg"] / opus["batch_equivalent_usd_avg"], 3)
    if failed:
        verdict = "KEEP_OPUS"
        why = [f"failed: {n}" for n in failed]
    else:
        verdict = "SONNET_MATCHES_ON_ACCURACY"
        why = ["every accuracy test is no worse than Opus; switching Watch reports is the operator's call after reading "
               "the PDF pairs"]
    return {"verdict": verdict, "matches_on_accuracy": not failed, "tests": [{"test": n, "pass": ok} for n, ok in tests],
            "why": why, "batch_cost_saving_pct": None if saving is None else round(100 * saving, 1)}


# ── outputs ───────────────────────────────────────────────────────────────────────────────────────────────────────
def scorecard_md(result: dict) -> str:
    o, s, rec = result["aggregate"].get("opus") or {}, result["aggregate"].get("sonnet") or {}, result["recommendation"]
    lines = ["# Watch prospectus model eval — Sonnet 5.5 vs Opus 5.5", "",
             f"Generated {result['generated_at']}. Symbols: {', '.join(r['symbol'] for r in result['rows'])}. "
             f"Paid spend this run: ${result['budget']['spent_usd']:.4f} of the ${result['budget']['cap_usd']:.2f} cap.", "",
             f"**Recommendation: {rec['verdict']}** — " + "; ".join(rec["why"]), "",
             "| measure | Opus 5.5 (stored) | Sonnet 5.5 (new) |", "|---|---|---|"]
    rows = [("accuracy defects P1 / P2 / P3", lambda a: f"{a.get('audit_p1')} / {a.get('audit_p2')} / {a.get('audit_p3')}"),
            ("data gate pass / hard fail", lambda a: f"{a.get('gate_pass')} / {a.get('gate_hard_fail')}"),
            ("prose numbers checked", lambda a: a.get("prose_numbers")),
            ("unsupported prose numbers (rate)", lambda a: f"{a.get('prose_unsupported')} ({100 * (a.get('unsupported_rate') or 0):.1f}%)"),
            ("numbers true but uncited", lambda a: a.get("prose_uncited")),
            ("dates not in the facts", lambda a: a.get("dates_unsupported")),
            ("key facts differing from the house now", lambda a: a.get("house_differs")),
            ("sentences dropped by the guard", lambda a: a.get("guard_drops")),
            ("sections written / expected", lambda a: f"{a.get('sections_written')} / {a.get('sections_expected')}"),
            ("words per report (avg)", lambda a: a.get("words_avg")),
            ("numbers / citations / vague words per 100 words", lambda a: f"{a.get('numbers_per_100w')} / {a.get('citations_per_100w')} / {a.get('vague_per_100w')}"),
            ("output tokens (avg)", lambda a: a.get("output_tokens_avg")),
            ("cost per report, as run (avg)", lambda a: f"${(a.get('cost_usd') or 0) / max(1, a.get('reports') or 1):.4f}"),
            ("cost per report on the Batch price (avg)", lambda a: f"${a.get('batch_equivalent_usd_avg') or 0:.4f}")]
    for name, fn in rows:
        lines.append(f"| {name} | {fn(o) if o else '—'} | {fn(s) if s else '—'} |")
    if rec.get("batch_cost_saving_pct") is not None:
        lines += ["", f"Sonnet costs {rec['batch_cost_saving_pct']}% less per report on the like-for-like Batch price."]
    lines += ["", "## Accuracy tests", ""] + [f"- {'PASS' if t['pass'] else 'FAIL'} — {t['test']}" for t in rec.get("tests") or []]
    lines += ["", "## Per symbol", ""]
    for r in result["rows"]:
        lines.append(f"### {r['symbol']} ({r.get('category') or 'n/a'})")
        if r.get("error"):
            lines.append(f"- Sonnet: not written — {r['error']}")
        for side in ("opus", "sonnet"):
            x = r.get(side)
            if not x:
                continue
            lines.append(f"- {side}: gate {x['gate']['status']}, audit {x['audit']['counts']}, unsupported numbers "
                         f"{x['spot']['counts']['unsupported']}/{x['spot']['numbers']}, guard drops "
                         f"{x['measure']['guard_drops_total']}, {x['measure']['words']} words, "
                         f"${float(x['cost'].get('cost_usd') or 0):.4f} ({x['cost']['mode']}, {x['cost'].get('output_tokens')} out)")
        lines.append("")
    lines += ["## Method and caveats", ""] + [f"- {c}" for c in result["caveats"]]
    return "\n".join(lines) + "\n"


def _e(v: Any) -> str:
    return _html.escape(str(v if v is not None else "—"))


def comparison_html(result: dict, docs: dict[str, dict]) -> str:
    """One self-contained page: the scorecard, then per symbol the two verdict lines and sections side by side
    (stacked on a phone), with links to the PDF pairs."""
    o, s, rec = result["aggregate"].get("opus") or {}, result["aggregate"].get("sonnet") or {}, result["recommendation"]
    head = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prospectus Model Eval</title><style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#66645e;--card:#fff;--line:#e2e0da;--good:#1f7a4d;--bad:#b3261e;--accent:#2f5d8a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--fg:#ecebe7;--muted:#a4a29b;--card:#1f1f1d;--line:#34332f;--good:#5cc28d;--bad:#ef7b72;--accent:#8ab4e0}}
:root[data-theme="dark"]{--bg:#151514;--fg:#ecebe7;--muted:#a4a29b;--card:#1f1f1d;--line:#34332f;--good:#5cc28d;--bad:#ef7b72;--accent:#8ab4e0}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px}h1{font-size:22px;margin:4px 0 8px}h2{font-size:18px;margin:28px 0 8px}
h3{font-size:15px;margin:14px 0 6px}.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:7px 6px;text-align:left;vertical-align:top}
th{font-weight:600}.wrap{overflow-x:auto}.pass{color:var(--good);font-weight:600}.fail{color:var(--bad);font-weight:600}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pair>div{min-width:0}.sec{font-size:14px}.sec p{margin:4px 0}
a{color:var(--accent)}.btn{display:inline-block;min-height:44px;line-height:44px;padding:0 14px;border:1px solid var(--line);border-radius:8px;margin:4px 6px 4px 0;text-decoration:none}
@media (max-width:760px){.pair{grid-template-columns:1fr}}
</style></head><body><main>"""
    parts = [head, f"<h1>Watch prospectus: Sonnet 5.5 vs Opus 5.5</h1><p class='muted'>{_e(result['generated_at'])} · "
             f"{len(result['rows'])} symbols · paid this run ${result['budget']['spent_usd']:.4f} of "
             f"${result['budget']['cap_usd']:.2f}</p>",
             f"<div class='card'><b>{_e(rec['verdict'])}</b><br>{_e('; '.join(rec['why']))}</div>",
             "<h2>Scorecard</h2><div class='wrap'><table><tr><th>Measure</th><th>Opus 5.5</th><th>Sonnet 5.5</th></tr>"]
    for k, label in (("audit_p1", "Accuracy defects P1"), ("audit_p2", "Accuracy defects P2"), ("audit_p3", "Accuracy defects P3"),
                     ("gate_pass", "Data gate pass"), ("gate_hard_fail", "Data gate hard fail"),
                     ("prose_unsupported", "Unsupported prose numbers"), ("unsupported_rate", "Unsupported rate"),
                     ("prose_uncited", "True but uncited numbers"), ("dates_unsupported", "Dates not in the facts"),
                     ("house_differs", "Key facts ≠ house now"), ("guard_drops", "Sentences dropped by the guard"),
                     ("sections_written", "Sections written"), ("words_avg", "Words per report"),
                     ("numbers_per_100w", "Numbers / 100 words"), ("citations_per_100w", "Citations / 100 words"),
                     ("vague_per_100w", "Vague words / 100 words"), ("output_tokens_avg", "Output tokens"),
                     ("batch_equivalent_usd_avg", "Cost per report, Batch price ($)")):
        parts.append(f"<tr><td>{_e(label)}</td><td>{_e(o.get(k))}</td><td>{_e(s.get(k))}</td></tr>")
    parts.append("</table></div><h2>Accuracy tests</h2><div class='card'>")
    for t in rec.get("tests") or []:
        parts.append(f"<div><span class='{'pass' if t['pass'] else 'fail'}'>{'PASS' if t['pass'] else 'FAIL'}</span> {_e(t['test'])}</div>")
    parts.append("</div>")
    for r in result["rows"]:
        sym = r["symbol"]
        parts.append(f"<h2>{_e(sym)} <span class='muted'>· {_e(r.get('category'))}</span></h2>")
        links = [f"<a class='btn' href='{_e(p)}'>{_e(n)}</a>" for n, p in (r.get("files") or {}).items()]
        if links:
            parts.append("<div>" + "".join(links) + "</div>")
        if r.get("error"):
            parts.append(f"<div class='card fail'>Sonnet not written: {_e(r['error'])}</div>")
        od, sd = docs.get(f"opus:{sym}") or {}, docs.get(f"sonnet:{sym}") or {}
        parts.append("<div class='pair'>")
        for side, d, sc in (("Opus 5.5", od, r.get("opus")), ("Sonnet 5.5", sd, r.get("sonnet"))):
            parts.append(f"<div class='card'><h3>{_e(side)}</h3>")
            if sc:
                parts.append(f"<div class='muted'>gate {_e(sc['gate']['status'])} · audit {_e(sc['audit']['counts'])} · "
                             f"unsupported {sc['spot']['counts']['unsupported']}/{sc['spot']['numbers']} · "
                             f"{sc['measure']['words']} words · ${float(sc['cost'].get('cost_usd') or 0):.4f} "
                             f"({_e(sc['cost']['mode'])})</div>")
            parts.append(f"<p><b>{_e(d.get('verdict_line'))}</b></p>")
            for sec in d.get("sections") or []:
                body = _plain(sec.get("body_md") or "")
                paras = "".join(f"<p>{_e(p.strip())}</p>" for p in body.split("\n") if p.strip())
                parts.append(f"<div class='sec'><h3>{_e(sec.get('title'))}</h3>{paras}</div>")
            parts.append("</div>")
        parts.append("</div>")
    parts.append("<h2>Method and caveats</h2><div class='card'><ul>" + "".join(f"<li>{_e(c)}</li>" for c in result["caveats"])
                 + "</ul></div></main></body></html>")
    return "".join(parts)


CAVEATS = [
    "Sonnet reports were written now from a fresh production assembly of the same house stores; the stored Opus "
    "reports were written earlier, so a key-fact difference on the Opus side can be time, not error.",
    "Sonnet ran synchronously (tier mid, effort medium, 5,000 output tokens); Opus Watch reports written by the "
    "Batch API were billed at 50%. Cost is shown as run and on the like-for-like Batch price.",
    "Opus reports written before 2026-10-27 used the earlier Watch settings (effort high, 16,000 output tokens); "
    "their length is not comparable and is flagged per symbol.",
    "Accuracy uses the production data-quality gate, the standing accuracy auditor (deterministic, no paid prose "
    "review) and a deterministic prose spot check; reading quality is the operator's judgment from the PDF pairs.",
]


def write_outputs(out: Path, result: dict, docs: dict[str, dict]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    paths = {"comparison.json": out / "comparison.json", "SCORECARD.md": out / "SCORECARD.md",
             "comparison.html": out / "comparison.html"}
    paths["comparison.json"].write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    paths["SCORECARD.md"].write_text(scorecard_md(result), encoding="utf-8")
    paths["comparison.html"].write_text(comparison_html(result, docs), encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Deps:
    """Everything that touches a store, a model or a renderer; tests replace these with stubs."""
    sources: Any
    primary: Any
    generate_fn: Callable
    ai_fn: Optional[Callable]
    render_fn: Callable[[dict], dict]
    assemble_fn: Callable
    state_root: Path


def baseline(base: Path, sym: str, version: str | None) -> dict | None:
    doc = store.read_prospectus(base, sym, version)
    if doc is None or doc.get("scope") != "watch" or str(doc.get("model") or "") != BASELINE_MODEL:
        return None
    return doc


def candidates(base: Path, *, hours: float, now: datetime, holdings: set[str]) -> list[dict]:
    """Watch-scope READY reports written by Opus in the last ``hours`` (never a holding), newest first."""
    items = store.read_index(base).get("items") or {}
    out = []
    for sym, e in items.items():
        try:
            gen_at = datetime.fromisoformat(str(e.get("generated_at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if (e.get("scope") != "watch" or e.get("status") != "ready" or e.get("model") != BASELINE_MODEL
                or sym in holdings or now - gen_at > timedelta(hours=hours)):
            continue
        doc = store.read_prospectus(base, sym, e.get("version")) or {}
        facts = {f["label"]: f for f in doc.get("facts") or []}
        sector = (facts.get("Sector") or {}).get("text") or ((doc.get("blocks") or {}).get("fund_profile") or {}).get("category")
        out.append({"symbol": sym, "version": e.get("version"), "generated_at": e.get("generated_at"),
                    "mode": "batch" if doc.get("batch") else "sync", "gate_status": e.get("gate_status"),
                    "output_tokens": (doc.get("usage") or {}).get("output_tokens"), "name": doc.get("name"),
                    "sector": sector, "industry": (facts.get("Industry") or {}).get("text")})
    return sorted(out, key=lambda r: r["generated_at"], reverse=True)


def run(selection: list[dict], *, deps: Deps, cfg: dict, out: Path, apply: bool, budget: Budget,
        settings: dict, now_fn: Callable[[], datetime], log: Callable[[str], None] = print,
        preflight_fn: Callable[[int, float], dict] | None = None, pricing: dict | None = None) -> dict:
    """Write (``apply``) and score each selected symbol. A dry run assembles, gates and sizes only."""
    from scripts.lib.prospectus import generate as gen
    from scripts.lib.prospectus import quality_gate as qg
    base = store.base_dir(deps.state_root, cfg)
    gen_cfg = gen.generation_config()
    rows, docs = [], {}
    sym_ref: dict = {}
    plan = []
    for item in selection:
        sym = store.norm_symbol(item["symbol"])
        opus = baseline(base, sym, item.get("version"))
        b = deps.assemble_fn(deps.sources, sym, "watch", cfg=cfg, holding=None, now=now_fn(), request_refresh=False)
        prompt = gen.writer_prompt(b, cfg, mode="full", previous=None, gen=gen_cfg)
        det = qg.pre_write(qg.packet_from_bundle(b, now=now_fn()), settings=settings, ai_fn=None)
        plan.append({"symbol": sym, "category": item.get("category"), "opus_version": (opus or {}).get("version"),
                     "prompt_bytes": len(prompt.encode("utf-8")), "facts": len(b.facts), "gate_layer1": det["status"],
                     "gate_reasons": det["reasons"][:6], "bundle": b, "opus": opus})
    if pricing is None:
        from scripts.lib.anthropic_transport import load_policy
        pricing = load_policy().get("pricing") or {}
    est = max((estimate_symbol_usd(p["prompt_bytes"], pricing=pricing, cfg=cfg, gen=gen_cfg, ai_reads=3)
               for p in plan), default=0.0)
    pf = preflight_fn(len(plan), est) if preflight_fn else {"ok": True, "symbols_that_fit": len(plan), "skipped": "no preflight"}
    summary = {"schema": SCHEMA, "mode": "apply" if apply else "dry_run", "preflight": pf,
               "plan": [{k: v for k, v in p.items() if k not in ("bundle", "opus")} for p in plan]}
    if not apply:
        return summary
    if not pf.get("ok"):
        summary["stopped_reason"] = f"preflight: no headroom (lowest {pf.get('lowest')})"
        return summary
    allowed = int(pf.get("symbols_that_fit") or 0)
    stopped = None
    for i, p in enumerate(plan):
        sym, b = p["symbol"], p["bundle"]
        sym_ref["symbol"] = sym
        row = {"symbol": sym, "category": p["category"], "opus_version": p["opus_version"]}
        if p["opus"] is None:
            row["error"] = "no stored Opus Watch report at that version"
            rows.append(row)
            continue
        if stopped or i >= allowed:
            row["error"] = stopped or "not run: preflight sized the run below this symbol"
            rows.append(row)
            continue
        searches = {"left": SEARCHES_PER_SYMBOL}

        def allowance(take: bool, _s: dict = searches) -> int:
            if take:
                _s["left"] -= 1
            return max(0, _s["left"])
        version = store.stamp(now_fn())
        try:
            doc = gen.write(b, processes={"standard": WRITER_PROCESS, "premium": WRITER_PROCESS}, premium=False,
                            mode="full", previous=None, cfg=cfg, generate_fn=deps.generate_fn, manual=False,
                            now=now_fn(), version=version, search_fn=getattr(deps.sources, "search", None),
                            allowance_fn=allowance, ai_fn=deps.ai_fn)
        except gen.QueueLater as exc:
            stopped = f"stopped cleanly: {str(exc)[:200]}"
            row["error"] = stopped
            rows.append(row)
            log(f"STOP {sym}: {stopped}")
            continue
        except qg.DataBlocked as exc:
            row["error"] = f"data gate HARD_FAIL (no model call): {str(exc)[:200]}"
            rows.append(row)
            continue
        except gen.GenerationFailed as exc:
            row["error"] = f"generation failed: {str(exc)[:200]}"
            rows.append(row)
            continue
        if str(doc.get("model") or "") != EVAL_MODEL:
            row["error"] = f"returned model {doc.get('model')} is not {EVAL_MODEL}; not scored"
            rows.append(row)
            stopped = row["error"]
            continue
        sdir = out / "sonnet" / sym / version
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "prospectus.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
        try:
            files = deps.render_fn(doc)
        except Exception as exc:  # noqa: BLE001 - a render failure is recorded; the scores still stand
            files = {}
            row["render_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        for name, data in files.items():
            target = sdir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (sdir / "house_facts.json").write_text(json.dumps(b.facts, default=str), encoding="utf-8")
        log(f"WROTE {sym} {version} model={doc['model']} cost=${float(doc.get('cost_usd') or 0):.4f}")
        rows.append(row)
    summary["write"] = {"rows": rows, "stopped_reason": stopped, "budget": budget_dict(budget)}
    return summary


def budget_dict(budget: Budget) -> dict:
    return {"cap_usd": budget.cap_usd, "spent_usd": round(budget.spent_usd, 6), "calls": budget.calls}


def score(selection: list[dict], *, deps: Deps, cfg: dict, out: Path, settings: dict, budget: Budget,
          write_rows: list[dict] | None = None, now: datetime | None = None) -> dict:
    """Score the saved Sonnet reports under ``out/sonnet`` against the stored Opus versions; write the outputs."""
    base = store.base_dir(deps.state_root, cfg)
    errors = {r["symbol"]: r for r in write_rows or []}
    rows, docs = [], {}
    for item in selection:
        sym = store.norm_symbol(item["symbol"])
        row = {"symbol": sym, "category": item.get("category"), "files": {}}
        if errors.get(sym, {}).get("error"):
            row["error"] = errors[sym]["error"]
        opus = baseline(base, sym, item.get("version"))
        sdirs = sorted((out / "sonnet" / sym).glob("*/prospectus.json")) if (out / "sonnet" / sym).is_dir() else []
        sonnet = json.loads(sdirs[-1].read_text(encoding="utf-8")) if sdirs else None
        house = json.loads((sdirs[-1].parent / "house_facts.json").read_text(encoding="utf-8")) \
            if sdirs and (sdirs[-1].parent / "house_facts.json").is_file() else None
        if opus is not None:
            row["opus"] = score_doc(opus, settings=settings, primary=deps.primary, house_facts=house, ai_fn=deps.ai_fn, now=now)
            row["opus"]["settings"] = "watch batch (effort medium, 5k)" if opus.get("batch") else "sync (pre-2026-10-27 Watch settings)"
            docs[f"opus:{sym}"] = opus
            pdf = store.file_path(base, sym, "pdf", opus.get("version"))
            if pdf is not None:
                (out / "pdf").mkdir(parents=True, exist_ok=True)
                shutil.copy2(pdf, out / "pdf" / f"{sym}_opus.pdf")
                row["files"]["Opus PDF"] = f"pdf/{sym}_opus.pdf"
        if sonnet is not None:
            row["sonnet"] = score_doc(sonnet, settings=settings, primary=deps.primary, house_facts=house, ai_fn=deps.ai_fn, now=now)
            docs[f"sonnet:{sym}"] = sonnet
            spdf = sdirs[-1].parent / "prospectus.pdf"
            if spdf.is_file():
                (out / "pdf").mkdir(parents=True, exist_ok=True)
                shutil.copy2(spdf, out / "pdf" / f"{sym}_sonnet.pdf")
                row["files"]["Sonnet PDF"] = f"pdf/{sym}_sonnet.pdf"
            if (sdirs[-1].parent / "prospectus.html").is_file():
                row["files"]["Sonnet HTML"] = os.path.relpath(sdirs[-1].parent / "prospectus.html", out)
        rows.append(row)
    agg = {"opus": aggregate(rows, "opus"), "sonnet": aggregate(rows, "sonnet")}
    result = {"schema": SCHEMA, "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
              "eval_route": {"process": WRITER_PROCESS, "tier": EVAL_TIER, "model": EVAL_MODEL, "effort": EVAL_EFFORT,
                             "per_call_cap_usd": EVAL_PER_CALL_CAP_USD, "baseline_model": BASELINE_MODEL},
              "budget": budget_dict(budget), "aggregate": agg, "recommendation": recommend(agg["opus"], agg["sonnet"]),
              "rows": rows, "caveats": CAVEATS}
    result["outputs"] = write_outputs(out, result, docs)
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Sonnet 5.5 vs Opus 5.5 on Watch prospectuses (dry run by default).",
                                 allow_abbrev=False)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates", help="READY Opus Watch reports from the last --hours (free)")
    c.add_argument("--hours", type=float, default=48.0)
    for name in ("run", "score"):
        p = sub.add_parser(name)
        p.add_argument("--symbols", default="", help="SYM[:category[:opus_version]],... (comma-separated)")
        p.add_argument("--selection", default="", help="JSON file: [{symbol, category, version}] (private)")
        p.add_argument("--out", required=True, help="private output directory (never the prospectus store)")
        p.add_argument("--ai-gate", action="store_true", help="run the gate's layer-2 Haiku read (paid, ~$0.003 each)")
        p.add_argument("--cap-usd", type=float, default=DEFAULT_CAP_USD)
    sub.choices["run"].add_argument("--apply", action="store_true", help="paid: write the Sonnet reports, then score")
    sub.choices["run"].add_argument("--no-web", action="store_true", help="skip the web planning turn and searches")
    return ap.parse_args(argv)


def load_selection(args: argparse.Namespace) -> list[dict]:
    if args.selection:
        return json.loads(Path(args.selection).read_text(encoding="utf-8"))
    out = []
    for part in [x for x in args.symbols.split(",") if x.strip()]:
        bits = part.strip().split(":")
        out.append({"symbol": bits[0], "category": bits[1] if len(bits) > 1 else None,
                    "version": bits[2] if len(bits) > 2 else None})
    return out


def _guard_out(out: Path, state_root: Path, cfg: dict) -> None:
    base = store.base_dir(state_root, cfg).resolve()
    o = out.resolve()
    if o == base or base in o.parents:
        raise SystemExit(f"refused: --out {o} is inside the prospectus store {base}")


def production_deps(state_root: Path, *, budget: Budget, ai_gate: bool, web: bool) -> Deps:  # pragma: no cover - live
    from scripts.lib.prospectus import accuracy_audit as aa
    from scripts.lib.prospectus import generate as gen
    from scripts.lib.prospectus import quality_gate as qg
    from scripts.lib.prospectus import render
    from scripts.lib.prospectus.domains import full_assemble
    from scripts.lib.prospectus.inputs import HouseSources
    from scripts.prospectus_accuracy_audit import _db_query
    sources = HouseSources(state_root, read_only=False)  # production writer inputs (thesis fields included)
    if not web:
        sources.search = None  # type: ignore[assignment]
    sym_ref: dict = {}
    policy = overlay_policy(__import__("scripts.lib.anthropic_transport", fromlist=["load_policy"]).load_policy())
    worst = float(policy["per_call_caps_usd"][EVAL_TIER])
    worst_ai = float(policy["per_call_caps_usd"]["bulk"])
    deps = Deps(sources=sources, primary=aa.db_primary(_db_query(), state_root),
                generate_fn=budget_writer(gen.governed_generate, budget, worst_usd=worst, symbol_ref=sym_ref),
                ai_fn=budget_ai(qg.governed_ai_call, budget, worst_usd=worst_ai, symbol_ref=sym_ref, what="gate_layer2")
                if ai_gate else None,
                render_fn=render.render_all, assemble_fn=full_assemble, state_root=state_root)
    deps.sym_ref = sym_ref  # type: ignore[attr-defined]
    return deps


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wiring; the pieces are tested
    args = parse(argv)
    cfg = load_config()
    from scripts.lib.anthropic_routing import state_root as resolve
    state_root = Path(resolve())
    base = store.base_dir(state_root, cfg)
    now = datetime.now(timezone.utc)
    if args.cmd == "candidates":
        from scripts.lib.prospectus.inputs import HouseSources
        held = set((HouseSources(state_root, read_only=True).holdings() or {}).keys())
        print(json.dumps(candidates(base, hours=args.hours, now=now, holdings=held), indent=1, default=str))
        return 0
    out = Path(args.out).expanduser()
    _guard_out(out, state_root, cfg)
    selection = load_selection(args)
    from scripts.lib.prospectus.inputs import HouseSources
    held = set((HouseSources(state_root, read_only=True).holdings() or {}).keys())
    bad = [s["symbol"] for s in selection if store.norm_symbol(s["symbol"]) in held]
    if bad:
        raise SystemExit(f"refused: holdings are not in this test: {bad}")
    budget = Budget(cap_usd=float(args.cap_usd))
    from scripts.lib.prospectus import quality_gate as qg
    settings = qg.load_settings()
    deps = production_deps(state_root, budget=budget, ai_gate=args.ai_gate, web=not getattr(args, "no_web", False))
    if args.cmd == "score":
        with eval_route():
            res = score(selection, deps=deps, cfg=cfg, out=out, settings=settings, budget=budget, now=now)
        print(json.dumps({"recommendation": res["recommendation"], "aggregate": res["aggregate"],
                          "outputs": res["outputs"], "spent_usd": budget.spent_usd}, indent=1, default=str))
        return 0
    from scripts.lib import llm_consumption as lc
    from scripts.lib.anthropic_transport import load_policy
    from scripts.lib import search_budget as sb

    def pf(n: int, est: float) -> dict:
        return preflight(state_root=state_root, n_symbols=n, cap_usd=budget.cap_usd, est_per_symbol_usd=est,
                         policy=overlay_policy(load_policy()), lc=lc, search_status=lambda: sb.status("brave"))
    out.mkdir(parents=True, exist_ok=True)
    with eval_route() as route:
        summary = run(selection, deps=deps, cfg=cfg, out=out, apply=args.apply, budget=budget, settings=settings,
                      now_fn=lambda: datetime.now(timezone.utc), preflight_fn=pf,
                      pricing=load_policy().get("pricing") or {})
        summary["eval_route"] = route
        (out / ("run_apply.json" if args.apply else "run_dry.json")).write_text(
            json.dumps(summary, indent=1, default=str), encoding="utf-8")
        if args.apply:
            res = score(selection, deps=deps, cfg=cfg, out=out, settings=settings, budget=budget,
                        write_rows=(summary.get("write") or {}).get("rows"), now=datetime.now(timezone.utc))
            summary["recommendation"] = res["recommendation"]
            summary["outputs"] = res["outputs"]
            summary["spent_usd"] = budget.spent_usd
    print(json.dumps({k: v for k, v in summary.items() if k != "plan"} | {"plan": summary.get("plan")},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
