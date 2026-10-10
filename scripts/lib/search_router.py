"""search_router.py — the search source routing engine (SearchRoutingEngine@v1). One chokepoint above brave_router.

Operator, 2026-10-10: "we need to make sure that we have a mature engine and rules about which source to use
for what so we're conserving the spend", with scalps "about to fire" first.

Every routed question names its CALLER; ``config/search_routing_policy.json`` maps the caller to a QUESTION
CLASS, and the class says what to ask, in order:

    tier 0  shared cache            TTL per class (20 min scalp ... 6 h research); hits cost nothing
    tier 1  FREE lane               internal catalyst_record news (broker projection), SearXNG with an explicit
                                    engine list that never names a Brave engine, the Alpha Vantage owner's news
                                    store (read-only; skipped until the registry grants the scope)
    tier 2  PAID Brave              only when the class allows it AND the free answer fails the measurable
                                    quality rule (scripts/lib/search_quality.py); the dollar decision
                                    (scripts/lib/search_spend.py: pools, shares, daily pacing, $12/$15/$18
                                    lines) runs inside the ledger lock via brave_router -> try_consume(gate=)
    tier 3  declared no_coverage    say_so / declared_gap — never a value from the wrong place

A caller whose symbol the scalp-priority classifier (scripts/lib/scalp_priority.py) marks about-to-fire is
promoted to class ``scalp_priority`` (pool ``scalp``: first claim on the paid budget); a name researched in the
last 30 minutes is not re-promoted.

Flags: ``SEARCH_ROUTING_ENGINE=1`` (or ``enabled=True``) turns the engine on for a call; the paid tier also needs
brave_router's own ``BRAVE_ROUTER_LIVE`` arm (or an injected test transport). ``SEARCH_ROUTING_DRY_RUN=1`` (or
``dry_run=True``) plans every decision and calls nothing — no network, no ledger write, no receipt, no cache
write; a dry run can never spend a Brave request.

Every live routed question appends one SearchRoutingReceipt@v1 line (class, tier, source, reason, cost,
cache hit, latency) through ``search_budget.append_routing_receipt``.

AUTHORITY: READ_ONLY_ADVISORY. Data only: nothing here sizes, orders, stops or touches a broker. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time as _time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

SCHEMA = "SearchRoutingEngine@v1"
RESPONSE_SCHEMA = "RoutedSearchResponse@v1"
CACHE_SCHEMA = "SearchRoutingCache@v1"
FLAG_ENGINE = "SEARCH_ROUTING_ENGINE"
FLAG_DRY_RUN = "SEARCH_ROUTING_DRY_RUN"
_TRUE = {"1", "true", "yes", "on"}

Clock = Callable[[], datetime]


def _lib(name: str):
    import importlib

    try:
        return importlib.import_module(f"scripts.lib.{name}")
    except ImportError:  # pragma: no cover - dual-import shape
        return importlib.import_module(f"lib.{name}")


def engine_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FLAG_ENGINE, "")).strip().lower() in _TRUE


def dry_run_forced(env: Optional[Mapping[str, str]] = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FLAG_DRY_RUN, "")).strip().lower() in _TRUE


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _state_root(root: Optional[Path]) -> Path:
    if root is not None:
        return Path(root)
    return _lib("search_budget")._state_root()


# ── request / response ──────────────────────────────────────────────────────


@dataclass
class SearchRequest:
    query: str
    caller: str
    symbol: Optional[str] = None
    kind: Optional[str] = None                      # web | news; None = the class's kind
    count: int = 5
    #: Scalp rows the calling lane already holds (symbol, decision, score, rvol, gap_pct, change_pct).
    candidates: list[dict[str, Any]] = field(default_factory=list)
    idempotency_key: Optional[str] = None
    #: "scalp_priority" from a lane that already ranks its own about-to-fire list (Agent Q's hot tier). The
    #: engine still enforces the session and 30-minute recency rules before granting first claim on budget.
    priority_hint: Optional[str] = None
    #: Shared cache identity independent of query wording: (subject, intent). L708 and L379 both ask
    #: intent "premarket catalyst" and must share one entry.
    cache_identity: Optional[tuple[str, str]] = None
    #: Caller's TTL; the engine uses min(this, class TTL).
    cache_ttl_s: Optional[int] = None


@dataclass
class RoutedResponse:
    """Duck-compatible with brave_router.RouterResponse on ok/reason/results/provider/cache_hit/reservation_id."""

    schema: str = RESPONSE_SCHEMA
    ok: bool = False
    reason: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    cache_hit: bool = False
    reservation_id: Optional[str] = None
    receipt: Optional[dict[str, Any]] = None
    question_class: str = ""
    pool: str = ""
    tier: Optional[int] = None
    cost_usd: float = 0.0
    sufficient: bool = False
    no_coverage: Optional[str] = None
    dry_run: bool = False
    plan: list[dict[str, Any]] = field(default_factory=list)
    priority: Optional[dict[str, Any]] = None


# ── shared cache (tier 0) ───────────────────────────────────────────────────


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    with open(lock, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            except Exception:  # noqa: BLE001
                pass


def cache_key(kind: str, query: str, symbol: Optional[str]) -> str:
    norm = " ".join(str(query or "").lower().split())
    return hashlib.sha256(f"{kind}|{norm}|{str(symbol or '').upper()}".encode("utf-8")).hexdigest()


def cache_path(policy: Mapping[str, Any], root: Optional[Path]) -> Path:
    rel = ((policy.get("cache") or {}).get("path")) or "data/runtime/search_routing_cache.json"
    return _state_root(root) / rel


def cache_get(path: Path, key: str, *, ttl_s: int, now: datetime) -> Optional[dict[str, Any]]:
    """Fail CLOSED as a miss: an unreadable cache is never an answer (AGENTS.md "Caches ... fail closed")."""
    if ttl_s <= 0:
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        entry = (doc.get("entries") or {}).get(key)
        if not entry:
            return None
        ts = datetime.fromisoformat(str(entry["ts"]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (now - ts).total_seconds()
        if age < 0 or age > ttl_s:
            return None
        return entry
    except Exception:  # noqa: BLE001
        return None


def cache_put(path: Path, key: str, entry: dict[str, Any], *, now: datetime, max_entries: int, max_age_s: int) -> bool:
    """Only answers are cached (never an error string in the slot an answer occupies)."""
    if not entry.get("results"):
        return False
    try:
        with _exclusive(path):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    raise ValueError("not an object")
            except FileNotFoundError:
                doc = {"schema": CACHE_SCHEMA, "entries": {}}
            except Exception:  # noqa: BLE001 — a corrupt cache is set aside (archived, not deleted), not rebuilt over
                try:
                    path.replace(path.with_suffix(path.suffix + f".corrupt.{now.strftime('%Y%m%dT%H%M%S')}"))
                except Exception:  # noqa: BLE001
                    return False
                doc = {"schema": CACHE_SCHEMA, "entries": {}}
            entries = doc.setdefault("entries", {})
            entries[key] = {**entry, "ts": _iso(now)}
            keep = {}
            for k, v in entries.items():
                try:
                    ts = datetime.fromisoformat(str(v.get("ts")))
                    if (now - ts).total_seconds() <= max_age_s:
                        keep[k] = v
                except Exception:  # noqa: BLE001
                    continue
            if len(keep) > max_entries:
                keep = dict(sorted(keep.items(), key=lambda kv: str(kv[1].get("ts")))[-max_entries:])
            doc["entries"] = keep
            doc["schema"] = CACHE_SCHEMA
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(path)
        return True
    except Exception:  # noqa: BLE001
        return False


# ── tier-1 adapters ─────────────────────────────────────────────────────────


@dataclass
class TierResult:
    source: str
    ok: bool
    reason: str
    results: list[dict[str, Any]] = field(default_factory=list)
    units_free: int = 0


def _canon(url: str) -> str:
    return str(url or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def _merge(*lists: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out, seen = [], set()
    for lst in lists:
        for r in lst or []:
            u = _canon(str(r.get("url") or ""))
            if not u.startswith("http") or u in seen:
                continue
            seen.add(u)
            out.append(r)
    return out[: max(limit, 1) * 3]


def _adapter_searxng(ctx: "_Ctx", kind: str) -> TierResult:
    fs = _lib("free_search")
    sx = ((ctx.policy.get("free_lane") or {}).get("searxng") or {})
    engines = sx.get("engines") or {}
    resp = fs.search(ctx.req.query, caller=f"route.{ctx.cls_name}", kind=kind, count=ctx.req.count,
                     root=ctx.root, transport=ctx.free_transport, engines=engines)
    rows = []
    for r in list(getattr(resp, "results", None) or []):
        rows.append({**r, "provider": "searxng"})
    return TierResult("searxng", bool(getattr(resp, "ok", False)), str(getattr(resp, "reason", "")), rows,
                      int(getattr(resp, "units", 0) or 0))


def _adapter_internal_news(ctx: "_Ctx", kind: str) -> TierResult:
    if not ctx.req.symbol:
        return TierResult("internal_news", False, "NO_SYMBOL")
    import sys

    scripts_dir = str(Path(__file__).resolve().parents[1])
    if scripts_dir not in sys.path:   # the data broker package imports itself as ``lib.data_broker``
        sys.path.append(scripts_dir)
    import importlib

    cr = importlib.import_module("lib.data_broker.catalyst_record")
    db = ctx.db_query or getattr(cr, "_db_query")
    hours = ((ctx.cls.get("quality") or {}).get("freshness_hours")) or 72
    days = max(1, int((float(hours) + 23) // 24))
    rows = cr.get_symbol_news(db, ctx.req.symbol, days=days, limit=max(ctx.req.count, 3)) or []
    out = [{"title": r.get("title") or "", "url": r.get("url") or "", "description": f"{r.get('source') or ''}".strip(),
            "published_at": r.get("published_at"), "source": r.get("source"), "provider": "internal_news",
            "tagged_symbol": str(ctx.req.symbol).upper()}
           for r in rows if r.get("url")]
    return TierResult("internal_news", bool(out), "OK" if out else "ZERO_RESULTS", out)


def _av_granted(policy: Mapping[str, Any], registry: Optional[dict[str, Any]]) -> bool:
    spec = (policy.get("sources") or {}).get("alpha_vantage_news") or {}
    reg = registry
    if reg is None:
        try:
            reg = _lib("data_source_authority").registry()
        except Exception:  # noqa: BLE001
            return False
    supplies = set(((reg.get("providers") or {}).get("alpha_vantage") or {}).get("supplies") or [])
    return bool(supplies & set(spec.get("requires_supplies_any") or []))


def _adapter_alpha_vantage_news(ctx: "_Ctx", kind: str) -> TierResult:
    """Read the AV owner's NewsSentimentIndex@v1 store. Never sends an Alpha Vantage request."""
    if not ctx.req.symbol:
        return TierResult("alpha_vantage_news", False, "NO_SYMBOL")
    if not _av_granted(ctx.policy, ctx.registry):
        return TierResult("alpha_vantage_news", False, "NOT_GRANTED")
    spec = (ctx.policy.get("sources") or {}).get("alpha_vantage_news") or {}
    path = _state_root(ctx.root) / str(spec.get("store") or "")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return TierResult("alpha_vantage_news", False, "NO_STORE")
    except Exception as exc:  # noqa: BLE001
        return TierResult("alpha_vantage_news", False, f"STORE_UNREADABLE:{type(exc).__name__}")
    sym = str(ctx.req.symbol).upper()
    arts = list(((doc.get("by_ticker") or {}).get(sym)) or [])
    if not arts:
        for a in doc.get("articles") or []:
            tickers = {str(t.get("ticker") or "").upper() for t in a.get("ticker_sentiment") or [] if isinstance(t, dict)}
            if sym in tickers:
                arts.append(a)
    out = [{"title": a.get("title") or "", "url": a.get("url") or "", "description": str(a.get("summary") or "")[:500],
            "published_at": a.get("time_published"), "source": a.get("source"), "provider": "alpha_vantage_news",
            "tagged_symbol": sym}
           for a in arts if a.get("url")][: max(ctx.req.count, 3)]
    return TierResult("alpha_vantage_news", bool(out), "OK" if out else "ZERO_RESULTS", out)


ADAPTERS: dict[str, Callable[["_Ctx", str], TierResult]] = {
    "searxng": _adapter_searxng,
    "internal_news": _adapter_internal_news,
    "alpha_vantage_news": _adapter_alpha_vantage_news,
}


@dataclass
class _Ctx:
    req: SearchRequest
    policy: dict[str, Any]
    cls_name: str
    cls: dict[str, Any]
    root: Optional[Path]
    free_transport: Any
    db_query: Any
    registry: Optional[dict[str, Any]]


# ── classification ──────────────────────────────────────────────────────────


def resolve_class(policy: Mapping[str, Any], req: SearchRequest, *, now: datetime, root: Optional[Path],
                  scalp_rows: Optional[tuple[list[dict[str, Any]], Optional[datetime]]] = None
                  ) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    """(class name | None, priority decision dict | None). None class = UNKNOWN_CALLER."""
    base = (policy.get("callers") or {}).get(str(req.caller or ""))
    if base is None:
        return None, None
    promotable = str(req.caller) in set(policy.get("promotable_to_priority") or [])
    if not req.symbol or not (promotable or base == "scalp_priority"):
        return base, None
    sp = _lib("scalp_priority")
    cfg = ((policy.get("priority") or {}).get("scalp") or {})
    fallback = base if base != "scalp_priority" else "catalyst_confirmation"
    if req.priority_hint == "scalp_priority":
        sym = str(req.symbol).upper()
        reasons: list[str] = []
        if sp.session_phase(now, cfg) is None:
            reasons.append("SESSION_CLOSED")
        prev = sp.last_researched_from_receipts(_lib("search_budget").routing_receipts_path(root), now=now).get(sym)
        if prev is not None and (now - prev).total_seconds() < float(cfg.get("research_stale_after_min", 30)) * 60:
            reasons.append("RESEARCHED_RECENTLY")
        info = {"symbol": sym, "priority": not reasons, "source": "caller_hint", "reasons": reasons or ["CALLER_HINT"]}
        return ("scalp_priority" if not reasons else fallback), info
    if scalp_rows is None:
        scalp_rows = sp.load_scalp_list(_state_root(root), str(cfg.get("list_projection") or ""))
    rows, as_of = scalp_rows
    handed = [dict(c) for c in req.candidates or [] if isinstance(c, Mapping)]
    sym = str(req.symbol).upper()
    receipts = _lib("search_budget").routing_receipts_path(root)
    last = sp.last_researched_from_receipts(receipts, now=now)
    go_min = sp.go_min_score(float(cfg.get("go_min_score_default", 40)))
    decisions = []
    if handed:
        decisions += sp.classify(handed, now=now, cfg=cfg, go_min=go_min, last_researched=last, handed_in=True)
    decisions += sp.classify([r for r in rows if str(r.get("symbol") or "").upper() not in
                              {str(h.get("symbol") or "").upper() for h in handed}],
                             now=now, cfg=cfg, go_min=go_min, last_researched=last, list_as_of=as_of)
    # Rank once across both sources so the per-cycle cap is global.
    pri = sorted([d for d in decisions if d.priority], key=lambda d: (-(d.score or 0.0), d.symbol))
    cap = int(cfg.get("max_per_cycle", 5))
    mine = next((d for d in decisions if d.symbol == sym), None)
    if mine is None:
        mine = sp.PriorityDecision(symbol=sym, priority=False, reasons=["NOT_ON_SCALP_LIST"])
    elif mine.priority and mine not in pri[:cap]:
        mine.priority, mine.reasons = False, ["OVER_CYCLE_CAP"]
    info = mine.to_dict()
    if mine.priority:
        return "scalp_priority", info
    return fallback, info


# ── the engine ──────────────────────────────────────────────────────────────


def _receipt(row: dict[str, Any], root: Optional[Path]) -> Optional[dict[str, Any]]:
    return _lib("search_budget").append_routing_receipt(row, root=root)


def route(
    req: SearchRequest,
    *,
    policy: Optional[dict[str, Any]] = None,
    clock: Optional[Clock] = None,
    root: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    enabled: Optional[bool] = None,
    dry_run: Optional[bool] = None,
    free_transport: Any = None,
    paid_transport: Any = None,
    api_key: Optional[str] = None,
    db_query: Any = None,
    registry: Optional[dict[str, Any]] = None,
    scalp_rows: Optional[tuple[list[dict[str, Any]], Optional[datetime]]] = None,
) -> RoutedResponse:
    """Route one question through cache -> free -> paid -> no_coverage. Never raises."""
    t0 = _time.monotonic()
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    env_map = env if env is not None else os.environ
    on = engine_enabled(env_map) if enabled is None else bool(enabled)
    dry = dry_run_forced(env_map) if dry_run is None else bool(dry_run)
    if not on:
        return RoutedResponse(ok=False, reason="ENGINE_DISABLED")
    try:
        pol = policy if policy is not None else _lib("search_routing_policy").load_policy()
    except Exception as exc:  # noqa: BLE001 — an invalid policy routes nothing (fail closed)
        return RoutedResponse(ok=False, reason=f"POLICY_INVALID:{str(exc)[:200]}")
    q = str(req.query or "").strip()
    if not q:
        return RoutedResponse(ok=False, reason="EMPTY_QUERY")
    try:
        cls_name, pri = resolve_class(pol, req, now=now, root=root, scalp_rows=scalp_rows)
    except Exception as exc:  # noqa: BLE001
        cls_name, pri = (pol.get("callers") or {}).get(str(req.caller or "")), {"error": f"{type(exc).__name__}"}
    base = {"ts": _iso(now), "caller": req.caller, "symbol": (str(req.symbol).upper() if req.symbol else None),
            "query_hash": hashlib.sha256(q.encode("utf-8")).hexdigest()[:16], "priority": pri}
    if cls_name is None:
        row = {**base, "class": None, "pool": None, "tier": 3, "source": None, "reason": "UNKNOWN_CALLER",
               "answered": False, "cost_usd": 0.0, "cache_hit": False, "units_paid": 0, "units_free": 0}
        if not dry:
            _receipt(row, root)
        return RoutedResponse(ok=False, reason="UNKNOWN_CALLER", no_coverage="refuse_up_front", dry_run=dry,
                              receipt=None if dry else row, tier=3)
    cls = (pol.get("classes") or {})[cls_name]
    pool = str(cls.get("pool"))
    kind = req.kind if req.kind in ("web", "news") else str(cls.get("kind") or "web")
    price = float((pol.get("pricing") or {}).get("usd_per_request") or 0.0)
    trusted_domains = (pol.get("quality") or {}).get("trusted_domains") or []
    qcfg = {**((pol.get("quality") or {}).get("default") or {}), **(cls.get("quality") or {})}
    qual = _lib("search_quality")
    paid = cls.get("paid") or {}
    if req.cache_identity:
        subj, intent = req.cache_identity
        ckey = hashlib.sha256(f"identity|{kind}|{str(subj).upper()}|{' '.join(str(intent).lower().split())}"
                              .encode("utf-8")).hexdigest()
    else:
        ckey = cache_key(kind, q, req.symbol)
    ttl = int(cls.get("cache_ttl_s") or 0)
    if req.cache_ttl_s is not None:
        ttl = max(0, min(ttl, int(req.cache_ttl_s)))
    cpath = cache_path(pol, root)
    cache_cfg = pol.get("cache") or {}
    base.update({"class": cls_name, "pool": pool, "kind": kind})
    plan: list[dict[str, Any]] = []

    def finish(resp: RoutedResponse, row: dict[str, Any]) -> RoutedResponse:
        row["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        resp.question_class, resp.pool, resp.priority, resp.dry_run, resp.plan = cls_name, pool, pri, dry, plan
        if not dry:
            resp.receipt = _receipt({**base, **row}, root) or {**base, **row}
        else:
            resp.receipt = {**base, **row, "dry_run": True}
        return resp

    # tier 0 — shared cache
    hit = cache_get(cpath, ckey, ttl_s=ttl, now=now)
    plan.append({"tier": 0, "source": "cache", "ttl_s": ttl, "hit": bool(hit)})
    if hit and (hit.get("sufficient") or int(hit.get("tier") or 0) == 2 or not paid.get("allowed")):
        results = list(hit.get("results") or [])
        return finish(RoutedResponse(ok=True, reason="CACHE_HIT", results=results, provider=str(hit.get("provider") or "cache"),
                                     cache_hit=True, tier=0, sufficient=bool(hit.get("sufficient"))),
                      {"tier": 0, "source": "cache", "reason": "CACHE_HIT", "answered": bool(results), "cost_usd": 0.0,
                       "cache_hit": True, "units_paid": 0, "units_free": 0})

    # tier 1 — free lane
    ctx = _Ctx(req=SearchRequest(**{**asdict(req), "query": q}), policy=pol, cls_name=cls_name, cls=cls, root=root,
               free_transport=free_transport, db_query=db_query, registry=registry)
    free_rows: list[dict[str, Any]] = []
    units_free = 0
    attempts: list[str] = []
    assessment = qual.assess([], query=q, symbol=req.symbol, cfg=qcfg, trusted_domains=trusted_domains, now=now)
    for src in cls.get("free_tiers") or []:
        if dry:
            plan.append({"tier": 1, "source": src, "would_call": True})
            continue
        fn = ADAPTERS.get(src)
        if fn is None:
            attempts.append(f"{src}:NO_ADAPTER")
            continue
        try:
            tr = fn(ctx, kind)
        except Exception as exc:  # noqa: BLE001 — a failing free source is a note, not a crash
            tr = TierResult(src, False, f"ERROR:{type(exc).__name__}")
        units_free += tr.units_free
        attempts.append(f"{src}:{tr.reason if not tr.ok else 'OK:' + str(len(tr.results))}")
        free_rows = _merge(free_rows, tr.results, limit=req.count)
        assessment = qual.assess(free_rows, query=q, symbol=req.symbol, cfg=qcfg, trusted_domains=trusted_domains, now=now)
        if assessment["sufficient"]:
            break

    def _provider(rows: list[dict[str, Any]]) -> str:
        provs = sorted({str(r.get("provider") or "") for r in rows if r.get("provider")})
        return provs[0] if len(provs) == 1 else ("mixed:" + "+".join(provs) if provs else "")

    if not dry and assessment["sufficient"]:
        cache_put(cpath, ckey, {"results": free_rows, "provider": _provider(free_rows), "tier": 1, "sufficient": True,
                                "class": cls_name}, now=now, max_entries=int(cache_cfg.get("max_entries", 2000)),
                  max_age_s=int(cache_cfg.get("max_age_s", 86400)))
        return finish(RoutedResponse(ok=True, reason="FREE_SUFFICIENT", results=free_rows[: max(req.count, 1)],
                                     provider=_provider(free_rows), tier=1, sufficient=True),
                      {"tier": 1, "source": _provider(free_rows), "reason": "FREE_SUFFICIENT", "answered": True,
                       "cost_usd": 0.0, "cache_hit": False, "units_paid": 0, "units_free": units_free,
                       "quality": assessment, "attempts": attempts})

    # tier 2 — paid Brave
    spend = _lib("search_spend")
    paid_reason = None
    paid_rows: list[dict[str, Any]] = []
    cost = 0.0
    reservation_id = None
    decision_box: list[Any] = []
    if not paid.get("allowed"):
        paid_reason = "PAID_NOT_ALLOWED_FOR_CLASS"
    else:
        # Preview the dollar decision read-only (the binding one runs inside the ledger lock).
        try:
            doc = _lib("search_budget").ledger_doc(root=root)
            preview = spend.decide(pol, spend.snapshot(doc, pol, now), pool, today=now.date())
            plan.append({"tier": 2, "source": "brave", "budget_preview": preview.reason,
                         "est_usd": preview.est_usd, "would_call": preview.allowed})
        except Exception as exc:  # noqa: BLE001
            preview = None
            plan.append({"tier": 2, "source": "brave", "budget_preview": f"LEDGER_UNREADABLE:{type(exc).__name__}",
                         "would_call": False})
        br = _lib("brave_router")
        if dry:
            paid_reason = "DRY_RUN"
        elif preview is None:
            paid_reason = "BUDGET_UNAVAILABLE"
        elif not preview.allowed:
            paid_reason = f"DOLLAR_BUDGET:{preview.reason}"
        elif paid_transport is None and not br.live_armed():
            paid_reason = "PAID_NOT_ARMED"
        else:
            gcfg = (pol.get("goggles") or {}).get(str(paid.get("goggle") or "")) or {}
            goggle = gcfg.get("goggle_url") if gcfg.get("enabled") and gcfg.get("goggle_url") else None
            xs = bool((pol.get("extra_snippets") or {}).get("enabled"))
            pkind = str(paid.get("kind") or kind)
            idem = req.idempotency_key or f"route|{cls_name}|{ckey[:24]}|{now.strftime('%Y%m%d%H%M')}"
            try:
                resp = br.search(q, kind=pkind, count=int(paid.get("count") or req.count),
                                 freshness=paid.get("freshness"), caller=f"route.{pool}", purpose=f"route:{cls_name}",
                                 idempotency_key=idem, clock=clock, root=root, transport=paid_transport,
                                 api_key=api_key, enabled=True, no_spill=True,
                                 budget_gate=spend.make_gate(pol, pool, decision_box.append),
                                 goggles=goggle if pkind == "web" else None, extra_snippets=xs and pkind == "web")
            except Exception as exc:  # noqa: BLE001
                resp = None
                paid_reason = f"PAID_ERROR:{type(exc).__name__}"
            if resp is not None:
                reservation_id = getattr(resp, "reservation_id", None)
                if resp.ok:
                    paid_rows = [{**r, "provider": "brave"} for r in list(resp.results or [])]
                    cost = 0.0 if resp.cache_hit else price
                    paid_reason = "PAID_CACHE_HIT" if resp.cache_hit else "PAID_OK"
                else:
                    paid_reason = str(resp.reason or "PAID_REFUSED")

    merged = _merge(paid_rows, free_rows, limit=req.count)
    final = qual.assess(merged, query=q, symbol=req.symbol, cfg=qcfg, trusted_domains=trusted_domains, now=now)
    row = {"units_free": units_free, "units_paid": 1 if cost > 0 else 0, "cost_usd": round(cost, 6),
           "cache_hit": False, "quality": final, "attempts": attempts, "paid_reason": paid_reason,
           "spend_decision": decision_box[-1].to_dict() if decision_box else None}
    if dry:
        return finish(RoutedResponse(ok=False, reason="DRY_RUN", tier=None),
                      {**row, "tier": None, "source": None, "reason": "DRY_RUN", "answered": False})
    if paid_rows:
        cache_put(cpath, ckey, {"results": merged, "provider": _provider(merged), "tier": 2,
                                "sufficient": final["sufficient"], "class": cls_name}, now=now,
                  max_entries=int(cache_cfg.get("max_entries", 2000)), max_age_s=int(cache_cfg.get("max_age_s", 86400)))
        return finish(RoutedResponse(ok=True, reason=paid_reason or "PAID_OK", results=merged[: max(req.count, 1)],
                                     provider=_provider(merged), tier=2, cost_usd=round(cost, 6),
                                     sufficient=final["sufficient"], reservation_id=reservation_id),
                      {**row, "tier": 2, "source": "brave", "reason": paid_reason, "answered": True})
    if free_rows:
        # The free answer stands, labelled insufficient; it is cached only for classes that cannot escalate.
        if not paid.get("allowed"):
            cache_put(cpath, ckey, {"results": free_rows, "provider": _provider(free_rows), "tier": 1,
                                    "sufficient": False, "class": cls_name}, now=now,
                      max_entries=int(cache_cfg.get("max_entries", 2000)), max_age_s=int(cache_cfg.get("max_age_s", 86400)))
        reason = f"FREE_INSUFFICIENT:{paid_reason}"
        return finish(RoutedResponse(ok=True, reason=reason, results=free_rows[: max(req.count, 1)],
                                     provider=_provider(free_rows), tier=1, sufficient=False),
                      {**row, "tier": 1, "source": _provider(free_rows), "reason": reason, "answered": True})
    nc = str(cls.get("no_coverage") or "say_so")
    reason = f"NO_COVERAGE:{nc}"
    return finish(RoutedResponse(ok=False, reason=reason, tier=3, no_coverage=nc),
                  {**row, "tier": 3, "source": None, "reason": f"{reason}|{paid_reason}", "answered": False})


def route_query(query: str, *, caller: str, symbol: Optional[str] = None, kind: Optional[str] = None,
                count: int = 5, candidates: Optional[list[dict[str, Any]]] = None, **kw: Any) -> RoutedResponse:
    """Convenience: ``route(SearchRequest(...), **kw)``."""
    return route(SearchRequest(query=query, caller=caller, symbol=symbol, kind=kind, count=count,
                               candidates=list(candidates or [])), **kw)


#: Agent Q's request classes (branch n8nmat/scalp-hot-tier) -> the hint the engine verifies.
_Q_CLASSES = {"scalp_priority": "scalp_priority", "scalp_research": None}


def route_search(query: str, *, request_class: str, caller: str, subject: str, intent: str,
                 time_range: str = "day", categories: str = "news", limit: int = 3, cache_ttl_s: int = 1200,
                 dry_run: bool = False, env: Optional[Mapping[str, str]] = None,
                 candidates: Optional[list[dict[str, Any]]] = None, **kw: Any) -> dict[str, Any]:
    """The hot-tier call shape (Agent Q, 2026-10-10). Returns
    ``{ok, results:[{title,url,content,engine,published}], provider, cache_hit, as_of, decision, denied_reason}``.

    * ``request_class`` "scalp_priority" asks for first claim on the paid budget (granted only inside a
      session and when the subject was not researched in the last 30 min); "scalp_research" routes as the
      caller's policy class (catalyst_confirmation for hermes_scalp_catalyst / catalyst_momentum_engine).
    * the cache is keyed on (subject, intent) — L708 and L379 share entries; TTL = min(cache_ttl_s, class TTL).
    * ``dry_run=True`` reaches no provider, writes no ledger/receipt/cache: no budget can be spent.
    * ``time_range`` is advisory (the class quality rule sets freshness); ``categories`` "news" -> kind news.
    Live calls need SEARCH_ROUTING_ENGINE=1 (else ``denied_reason=ENGINE_DISABLED``); a dry run plans without it.
    """
    if request_class not in _Q_CLASSES:
        now = datetime.now(timezone.utc)
        return {"ok": False, "results": [], "provider": "", "cache_hit": False, "as_of": _iso(now),
                "decision": {"request_class": request_class}, "denied_reason": "UNKNOWN_REQUEST_CLASS"}
    kind = "news" if str(categories or "").lower() == "news" else "web"
    req = SearchRequest(query=query, caller=caller, symbol=subject or None, kind=kind, count=int(limit or 3),
                        priority_hint=_Q_CLASSES[request_class], cache_identity=(str(subject or ""), str(intent or "")),
                        cache_ttl_s=int(cache_ttl_s), candidates=list(candidates or []))
    clock = kw.get("clock") or (lambda: datetime.now(timezone.utc))
    kw["clock"] = clock
    if dry_run:
        kw.setdefault("enabled", True)   # a plan touches nothing, so it needs no flag
    resp = route(req, env=env, dry_run=dry_run, **kw)
    rows = [{"title": str(r.get("title") or ""), "url": str(r.get("url") or ""),
             "content": str(r.get("description") or r.get("snippet") or r.get("content") or "")[:500],
             "engine": str(r.get("provider") or resp.provider or ""),
             "published": str(r.get("published_at") or r.get("age") or "")} for r in resp.results]
    return {"ok": bool(resp.ok and rows), "results": rows, "provider": resp.provider, "cache_hit": resp.cache_hit,
            "as_of": _iso(clock()),
            "decision": {"request_class": request_class, "question_class": resp.question_class, "pool": resp.pool,
                         "tier": resp.tier, "reason": resp.reason, "cost_usd": resp.cost_usd,
                         "sufficient": resp.sufficient, "priority": resp.priority, "dry_run": resp.dry_run,
                         "plan": resp.plan if resp.dry_run else None},
            "denied_reason": None if (resp.ok and rows) else resp.reason}


__all__ = ["route_search", "SCHEMA", "FLAG_ENGINE", "FLAG_DRY_RUN", "SearchRequest", "RoutedResponse", "engine_enabled",
           "dry_run_forced", "route", "route_query", "resolve_class", "cache_key", "cache_get", "cache_put", "ADAPTERS"]
