"""Gap resolver — when an answer is stale or missing, go find out through
DECLARED vectors, in a declared order, inside a declared budget, leaving a
receipt for every attempt.

THE OPERATOR'S QUESTION (2026-09-13, verbatim)
----------------------------------------------
"what happens when the information is stale or it doesn't meet the operator's
need — how does it find out through multiple different vectors: one for Hermes
research, two for like DeepSeek curation, etc."

Before this module the honest answer was: it mostly doesn't. A desk or
projection that met stale or missing data either served the old value, opened a
pending that might never close, or said "no coverage". The pieces existed —
``gather_tradeai_evidence`` names the gaps, ``_enqueue_hermes_research`` queues
Hermes, ``brave_router`` governs search, ``deepseek_offpeak`` knows when DeepSeek
is cheap, ``retired_providers`` knows which slots are dead — but nothing ran them
as a sequence, nothing budgeted them, and nothing wrote down what was tried.

THE VECTORS, in the only order they may run
-------------------------------------------
    refresh_producer   free     re-run the domain's declared writer (never a new one)
    backup_provider    free     the registry's backup chain — same question only
    governed_search    metered  brave_router (Phase 5 teaches it to spill to SearXNG)
    hermes_research    metered  _enqueue_hermes_research — slow, returns an ETA
    llm_curation       metered  DeepSeek off-peak (Ollama when the window is closed)
                                CURATES evidence already gathered; never invents
    operator_ask       free     ONE question to the operator, with an ETA — always last

Rules enforced here, not left to the caller:
  * free before metered before paid (the free_first rail, ``reject_paid_transition``);
  * a retired provider is never a vector — ``retired_providers.is_retired`` — and the
    refusal is a receipt (``retired_skipped``), never a silent fall-through;
  * every attempt writes one receipt row, append-only, whatever the outcome;
  * a budget is per vector per day, counted from the receipts, so it survives restarts;
  * ``llm_curation`` with no gathered evidence does not call a model at all;
  * ``operator_ask`` is the last vector, never the first.

The chain is read from ``config/data_source_authority.json`` under the domain's
``on_gap`` key when present (the proposal lives in
docs/implementation/sot/phase7_registry_patch.json until the registry owner merges
it) and falls back to DEFAULT_ON_GAP otherwise.

Nothing here has broker, order, stop or 2FA authority. Nothing here writes a
domain store; ``refresh_producer`` only invokes the writer the registry already
names, and only when ``GAP_RESOLVER_LIVE=1`` — without it every side-effecting
vector records what it WOULD have done (dry run, AGENTS.md §0 rule 7).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "GapResolution@v1"
RECEIPT_SCHEMA = "GapResolutionReceipt@v1"

#: Append-only. Prefer ``~/.local/state/tradeai/`` (measurable without
#: release-write), then served persistent-state, then checkout-relative.
RECEIPTS_REL = "data/cio/gap_resolution_receipts.jsonl"
RECEIPTS_PATH = PROJECT_ROOT / RECEIPTS_REL


def _local_receipts_path() -> Path:
    return Path.home() / ".local/state/tradeai/gap_resolution_receipts.jsonl"


def _persistent_receipts_path() -> Optional[Path]:
    try:
        from scripts.lib.persistent_state_root import good_persistent_root

        return good_persistent_root() / RECEIPTS_REL
    except Exception:  # noqa: BLE001 — resolution must never block resolve()
        return None


def default_receipts_path() -> Path:
    """Local state first; persistent-state when present; else checkout-relative.

    Tests monkeypatch ``RECEIPTS_PATH`` onto a tmp file — honour that redirect
    before any production preference so hermetic suites never dual-write the
    operator's local ledger.
    """
    canonical = PROJECT_ROOT / RECEIPTS_REL
    try:
        if RECEIPTS_PATH.resolve() != canonical.resolve():
            return RECEIPTS_PATH
    except OSError:
        if RECEIPTS_PATH != canonical:
            return RECEIPTS_PATH
    local = _local_receipts_path()
    if local.is_file() or local.parent.is_dir():
        return local
    served = _persistent_receipts_path()
    if served is not None and (
        served.parent.is_dir() or served.parent.parent.is_dir()
    ):
        return served
    return RECEIPTS_PATH


def _receipt_write_targets(primary: Path) -> list[Path]:
    """Dual-write local + persistent (+ checkout) on default paths; single path for tests."""
    canonical = PROJECT_ROOT / RECEIPTS_REL
    known: list[Path] = [_local_receipts_path(), canonical]
    served = _persistent_receipts_path()
    if served is not None:
        known.append(served)

    def _key(p: Path) -> str:
        try:
            return str(p.resolve())
        except OSError:
            return str(p)

    primary_key = _key(primary)
    # Monkeypatched RECEIPTS_PATH / Context.receipts_path → single target only.
    if primary_key not in {_key(k) for k in known}:
        return [primary]
    targets: list[Path] = [_local_receipts_path()]
    if served is not None and served.parent.is_dir():
        targets.append(served)
    if canonical.parent.is_dir():
        targets.append(canonical)
    out: list[Path] = []
    seen: set[str] = set()
    for t in targets:
        k = _key(t)
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out or [primary]

AUTHORITY_PATH = PROJECT_ROOT / "config" / "data_source_authority.json"

#: Arm for real side effects (running a producer, calling a provider, sending).
#: Tests never set it. Unset, every side-effecting vector is a dry run that
#: records what it would have done.
FLAG_LIVE = "GAP_RESOLVER_LIVE"
#: Operator grant for a vector whose cost_class is "paid". Absent, the
#: free_first rail (reject_paid_transition) refuses the slot and says so.
FLAG_PAID = "GAP_RESOLVER_PAID_AUTHORIZED"

VECTORS = (
    "refresh_producer",
    "backup_provider",
    "governed_search",
    "hermes_research",
    "llm_curation",
    "operator_ask",
)
COST_CLASSES = ("free", "metered", "paid")
COST_RANK = {c: i for i, c in enumerate(COST_CLASSES)}
OUTCOMES = (
    "answered",         # an authoritative value for the question, with as_of
    "partial",          # evidence gathered, not yet an answer (search hits, curation)
    "queued",           # a slow vector accepted the request; eta_seconds set
    "no_answer",        # ran (or dry-ran) and produced nothing
    "budget_denied",    # the day's attempts for this vector are spent
    "retired_skipped",  # the provider is retired in the registry; refused up front
    "error",            # the vector raised; message in detail
)
WHYS = ("stale_hours", "no_producer", "no_coverage", "unanswerable")

#: The fallback chain when a domain declares no ``on_gap``. Budgets are per
#: vector per UTC day; ``expected_seconds`` is what the desk tells the operator.
DEFAULT_ON_GAP: list[dict[str, Any]] = [
    {"vector": "refresh_producer", "cost_class": "free", "max_per_day": 6, "expected_seconds": 120},
    {"vector": "backup_provider", "cost_class": "free", "max_per_day": 12, "expected_seconds": 30},
    {"vector": "governed_search", "cost_class": "metered", "max_per_day": 10, "expected_seconds": 20},
    {"vector": "hermes_research", "cost_class": "metered", "max_per_day": 4, "expected_seconds": 1800},
    {"vector": "llm_curation", "cost_class": "metered", "max_per_day": 6, "expected_seconds": 60},
    {"vector": "operator_ask", "cost_class": "free", "max_per_day": 1, "expected_seconds": 7200},
]

#: Vectors whose daily budget is counted PER GOAL rather than globally.
#:
#: `operator_ask` was capped at one question per day across the whole system, so
#: a measured receipt shows the day's SECOND question refused human escalation
#: because an unrelated first question had used the only slot. The cap exists to
#: stop the desk pestering the operator about ONE thing repeatedly -- not to
#: ration the number of distinct things that may be asked about. Counting per
#: goal keeps the former and removes the latter. Gaps that name no goal share
#: ONE bucket among themselves -- the historic single slot -- rather than
#: competing with goal-scoped work for it, which would simply move the defect.
PER_GOAL_BUDGET_VECTORS = frozenset({"operator_ask"})

#: Desk evidence-domain names → registry domains. The desk speaks in needs
#: ("analyst_view"); the registry speaks in domains ("analyst_opinion").
DESK_DOMAIN_MAP = {
    "hermes_research": "research_thesis",
    "research": "research_thesis",
    "analyst_view": "analyst_opinion",
    "analyst": "analyst_opinion",
    "reentry_decision_desk": "technicals",
    "reentry": "technicals",
    "row": "technicals",
    "risk": "holdings_accounts",
    "portfolio": "holdings_accounts",
    "cash": "holdings_accounts",
    "book": "holdings_accounts",
    "quote": "quote_price",
    "price": "quote_price",
    "news": "catalyst_news",
    "catalyst": "catalyst_news",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def live_armed(env: Optional[dict[str, str]] = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(FLAG_LIVE, "")).strip().lower() in ("1", "true", "yes", "on")


def paid_authorized(env: Optional[dict[str, str]] = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(FLAG_PAID, "")).strip().lower() in ("1", "true", "yes", "on")


# ── the two contracts ────────────────────────────────────────────────────────


@dataclass
class DataGap:
    """What is missing, for whom, and why the store could not answer."""

    domain: str
    subject: str
    question: str
    why: str = "stale_hours"           # one of WHYS
    requester: str = "desk"            # operator chat_id / desk / projection id
    symbols: list[str] = field(default_factory=list)
    stale_age_hours: Optional[float] = None
    evidence: dict[str, Any] = field(default_factory=dict)   # already-gathered facts
    gap_id: str = ""
    #: The cio_goals goal this gap is being worked for, when there is one.
    #: Deliberately NOT part of the gap_id payload below: the same question is
    #: the same gap whoever asks it, and folding this in would fork every id.
    goal_id: str = ""

    def __post_init__(self) -> None:
        self.domain = str(self.domain or "").strip()
        self.subject = str(self.subject or "").strip().upper()
        if self.why not in WHYS:
            self.why = "no_coverage"
        if not self.symbols and self.subject and self.subject != "BOOK":
            self.symbols = [self.subject]
        if not self.gap_id:
            payload = f"tradeai:gap:{self.domain}|{self.subject}|{self.question}"
            self.gap_id = str(uuid.uuid5(uuid.NAMESPACE_URL, payload))


@dataclass
class Attempt:
    vector: str
    outcome: str
    cost_class: str
    provider: Optional[str] = None
    model: Optional[str] = None
    as_of: Optional[str] = None
    eta_seconds: Optional[int] = None
    detail: str = ""
    started: str = ""
    finished: str = ""


@dataclass
class Resolution:
    """What the caller gets. Either an answer with its provenance, or a
    declared gap with what was tried and what is still coming."""

    schema: str = SCHEMA
    authority: str = AUTHORITY
    gap_id: str = ""
    domain: str = ""
    subject: str = ""
    outcome: str = "no_coverage"       # answered | partial | queued | no_coverage
    answered: bool = False
    answer: Any = None
    as_of: Optional[str] = None
    age_hours: Optional[float] = None
    source: Optional[str] = None       # "<vector>:<provider>" or "llm_curation:<model>"
    vector: Optional[str] = None       # the vector that answered / queued
    model: Optional[str] = None
    eta_seconds: Optional[int] = None  # set when a slow vector was queued
    operator_question: Optional[str] = None
    no_coverage_behaviour: Optional[str] = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def eta_text(self) -> Optional[str]:
        """'≈ N min' for the operator. None when nothing slow was queued."""
        if self.eta_seconds is None:
            return None
        mins = max(1, int(round(self.eta_seconds / 60.0)))
        return f"≈ {mins} min"


@dataclass
class VectorResult:
    """What one vector returns. The resolver turns it into a receipt."""

    outcome: str
    answer: Any = None
    as_of: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    eta_seconds: Optional[int] = None
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    operator_question: Optional[str] = None


@dataclass
class Context:
    """Everything a vector may touch, injected so tests can replace all I/O."""

    now: Callable[[], datetime] = _now
    receipts_path: Optional[Path] = None      # None → module RECEIPTS_PATH at call time
    live: Optional[bool] = None               # None → read FLAG_LIVE
    chat_id: str = ""
    pending_id: str = ""
    operator_text: str = ""
    send_fn: Optional[Callable[..., dict[str, Any]]] = None
    recheck: Optional[Callable[[], Any]] = None   # re-read the store after a refresh
    #: The caller's own _enqueue_hermes_research. The desk module is importable
    #: under two names (lib.* and scripts.lib.*); importing it here would bind
    #: a DIFFERENT module object from the one the caller (and its tests) hold.
    hermes_enqueue: Optional[Callable[..., dict[str, Any]]] = None
    env: Optional[dict[str, str]] = None

    def is_live(self) -> bool:
        return live_armed(self.env) if self.live is None else bool(self.live)

    @property
    def receipts(self) -> Path:
        return self.receipts_path or default_receipts_path()


# ── registry ─────────────────────────────────────────────────────────────────


def _authority(path: Optional[Path] = None) -> dict[str, Any]:
    try:
        return json.loads((path or AUTHORITY_PATH).read_text(encoding="utf-8"))
    except Exception:
        return {"domains": [], "providers": {}}


def registry_domain(domain: str, *, authority: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """The registry row for a domain, accepting desk names too. {} if unknown."""
    auth = authority if authority is not None else _authority()
    name = DESK_DOMAIN_MAP.get(str(domain or ""), str(domain or ""))
    for row in auth.get("domains") or []:
        if row.get("domain") == name:
            return row
    return {}


def canonical_domain(domain: str) -> str:
    return DESK_DOMAIN_MAP.get(str(domain or ""), str(domain or ""))


def load_on_gap(domain: str, *, authority: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """The declared ``on_gap`` chain for a domain, or DEFAULT_ON_GAP.

    Whatever the source, the chain is normalised: unknown vectors dropped,
    free→metered→paid order enforced (stable), operator_ask forced last.
    """
    row = registry_domain(domain, authority=authority)
    raw = row.get("on_gap") if isinstance(row.get("on_gap"), list) else None
    chain = [dict(x) for x in (raw or DEFAULT_ON_GAP) if isinstance(x, dict)]
    return normalise_chain(chain)


def normalise_chain(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    defaults = {c["vector"]: c for c in DEFAULT_ON_GAP}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in chain:
        v = str(entry.get("vector") or "")
        if v not in VECTORS or v in seen:
            continue
        seen.add(v)
        base = dict(defaults[v])
        base.update({k: entry[k] for k in ("cost_class", "max_per_day", "expected_seconds") if k in entry})
        if base.get("cost_class") not in COST_RANK:
            base["cost_class"] = defaults[v]["cost_class"]
        base["max_per_day"] = max(0, int(base.get("max_per_day") or 0))
        base["expected_seconds"] = int(base.get("expected_seconds") or 0)
        out.append(base)
    # free before metered before paid; stable within a class. The registry may
    # list them however it likes -- the rail is enforced here.
    body = [c for c in out if c["vector"] != "operator_ask"]
    body.sort(key=lambda c: COST_RANK[c["cost_class"]])
    tail = [c for c in out if c["vector"] == "operator_ask"]
    return body + tail


# ── receipts and budgets ─────────────────────────────────────────────────────


def _append_receipt(path: Path, row: dict[str, Any]) -> None:
    line = json.dumps(row, sort_keys=True, default=str) + "\n"
    for target in _receipt_write_targets(path):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            continue


def read_receipts(path: Optional[Path] = None) -> list[dict[str, Any]]:
    p = path or default_receipts_path()
    if not p.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows


def attempts_today(vector: str, *, path: Optional[Path] = None, now: Optional[datetime] = None,
                   rows: Optional[list[dict[str, Any]]] = None,
                   goal_id: Optional[str] = None) -> int:
    """Attempts that consumed budget today: everything except refusals.

    `goal_id` scopes the count to one goal's own attempts. Passing None counts
    globally, which is the historic behaviour and stays the default. Passing
    `""` counts the attempts that name NO goal -- including every receipt
    written before this field existed, which is what keeps the ungoaled bucket
    honest rather than starting it back at zero.
    """
    day = (now or _now()).date().isoformat()
    n = 0
    for r in (rows if rows is not None else read_receipts(path)):
        if r.get("vector") != vector:
            continue
        if str(r.get("started") or "")[:10] != day:
            continue
        if r.get("outcome") in ("budget_denied", "retired_skipped"):
            continue
        if goal_id is not None and str(r.get("goal_id") or "") != str(goal_id):
            continue
        n += 1
    return n


# ── the default vector implementations ───────────────────────────────────────
# Each one is fail-soft, touches nothing without ctx.is_live(), and NEVER
# imports a retired provider. Tests replace them wholesale through `vectors=`.


def _v_refresh_producer(gap: DataGap, entry: dict[str, Any], ctx: Context) -> VectorResult:
    row = registry_domain(gap.domain)
    writer = row.get("writer") or row.get("writer_target")
    provider = row.get("primary_provider")
    if not writer or writer == "operator":
        return VectorResult("no_answer", provider=provider,
                            detail="no_producer: the registry names no writer for this domain")
    script = PROJECT_ROOT / str(writer)
    if not script.is_file():
        return VectorResult("no_answer", provider=provider, detail=f"writer_missing:{writer}")
    cmd = [sys.executable, str(script)]
    if not ctx.is_live():
        return VectorResult("no_answer", provider=provider,
                            detail=f"dry_run: would run {writer} ({FLAG_LIVE} unset)")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(PROJECT_ROOT))
    except (OSError, subprocess.SubprocessError) as exc:
        return VectorResult("error", provider=provider, detail=f"{type(exc).__name__}:{exc}")
    if proc.returncode != 0:
        return VectorResult("no_answer", provider=provider,
                            detail=f"writer_exit_{proc.returncode}: {(proc.stderr or '')[-300:]}")
    # Exit 0 is not evidence. Re-read the store; only a value is an answer.
    fresh = ctx.recheck() if ctx.recheck else None
    if fresh:
        as_of = fresh.get("as_of") if isinstance(fresh, dict) else None
        return VectorResult("answered", answer=fresh, as_of=as_of or _iso(ctx.now()), provider=provider,
                            detail=f"ran {writer}; store re-read")
    return VectorResult("no_answer", provider=provider, detail=f"ran {writer}; store still has no answer")


#: On-demand fetchers for a backup provider, keyed (registry domain, provider).
#: Same question, different provider -- the only substitution the registry allows.
BACKUP_FETCHERS: dict[tuple[str, str], Callable[[DataGap, Context], VectorResult]] = {}


def _yf_analyst(gap: DataGap, ctx: Context) -> VectorResult:
    import yfinance as yf  # declared provider; lazy so the module imports without it

    sym = gap.symbols[0] if gap.symbols else gap.subject
    info = yf.Ticker(sym).info or {}
    mean = info.get("recommendationMean")
    if mean is not None and not (1 <= float(mean) <= 5):
        mean = None  # the same 1-5 rail the analyst domain enforces
    if mean is None and info.get("targetMeanPrice") is None:
        return VectorResult("no_answer", provider="yfinance_on_demand", detail=f"yfinance has no analyst view for {sym}")
    answer = {
        "symbol": sym,
        "rating": info.get("recommendationKey"),
        "rating_mean": float(mean) if mean is not None else None,
        "target_low": info.get("targetLowPrice"),
        "target_mean": info.get("targetMeanPrice"),
        "target_high": info.get("targetHighPrice"),
        "analysts": info.get("numberOfAnalystOpinions"),
        "as_of": _iso(ctx.now()),
        "source": "yfinance_on_demand",
    }
    return VectorResult("answered", answer=answer, as_of=answer["as_of"], provider="yfinance_on_demand")


def _yf_quote(gap: DataGap, ctx: Context) -> VectorResult:
    import yfinance as yf

    sym = gap.symbols[0] if gap.symbols else gap.subject
    fi = yf.Ticker(sym).fast_info
    price = getattr(fi, "last_price", None)
    if price is None:
        return VectorResult("no_answer", provider="yfinance", detail=f"yfinance has no last price for {sym}")
    as_of = _iso(ctx.now())
    return VectorResult("answered", answer={"symbol": sym, "price": float(price), "as_of": as_of, "provider": "yfinance"},
                        as_of=as_of, provider="yfinance")


BACKUP_FETCHERS[("analyst_opinion", "yfinance_on_demand")] = _yf_analyst
BACKUP_FETCHERS[("quote_price", "yfinance")] = _yf_quote


def _v_backup_provider(gap: DataGap, entry: dict[str, Any], ctx: Context) -> VectorResult:
    """Walk the registry backup chain. A retired slot is refused up front and the
    refusal is returned as its own outcome so it lands in a receipt."""
    from scripts.lib.retired_providers import is_retired

    row = registry_domain(gap.domain)
    dom = canonical_domain(gap.domain)
    chain = [str(p) for p in (row.get("backup") or [])]
    if not chain:
        return VectorResult("no_answer", detail="registry declares no backup for this domain")
    tried: list[str] = []
    for provider in chain:
        if is_retired(provider):
            return VectorResult("retired_skipped", provider=provider,
                                detail=f"{provider} is retired in the registry; refused up front")
        fn = BACKUP_FETCHERS.get((dom, provider))
        if fn is None:
            tried.append(f"{provider}:no_adapter")
            continue
        if not ctx.is_live():
            return VectorResult("no_answer", provider=provider,
                                detail=f"dry_run: would fetch from {provider} ({FLAG_LIVE} unset)")
        try:
            res = fn(gap, ctx)
        except Exception as exc:  # noqa: BLE001 -- fail-soft; the receipt carries it
            return VectorResult("error", provider=provider, detail=f"{type(exc).__name__}:{exc}")
        if res.outcome == "answered":
            return res
        tried.append(f"{provider}:{res.outcome}")
    return VectorResult("no_answer", detail="backup chain exhausted: " + ", ".join(tried))


def _v_governed_search(gap: DataGap, entry: dict[str, Any], ctx: Context) -> VectorResult:
    """Through brave_router only. The router owns the budget, the cache and (Phase
    5) the spill to SearXNG; this vector never touches a search host itself."""
    from scripts.lib import brave_router
    from scripts.lib.retired_providers import is_retired

    if is_retired(brave_router.PROVIDER):
        return VectorResult("retired_skipped", provider=brave_router.PROVIDER, detail="search provider retired")
    if not brave_router.router_enabled():
        return VectorResult("no_answer", provider=brave_router.PROVIDER,
                            detail=f"router_disabled: {brave_router.FLAG_ENABLED} unset; no call, no side effect")
    if not ctx.is_live():
        return VectorResult("no_answer", provider=brave_router.PROVIDER,
                            detail=f"dry_run: would search {gap.question!r} ({FLAG_LIVE} unset)")
    kind = "news" if canonical_domain(gap.domain) == "catalyst_news" else "web"
    try:
        resp = brave_router.search(gap.question, kind=kind, count=5, caller="gap_resolver",
                                   purpose=f"gap:{canonical_domain(gap.domain)}",
                                   idempotency_key=f"gap:{gap.gap_id}:{ctx.now().date().isoformat()}")
    except brave_router.BudgetRefused as exc:
        return VectorResult("budget_denied", provider=brave_router.PROVIDER, detail=f"router refused: {exc}")
    except Exception as exc:  # noqa: BLE001
        return VectorResult("error", provider=brave_router.PROVIDER, detail=f"{type(exc).__name__}:{exc}")
    if not resp.ok:
        outcome = "budget_denied" if "EXHAUST" in str(resp.reason).upper() or "429" in str(resp.reason) else "no_answer"
        return VectorResult(outcome, provider=brave_router.PROVIDER, detail=f"router: {resp.reason}")
    hits = list(resp.results or [])
    if not hits:
        return VectorResult("no_answer", provider=brave_router.PROVIDER, detail="router ok, zero results")
    # RouterResponse carries no ``spilled_to`` — the spill target is ``provider``
    # ("Which provider actually answered — brave or the backup that took the
    # spill"). The old getattr therefore defaulted to None on EVERY response, so
    # a spilled answer was recorded as brave and the gap receipts disagreed with
    # the budget ledger about who answered. Only the RECEIPT has spilled_to.
    provider = str(getattr(resp, "provider", None) or brave_router.PROVIDER)
    return VectorResult("partial", provider=provider, as_of=_iso(ctx.now()),
                        detail=f"{len(hits)} results{' (cache)' if resp.cache_hit else ''}",
                        evidence={"search_results": hits[:5], "search_provider": provider})


def _v_hermes_research(gap: DataGap, entry: dict[str, Any], ctx: Context) -> VectorResult:
    """Queue Hermes through the ONE existing entry. Slow: the answer arrives via
    the pending machinery, so this returns queued + an ETA, never an answer."""
    enqueue = ctx.hermes_enqueue
    if enqueue is None:
        # Prefer whichever copy of the desk module is already loaded, so a
        # caller's monkeypatch (or hot-reload) is honoured.
        mod = sys.modules.get("lib.cio_operator_desk_loop") or sys.modules.get("scripts.lib.cio_operator_desk_loop")
        if mod is None:
            try:
                from scripts.lib import cio_operator_desk_loop as mod  # type: ignore
            except ImportError:  # pragma: no cover
                from lib import cio_operator_desk_loop as mod  # type: ignore
        enqueue = getattr(mod, "_enqueue_hermes_research")
    out = enqueue(
        symbols=list(gap.symbols) or [gap.subject or "BOOK"],
        chat_id=str(ctx.chat_id or gap.requester),
        pending_id=str(ctx.pending_id or gap.gap_id),
        operator_text=ctx.operator_text or gap.question,
    )
    if not isinstance(out, dict) or not out.get("ok"):
        return VectorResult("no_answer", provider="hermes",
                            detail=f"enqueue refused: {(out or {}).get('error') or (out or {}).get('emit')}")
    return VectorResult("queued", provider="hermes", eta_seconds=int(entry.get("expected_seconds") or 1800),
                        detail=f"plan_id={out.get('plan_id')} emitted={out.get('emitted')}")


def _curation_prompt(gap: DataGap, evidence: dict[str, Any]) -> str:
    return (
        "You are a curator, not a source. Summarise ONLY the evidence below as it "
        "bears on the question. Do not add facts, numbers, dates or names that are "
        "not in the evidence. If the evidence does not answer the question, say so "
        "in one sentence.\n\n"
        f"QUESTION: {gap.question}\nSUBJECT: {gap.subject}\nDOMAIN: {canonical_domain(gap.domain)}\n\n"
        "EVIDENCE (JSON):\n" + json.dumps(evidence, default=str)[:6000]
    )


def _curate_deepseek(prompt: str) -> tuple[Optional[str], Optional[str]]:
    from scripts.lib.deepseek_client import chat

    resp = chat(policy="FAST", prompt=prompt, max_tokens=400, timeout=45.0,
                source_service="gap_resolver", source_lane="llm_curation")
    if not getattr(resp, "ok", False) or not getattr(resp, "content", None):
        return None, None
    model = getattr(resp, "returned_model", None) or getattr(resp, "requested_model_id", None)
    return str(resp.content).strip(), str(model or "deepseek")


def _curate_ollama(prompt: str) -> tuple[Optional[str], Optional[str]]:
    import urllib.request

    scripts = PROJECT_ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from local_llm_config import get_local_llm_base_url, get_local_llm_model  # type: ignore

    model = get_local_llm_model()
    payload = json.dumps({"model": model, "stream": False, "think": False,
                          "messages": [{"role": "user", "content": prompt}],
                          "options": {"temperature": 0.1, "num_predict": 400}}).encode()
    req = urllib.request.Request(f"{get_local_llm_base_url().rstrip('/')}/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 -- local host only
        data = json.loads(resp.read())
    text = ((data.get("message") or {}).get("content") or "").strip()
    return (text or None), f"ollama:{model}"


def _v_llm_curation(gap: DataGap, entry: dict[str, Any], ctx: Context) -> VectorResult:
    """Curate what earlier vectors gathered. No evidence → no model call, full stop.
    DeepSeek in its off-peak/bulk window; Ollama otherwise. The output is
    labelled with the model that produced it and is never a fact source."""
    evidence = dict(gap.evidence or {})
    if not evidence:
        return VectorResult("no_answer", detail="no_evidence_to_curate: llm_curation never invents; nothing gathered")
    if not ctx.is_live():
        return VectorResult("no_answer", detail=f"dry_run: would curate {len(evidence)} evidence keys ({FLAG_LIVE} unset)")
    from scripts.lib.deepseek_offpeak import is_bulk_deepseek_window

    prompt = _curation_prompt(gap, evidence)
    try:
        if is_bulk_deepseek_window(ctx.now()):
            text, model = _curate_deepseek(prompt)
            provider = "deepseek"
        else:
            text, model = _curate_ollama(prompt)
            provider = "ollama"
    except Exception as exc:  # noqa: BLE001
        return VectorResult("error", provider="llm", detail=f"{type(exc).__name__}:{exc}")
    if not text:
        return VectorResult("no_answer", provider=provider, model=model, detail="model returned nothing")
    answer = {
        "source": "llm_curation",
        "model": model,
        "text": text,
        "curated_from": sorted(evidence.keys()),
        "as_of": _iso(ctx.now()),
        "note": "curation of gathered evidence; not a fact source",
    }
    return VectorResult("partial", answer=answer, as_of=answer["as_of"], provider=provider, model=model,
                        detail=f"curated {len(evidence)} evidence keys")


def _v_operator_ask(gap: DataGap, entry: dict[str, Any], ctx: Context) -> VectorResult:
    """ONE question to the operator with an ETA. Sends only when a send_fn is
    injected AND live; the desk path embeds the question in its own reply."""
    eta = int(entry.get("expected_seconds") or 7200)
    mins = max(1, int(round(eta / 60.0)))
    question = (
        f"I could not find {canonical_domain(gap.domain).replace('_', ' ')} for "
        f"{gap.subject or 'the book'} through any declared source. "
        f"Do you have a source I should use, or should I keep trying for ≈ {mins} min?"
    )
    detail = "question embedded in caller's reply"
    if ctx.send_fn is not None and ctx.chat_id:
        if not ctx.is_live():
            detail = f"dry_run: would send operator question ({FLAG_LIVE} unset)"
        else:
            try:
                sent = ctx.send_fn(ctx.chat_id, question + f"\n{AUTHORITY}", None)
                detail = "sent" if (sent or {}).get("ok", True) else f"send_failed:{(sent or {}).get('error')}"
            except Exception as exc:  # noqa: BLE001
                return VectorResult("error", provider="operator", detail=f"{type(exc).__name__}:{exc}",
                                    operator_question=question)
    return VectorResult("queued", provider="operator", eta_seconds=eta, detail=detail, operator_question=question)


DEFAULT_VECTORS: dict[str, Callable[[DataGap, dict[str, Any], Context], VectorResult]] = {
    "refresh_producer": _v_refresh_producer,
    "backup_provider": _v_backup_provider,
    "governed_search": _v_governed_search,
    "hermes_research": _v_hermes_research,
    "llm_curation": _v_llm_curation,
    "operator_ask": _v_operator_ask,
}


# ── the resolver ─────────────────────────────────────────────────────────────


def _age_hours(as_of: Optional[str], now: datetime) -> Optional[float]:
    if not as_of:
        return None
    try:
        dt = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((now - dt).total_seconds() / 3600.0, 3)
    except Exception:
        return None


def resolve(
    gap: DataGap,
    *,
    chain: Optional[list[dict[str, Any]]] = None,
    vectors: Optional[dict[str, Callable[..., VectorResult]]] = None,
    ctx: Optional[Context] = None,
    authority: Optional[dict[str, Any]] = None,
) -> Resolution:
    """Run the declared vectors in order until one answers. Receipt every attempt.

    * ``chain`` overrides the registry/default chain (tests); it is still normalised.
    * ``vectors`` overrides vector implementations by name (tests inject fakes).
    * ``ctx`` carries the clock, receipts path, arm flag and caller hooks.
    """
    ctx = ctx or Context()
    _register_gap_on_spine(gap)
    impls = dict(DEFAULT_VECTORS)
    impls.update(vectors or {})
    from scripts.lib.free_first_refresh import reject_paid_transition
    from scripts.lib.retired_providers import is_retired

    row = registry_domain(gap.domain, authority=authority)
    plan = normalise_chain(chain) if chain is not None else load_on_gap(gap.domain, authority=authority)
    res = Resolution(gap_id=gap.gap_id, domain=canonical_domain(gap.domain), subject=gap.subject,
                     no_coverage_behaviour=row.get("no_coverage"))
    gathered: dict[str, Any] = dict(gap.evidence or {})
    receipts_rows = read_receipts(ctx.receipts)
    entered_paid = False
    queued: Optional[Attempt] = None

    for entry in plan:
        vector = entry["vector"]
        cost = entry["cost_class"]
        started = ctx.now()
        attempt = Attempt(vector=vector, outcome="no_answer", cost_class=cost, started=_iso(started) or "")

        # The free_first rail: a PLANNED gap may not enter a paid class on its
        # own. Only an explicit operator grant (FLAG_PAID) moves the state to
        # PAID_AUTHORIZED; without it the rail raises and the slot is denied,
        # with the rail's own words in the receipt.
        if cost == "paid" and not entered_paid:
            granted = paid_authorized(ctx.env)
            try:
                reject_paid_transition("PAID_AUTHORIZED" if granted else "PLANNED", True,
                                       mode="PAID_AUTHORIZED" if granted else "FREE_FIRST_ONLY")
                entered_paid = True
            except RuntimeError as exc:
                attempt.outcome, attempt.detail = "budget_denied", str(exc)
                _finish(attempt, ctx, res, receipts_rows, gap)
                continue

        # Retired provider named for this vector? Refuse before spending anything.
        pinned = _pinned_provider(vector, row)
        if pinned and is_retired(pinned):
            attempt.outcome, attempt.provider = "retired_skipped", pinned
            attempt.detail = f"{pinned} is retired in the registry; refused up front"
            _finish(attempt, ctx, res, receipts_rows, gap)
            continue

        # Budget: per vector per day, counted from receipts. A vector in
        # PER_GOAL_BUDGET_VECTORS is counted against THIS goal's own attempts,
        # so one goal's question cannot consume another goal's escalation slot.
        # An empty goal_id is a bucket in its own right, NOT a fall-back to the
        # global count: counting globally here would let goal-scoped work starve
        # the ungoaled slot, which is the same defect wearing a different hat.
        scope = gap.goal_id if vector in PER_GOAL_BUDGET_VECTORS else None
        used = attempts_today(vector, now=started, rows=receipts_rows, goal_id=scope)
        if used >= int(entry.get("max_per_day") or 0):
            attempt.outcome = "budget_denied"
            attempt.detail = f"{used}/{entry.get('max_per_day')} attempts today"
            _finish(attempt, ctx, res, receipts_rows, gap)
            continue

        impl = impls.get(vector)
        if impl is None:
            attempt.outcome, attempt.detail = "error", "no implementation"
            _finish(attempt, ctx, res, receipts_rows, gap)
            continue

        gap_for_vector = DataGap(**{**asdict(gap), "evidence": dict(gathered)})
        try:
            out = impl(gap_for_vector, entry, ctx)
        except Exception as exc:  # noqa: BLE001 -- one vector failing must not kill the chain
            out = VectorResult("error", detail=f"{type(exc).__name__}:{exc}")
        if out.outcome not in OUTCOMES:
            out.outcome = "error"
            out.detail = f"unknown outcome from {vector}: {out.detail}"

        attempt.outcome = out.outcome
        attempt.provider = out.provider or pinned
        attempt.model = out.model
        attempt.as_of = out.as_of
        attempt.eta_seconds = out.eta_seconds
        attempt.detail = out.detail
        _finish(attempt, ctx, res, receipts_rows, gap)

        if out.evidence:
            gathered.update(out.evidence)
        if out.operator_question:
            res.operator_question = out.operator_question

        if out.outcome == "answered":
            res.outcome, res.answered, res.answer = "answered", True, out.answer
            res.as_of = out.as_of
            res.age_hours = _age_hours(out.as_of, ctx.now())
            res.vector, res.model = vector, out.model
            res.source = f"llm_curation:{out.model}" if vector == "llm_curation" else f"{vector}:{out.provider or 'internal'}"
            break
        if out.outcome == "partial":
            # Evidence, not an answer; keep going but remember it for the caller.
            res.outcome = "partial"
            if out.answer is not None:
                res.answer, res.as_of, res.model = out.answer, out.as_of, out.model
                res.source = f"llm_curation:{out.model}" if vector == "llm_curation" else f"{vector}:{out.provider or 'internal'}"
                res.vector = vector
            continue
        if out.outcome == "queued" and queued is None:
            queued = attempt
            if vector == "operator_ask":
                # Last vector by construction; nothing runs after it.
                break
            # A slow vector accepted the request. Keep walking the cheaper
            # remaining vectors (curation of what we have), but the ETA stands.
            continue

    if not res.answered:
        if queued is not None:
            res.outcome = "queued" if res.outcome != "partial" else "partial"
            res.vector = res.vector or queued.vector
            res.eta_seconds = queued.eta_seconds
            res.source = res.source or f"{queued.vector}:{queued.provider or 'internal'}"
        elif res.outcome != "partial":
            res.outcome = "no_coverage"
    res.evidence = gathered

    # Phase-2 quality escalate: thin search/answer → one free SearXNG climb.
    # Off unless RESEARCH_QUALITY_ESCALATE=1 (env) or host file
    # ~/.config/tradeai/research_quality_escalate. Reuses score_lap; never invents a rubric.
    if res.outcome in ("partial", "answered"):
        try:
            from scripts.lib import research_quality_escalate as rqe

            # Prefer explicit env value; when the key is absent, allow host-file arming.
            # Under pytest with no Context.env, stay hermetic — never consult the host file
            # (otherwise a live ~/.config/tradeai/research_quality_escalate arms every suite).
            _flag_env = ctx.env
            if _flag_env is not None and rqe.FLAG not in _flag_env:
                _flag_env = None
            if _flag_env is None and os.environ.get("PYTEST_CURRENT_TEST"):
                _flag_env = {}
            if rqe.enabled(_flag_env):
                esc = rqe.maybe_escalate(
                    question=gap.question,
                    symbol=(list(gap.symbols)[0] if gap.symbols else gap.subject) or None,
                    search_hits=list((gathered or {}).get("search_results") or []),
                    answer=res.answer,
                    env=_flag_env,
                    dry_run=not ctx.is_live(),
                )
                gathered = dict(gathered or {})
                gathered["quality_escalate"] = esc
                if esc.get("escalated") and esc.get("hits"):
                    prior = list(gathered.get("search_results") or [])
                    gathered["search_results"] = prior + list(esc["hits"])
                    if not res.answered:
                        res.outcome = "partial"
                        res.source = res.source or "quality_escalate:searxng"
                    # Durable receipt so "thin_answer" climbs are measurable.
                    _append_receipt(
                        ctx.receipts,
                        {
                            "schema": RECEIPT_SCHEMA,
                            "authority": AUTHORITY,
                            "gap_id": gap.gap_id,
                            "goal_id": gap.goal_id,
                            "domain": canonical_domain(gap.domain),
                            "subject": gap.subject,
                            "question": gap.question[:300],
                            "vector": "quality_escalate",
                            "provider": "searxng",
                            "outcome": "partial",
                            "detail": esc.get("detail") or rqe.REASON,
                            "reason": rqe.REASON,
                            "started": esc.get("as_of") or "",
                            "finished": esc.get("as_of") or "",
                        },
                    )
                    res.attempts.append(
                        {
                            "vector": "quality_escalate",
                            "provider": "searxng",
                            "outcome": "partial",
                            "detail": esc.get("detail"),
                        }
                    )
                elif esc.get("enabled") and esc.get("thin"):
                    # Thin + armed but no climb (dry_run / no hits) still leaves
                    # a receipt — PARTIAL-quality-escalate-organic was stuck at
                    # zero because only escalated+hits wrote, while the cron
                    # often runs dry_run without GAP_RESOLVER_LIVE.
                    _append_receipt(
                        ctx.receipts,
                        {
                            "schema": RECEIPT_SCHEMA,
                            "authority": AUTHORITY,
                            "gap_id": gap.gap_id,
                            "goal_id": gap.goal_id,
                            "domain": canonical_domain(gap.domain),
                            "subject": gap.subject,
                            "question": gap.question[:300],
                            "vector": "quality_escalate",
                            "provider": "searxng",
                            "outcome": (
                                "dry_run"
                                if esc.get("dry_run") or esc.get("would_escalate")
                                else "partial"
                            ),
                            "detail": esc.get("detail") or rqe.REASON,
                            "reason": rqe.REASON,
                            "would_escalate": bool(esc.get("would_escalate")),
                            "started": esc.get("as_of") or "",
                            "finished": esc.get("as_of") or "",
                        },
                    )
                    res.attempts.append(
                        {
                            "vector": "quality_escalate",
                            "provider": "searxng",
                            "outcome": "dry_run" if esc.get("dry_run") else "partial",
                            "detail": esc.get("detail"),
                        }
                    )
                res.evidence = gathered
        except Exception:  # noqa: BLE001 — escalate must never break resolve
            pass

    return res


def _register_gap_on_spine(gap: DataGap) -> Optional[str]:
    """Register `DataGap.gap_id` under source_table `gap_resolver_gaps`.

    The id is untouched -- it stays the uuid5 over `domain|subject|question`
    this dataclass has always minted. What changes is that the receipts keyed on
    it can now be joined to the goal that raised the gap and to the pending
    reply that answers it, which no id in this file could do.

    `BOOK` and other non-entity subjects resolve to nothing and are skipped:
    `cio_subject_guid` calls that NOT_APPLICABLE, not unknown.

    Fail-safe: a resolution must never fail because a link could not be written.
    """
    try:
        from scripts.lib.cio_identity_spine import register_symbol_on_spine

        return register_symbol_on_spine("gap_resolver_gaps", gap.gap_id, gap.subject)
    except Exception:  # noqa: BLE001
        return None


def _pinned_provider(vector: str, row: dict[str, Any]) -> Optional[str]:
    """The provider a vector is bound to by the registry, when there is one."""
    if vector == "refresh_producer":
        p = row.get("primary_provider")
        return None if not p or str(p).startswith("internal") or p == "none" else str(p)
    if vector == "governed_search":
        return "brave"
    return None


def _finish(attempt: Attempt, ctx: Context, res: Resolution, rows: list[dict[str, Any]], gap: DataGap) -> None:
    attempt.finished = _iso(ctx.now()) or ""
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "authority": AUTHORITY,
        "gap_id": gap.gap_id,
        # The join that makes a per-goal budget countable at all: without this
        # on the receipt there is no way to ask "how many times have we asked
        # the operator about THIS goal today".
        "goal_id": gap.goal_id,
        "domain": canonical_domain(gap.domain),
        "subject": gap.subject,
        "question": gap.question[:300],
        "why": gap.why,
        "requester": gap.requester,
        **asdict(attempt),
    }
    _append_receipt(ctx.receipts, receipt)
    rows.append(receipt)
    res.attempts.append(asdict(attempt))


__all__ = [
    "AUTHORITY", "SCHEMA", "RECEIPT_SCHEMA", "RECEIPTS_PATH", "FLAG_LIVE", "FLAG_PAID", "paid_authorized",
    "VECTORS", "COST_CLASSES", "OUTCOMES", "WHYS", "DEFAULT_ON_GAP", "DESK_DOMAIN_MAP",
    "PER_GOAL_BUDGET_VECTORS",
    "DataGap", "Resolution", "VectorResult", "Context", "Attempt",
    "resolve", "load_on_gap", "normalise_chain", "registry_domain", "canonical_domain",
    "read_receipts", "attempts_today", "live_armed", "BACKUP_FETCHERS", "DEFAULT_VECTORS",
    "default_receipts_path",
]
