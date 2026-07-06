"""universe.py — options underlying universe + strategy registry loaders (Stage 1).

Loads and validates config/options_universe.yaml (tiered underlying universe)
and config/options_strategy_registry.yaml (per-strategy permission registry)
for the paper-only options strategy scanner.

Design rules:
  * FAIL-CLOSED loading: a missing/corrupt/invalid yaml raises
    UniverseConfigError / RegistryConfigError — callers refuse to scan rather
    than scanning a guessed universe.
  * FAIL-CLOSED live policy: load_strategy_registry raises if ANY strategy
    carries live_enabled/live_exception_allowed true unless env
    TRADE_AI_OPTIONS_LIVE_POLICY == "explicit" (never set in this deployment).
  * Dynamic tier resolvers are DEFENSIVE: holdings.json / DB / discovery
    outages degrade that tier to [] — they never raise out of resolve_universe
    and never fabricate symbols.
  * ADVISORY-ONLY: no broker submit / order / 2FA imports (AST test-enforced,
    tests/test_options_universe.py).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

UNIVERSE_CONFIG_PATH = PROJECT_ROOT / "config" / "options_universe.yaml"
REGISTRY_CONFIG_PATH = PROJECT_ROOT / "config" / "options_strategy_registry.yaml"

LIVE_POLICY_ENV = "TRADE_AI_OPTIONS_LIVE_POLICY"
LIVE_POLICY_EXPLICIT = "explicit"

KNOWN_STRATEGIES = frozenset({
    "deep_itm_call", "covered_call", "cash_secured_put",
    "protective_put", "credit_spread",
})
REQUIRED_TIERS = (
    "holdings", "watchlist_buy_strong_buy", "liquid_options_core",
    "sector_etfs", "discovery_missing_exposure", "strategy_specific",
    "operator_added",
)
KNOWN_RESOLVERS = frozenset({"holdings_json", "watchlist_verdicts",
                             "hermes_gap_candidates"})
REGISTRY_STATUSES = frozenset({"RESEARCH_ONLY", "MODELED", "TESTING_PAPER",
                               "VALIDATED", "PAUSED", "KILLED",
                               "BLOCKED_INITIAL"})
# BLOCKED_INITIAL (EARNINGS-SPREADS Stage 1): a registry row the loader accepts
# as VALID but that must stay UNSCANNABLE — load_strategy_registry enforces
# paper_enabled=false + alpaca_paper_enabled=false on such rows (fail-closed).
# Enabling requires an explicit status change in the registry yaml.
_UNSCANNABLE_STATUSES = frozenset({"BLOCKED_INITIAL"})

# scanner --universe selector → tiers scanned (None = all, in precedence order)
UNIVERSE_SELECTORS: Dict[str, Optional[List[str]]] = {
    "holdings_watchlist": ["holdings", "watchlist_buy_strong_buy"],
    "liquid_core": ["liquid_options_core", "sector_etfs"],
    "discovery": ["discovery_missing_exposure"],
    "all": None,
}

GAP_TYPES_FOR_EXPOSURE = ("MISSING_SECTOR", "MISSING_COMPANY")
_OPEN_GAP_EXCLUDED_STATUSES = ("REJECTED", "MERGED_DUPLICATE", "BLOCKED",
                               "ARCHIVED_COLD")
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

# Runtime state dir override (worktrees / tests) — same env the scanner honors.
def _state_dir() -> Path:
    return Path(os.getenv("OPTIONS_PIPELINE_STATE_DIR",
                          str(PROJECT_ROOT / "data" / "portfolios" / "state")))


class UniverseConfigError(Exception):
    """options_universe.yaml missing/corrupt/invalid — fail closed."""


class RegistryConfigError(Exception):
    """options_strategy_registry.yaml missing/corrupt/invalid — fail closed."""


class LivePolicyViolation(RegistryConfigError):
    """A registry row claims live permission without the explicit policy env."""


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x


# ── universe config ──────────────────────────────────────────────────────────

def _validate_symbol_entry(tier: str, entry: Any, seen: set) -> None:
    if not isinstance(entry, dict):
        raise UniverseConfigError(f"tier {tier}: symbol entry must be a mapping, got {type(entry).__name__}")
    sym = entry.get("symbol")
    if not isinstance(sym, str) or not _SYMBOL_RE.match(sym.strip().upper()):
        raise UniverseConfigError(f"tier {tier}: invalid symbol {sym!r}")
    sym = sym.strip().upper()
    if sym in seen:
        raise UniverseConfigError(f"tier {tier}: duplicate symbol {sym}")
    seen.add(sym)
    if not str(entry.get("reason_included") or "").strip():
        raise UniverseConfigError(f"tier {tier}: {sym} missing reason_included")
    allow = entry.get("strategy_allowlist")
    if not isinstance(allow, list) or not allow:
        raise UniverseConfigError(f"tier {tier}: {sym} missing strategy_allowlist")
    unknown = set(allow) - KNOWN_STRATEGIES
    if unknown:
        raise UniverseConfigError(f"tier {tier}: {sym} unknown strategies in allowlist: {sorted(unknown)}")
    if not isinstance(entry.get("enabled"), bool):
        raise UniverseConfigError(f"tier {tier}: {sym} 'enabled' must be a bool")


def load_universe_config(path: Optional[Path] = None) -> dict:
    """Load + validate config/options_universe.yaml. Raises UniverseConfigError."""
    p = Path(path) if path else UNIVERSE_CONFIG_PATH
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UniverseConfigError(f"universe config missing: {p}")
    except yaml.YAMLError as e:
        raise UniverseConfigError(f"universe config unparsable: {e}")
    if not isinstance(raw, dict):
        raise UniverseConfigError("universe config root must be a mapping")

    tiers = raw.get("tiers")
    if not isinstance(tiers, dict):
        raise UniverseConfigError("universe config missing 'tiers' mapping")
    missing = [t for t in REQUIRED_TIERS if t not in tiers]
    if missing:
        raise UniverseConfigError(f"universe config missing required tiers: {missing}")

    precedence = raw.get("tier_precedence")
    if (not isinstance(precedence, list)
            or sorted(precedence) != sorted(tiers.keys())):
        raise UniverseConfigError(
            "tier_precedence must list every tier exactly once "
            f"(got {precedence!r} for tiers {sorted(tiers)})")

    for name, tier in tiers.items():
        if not isinstance(tier, dict):
            raise UniverseConfigError(f"tier {name} must be a mapping")
        if not isinstance(tier.get("enabled"), bool):
            raise UniverseConfigError(f"tier {name}: 'enabled' must be a bool")
        dynamic = tier.get("dynamic")
        if not isinstance(dynamic, bool):
            raise UniverseConfigError(f"tier {name}: 'dynamic' must be a bool")
        if dynamic:
            if tier.get("resolver") not in KNOWN_RESOLVERS:
                raise UniverseConfigError(
                    f"tier {name}: dynamic tier needs a known resolver "
                    f"(got {tier.get('resolver')!r})")
            if "symbols" in tier:
                raise UniverseConfigError(
                    f"tier {name}: dynamic tier must not carry a static symbols list")
            allow = tier.get("strategy_allowlist")
            if not isinstance(allow, list) or set(allow) - KNOWN_STRATEGIES:
                raise UniverseConfigError(f"tier {name}: invalid tier strategy_allowlist")
        else:
            symbols = tier.get("symbols")
            if not isinstance(symbols, list):
                raise UniverseConfigError(f"tier {name}: static tier needs a symbols list")
            seen: set = set()
            for entry in symbols:
                _validate_symbol_entry(name, entry, seen)
    return raw


# ── dynamic tier resolvers (defensive — outage ⇒ [], never raise) ───────────

def _load_holdings_symbols() -> Dict[str, float]:
    """{symbol: shares} for non-cash equity holdings (holdings.json snapshot)."""
    out: Dict[str, float] = {}
    try:
        raw = json.loads((_state_dir() / "holdings.json").read_text(encoding="utf-8"))
    except Exception:
        return out
    for h in raw.get("holdings") or []:
        sym = (h.get("symbol") or "").upper()
        if not sym or h.get("is_cash") or not sym.isalpha() or len(sym) > 6:
            continue
        if sym in ("CASH", "SPAXX", "FCASH", "CORE"):
            continue
        shares = _f(h.get("shares"))
        if shares > 0:
            out[sym] = out.get(sym, 0.0) + shares
    return out


def _fetch_watchlist_buy_rows() -> List[dict]:
    """Watchlist buy/strong_buy names — read-only DB query; [] on any failure."""
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return []
        rows = _execute(
            """SELECT wi.symbol,
                      rc.latest_recommendation AS card_rec,
                      fs.recommendation AS synth_rec,
                      wi.hermes_composite_score
               FROM watchlist_items wi
               LEFT JOIN watchlist_research_cards rc ON rc.symbol = wi.symbol
               LEFT JOIN watchlist_final_synthesis fs ON UPPER(fs.symbol) = UPPER(wi.symbol)
               WHERE wi.status <> 'removed'
                 AND wi.symbol ~ '^[A-Z]{1,5}$'
               ORDER BY wi.hermes_composite_score DESC NULLS LAST, wi.symbol""",
            fetch="all",
        ) or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def _normalize_verdict(raw: Any) -> Optional[str]:
    if not raw:
        return None
    r = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if r == "strongbuy":
        r = "strong_buy"
    return r if r in ("buy", "strong_buy") else None


def _fetch_open_gap_rows() -> List[dict]:
    """Open GAP_CANDIDATE rows (MISSING_SECTOR / MISSING_COMPANY) — [] on failure."""
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return []
        rows = _execute(
            """SELECT id, label, status, seed_symbols, meta_json
               FROM hermes_discovery_candidates
               WHERE candidate_type = 'GAP_CANDIDATE'
                 AND status NOT IN %s
                 AND meta_json->>'gap_type' IN %s
               ORDER BY last_seen_at DESC NULLS LAST, id DESC
               LIMIT 100""",
            (_OPEN_GAP_EXCLUDED_STATUSES, GAP_TYPES_FOR_EXPOSURE),
            fetch="all",
        ) or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def _validate_gap_ticker(symbol: str) -> bool:
    """True only if the discovery ticker survives full validation (fail-closed)."""
    try:
        from lib.hermes_discovery.symbol_validation import VERDICT_VALID, validate_ticker
        return (validate_ticker(symbol) or {}).get("verdict") == VERDICT_VALID
    except Exception:
        return False  # validator unavailable → discovery names do NOT pass


def _gap_row_ticker(row: dict) -> Optional[str]:
    """Extract the validated ticker a gap row carries (seed_symbols / meta), or None."""
    meta = row.get("meta_json")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    meta = meta if isinstance(meta, dict) else {}
    candidates: List[str] = []
    for s in (row.get("seed_symbols") or []):
        candidates.append(str(s))
    tv = meta.get("ticker_validation") or {}
    if tv.get("symbol"):
        candidates.append(str(tv["symbol"]))
    for c in candidates:
        sym = c.strip().upper()
        if _SYMBOL_RE.match(sym):
            return sym
    return None


def _resolve_dynamic_tier(
    name: str,
    tier: dict,
    default_conviction: float,
    *,
    holdings: Optional[Dict[str, float]] = None,
    watchlist_rows: Optional[List[dict]] = None,
    gap_rows: Optional[List[dict]] = None,
    gap_validator: Optional[Callable[[str], bool]] = None,
) -> List[dict]:
    """Resolve one dynamic tier to entry dicts. Defensive: bad inputs ⇒ []."""
    resolver = tier.get("resolver")
    base = {
        "source_tier": name,
        "reason_included": tier.get("reason_included") or f"dynamic tier {name}",
        "strategy_allowlist": list(tier.get("strategy_allowlist") or []),
        "liquidity_expectation": tier.get("liquidity_expectation"),
    }
    out: List[dict] = []
    try:
        if resolver == "holdings_json":
            held = _load_holdings_symbols() if holdings is None else holdings
            for sym, shares in sorted(held.items()):
                out.append(dict(base, symbol=sym, held_shares=shares,
                                conviction=max(default_conviction, 0.60),
                                conviction_source="current_holding", verdict=None,
                                rank_score=0.0))
        elif resolver == "watchlist_verdicts":
            rows = _fetch_watchlist_buy_rows() if watchlist_rows is None else watchlist_rows
            for row in rows:
                sym = (row.get("symbol") or "").strip().upper()
                verdict = (_normalize_verdict(row.get("card_rec"))
                           or _normalize_verdict(row.get("synth_rec")))
                if not sym or not _SYMBOL_RE.match(sym) or verdict is None:
                    continue
                conviction = 0.85 if verdict == "strong_buy" else 0.70
                out.append(dict(base, symbol=sym, held_shares=None,
                                conviction=conviction,
                                conviction_source=f"watchlist_{verdict}",
                                verdict=verdict,
                                rank_score=_f(row.get("hermes_composite_score"))))
        elif resolver == "hermes_gap_candidates":
            rows = _fetch_open_gap_rows() if gap_rows is None else gap_rows
            validate = gap_validator or _validate_gap_ticker
            for row in rows:
                sym = _gap_row_ticker(row)
                if not sym or not validate(sym):
                    continue
                gap_meta = row.get("meta_json")
                if isinstance(gap_meta, str):
                    try:
                        gap_meta = json.loads(gap_meta)
                    except Exception:
                        gap_meta = {}
                gap_type = (gap_meta or {}).get("gap_type") if isinstance(gap_meta, dict) else None
                out.append(dict(
                    base, symbol=sym, held_shares=None,
                    conviction=default_conviction,
                    conviction_source=f"discovery_gap_{(gap_type or 'unknown').lower()}",
                    verdict=None, rank_score=0.0,
                    reason_included=(f"{base['reason_included']} "
                                     f"(gap #{row.get('id')}: {row.get('label')})"),
                    discovery_gap={"candidate_id": row.get("id"),
                                   "gap_type": gap_type,
                                   "label": row.get("label"),
                                   "status": row.get("status")},
                ))
    except Exception:
        return []  # defensive: a broken resolver degrades to an empty tier
    return out


def _static_tier_entries(name: str, tier: dict, default_conviction: float) -> List[dict]:
    out: List[dict] = []
    for entry in tier.get("symbols") or []:
        if not entry.get("enabled", True):
            continue
        out.append({
            "symbol": str(entry["symbol"]).strip().upper(),
            "source_tier": name,
            "reason_included": entry.get("reason_included"),
            "strategy_allowlist": list(entry.get("strategy_allowlist") or []),
            "liquidity_expectation": entry.get("liquidity_expectation"),
            "conviction": _f(entry.get("conviction"), default_conviction),
            "conviction_source": f"universe_{name}",
            "verdict": None,
            "held_shares": None,
            "rank_score": 0.0,
        })
    return out


def resolve_universe(
    tier_selector: str = "all",
    *,
    config: Optional[dict] = None,
    holdings: Optional[Dict[str, float]] = None,
    watchlist_rows: Optional[List[dict]] = None,
    gap_rows: Optional[List[dict]] = None,
    gap_validator: Optional[Callable[[str], bool]] = None,
) -> List[dict]:
    """Resolve the selected universe tiers into a deduped, precedence-ordered list.

    tier_selector: a key of UNIVERSE_SELECTORS ('holdings_watchlist' |
    'liquid_core' | 'discovery' | 'all') or an explicit list of tier names.
    Returns [{symbol, source_tier, reason_included, strategy_allowlist,
    conviction, conviction_source, ...}] — one entry per symbol, first tier in
    precedence order wins. Injectable inputs keep dynamic resolvers testable.
    """
    cfg = config if config is not None else load_universe_config()
    tiers = cfg["tiers"]
    precedence = list(cfg.get("tier_precedence") or REQUIRED_TIERS)
    defaults = cfg.get("defaults") or {}
    default_conviction = _f(defaults.get("default_conviction"), 0.60)

    if isinstance(tier_selector, (list, tuple)):
        wanted = list(tier_selector)
    else:
        if tier_selector not in UNIVERSE_SELECTORS:
            raise UniverseConfigError(
                f"unknown universe selector {tier_selector!r} "
                f"(known: {sorted(UNIVERSE_SELECTORS)})")
        wanted = UNIVERSE_SELECTORS[tier_selector] or precedence
    unknown = set(wanted) - set(tiers)
    if unknown:
        raise UniverseConfigError(f"selector references unknown tiers: {sorted(unknown)}")

    out: Dict[str, dict] = {}
    for name in precedence:                     # precedence order = dedupe order
        if name not in wanted:
            continue
        tier = tiers[name]
        if not tier.get("enabled"):
            continue
        if tier.get("dynamic"):
            entries = _resolve_dynamic_tier(
                name, tier, default_conviction,
                holdings=holdings, watchlist_rows=watchlist_rows,
                gap_rows=gap_rows, gap_validator=gap_validator)
        else:
            entries = _static_tier_entries(name, tier, default_conviction)
        for e in entries:
            sym = e["symbol"]
            if sym not in out:                  # first (highest-precedence) tier wins
                out[sym] = e
    return list(out.values())


# ── strategy registry (fail-closed live policy) ──────────────────────────────

_REGISTRY_REQUIRED_FIELDS = (
    "status", "paper_enabled", "alpaca_paper_enabled", "live_enabled",
    "live_exception_allowed", "live_exception_requires_2fa",
    "required_permission_level", "allowed_underlying_tiers",
    "liquidity_gates", "max_contracts_paper", "max_premium_paper",
)
_REGISTRY_BOOL_FIELDS = ("paper_enabled", "alpaca_paper_enabled", "live_enabled",
                         "live_exception_allowed", "live_exception_requires_2fa")


def load_strategy_registry(path: Optional[Path] = None, *, env: Optional[dict] = None) -> dict:
    """Load + validate config/options_strategy_registry.yaml (fail-closed).

    Raises LivePolicyViolation if any strategy has live_enabled or
    live_exception_allowed true while env TRADE_AI_OPTIONS_LIVE_POLICY is not
    'explicit' (it is never set — the whole stack stays paper-only).
    """
    p = Path(path) if path else REGISTRY_CONFIG_PATH
    environ = os.environ if env is None else env
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RegistryConfigError(f"strategy registry missing: {p}")
    except yaml.YAMLError as e:
        raise RegistryConfigError(f"strategy registry unparsable: {e}")
    if not isinstance(raw, dict) or not isinstance(raw.get("strategies"), dict) \
            or not raw["strategies"]:
        raise RegistryConfigError("strategy registry needs a non-empty 'strategies' mapping")

    live_ok = environ.get(LIVE_POLICY_ENV) == LIVE_POLICY_EXPLICIT
    for sid, row in raw["strategies"].items():
        if not isinstance(row, dict):
            raise RegistryConfigError(f"registry {sid}: entry must be a mapping")
        missing = [k for k in _REGISTRY_REQUIRED_FIELDS if k not in row]
        if missing:
            raise RegistryConfigError(f"registry {sid}: missing fields {missing}")
        for k in _REGISTRY_BOOL_FIELDS:
            if not isinstance(row[k], bool):
                raise RegistryConfigError(f"registry {sid}: {k} must be a bool")
        if row.get("status") not in REGISTRY_STATUSES:
            raise RegistryConfigError(
                f"registry {sid}: unknown status {row.get('status')!r}")
        if row.get("status") in _UNSCANNABLE_STATUSES and (
                row["paper_enabled"] or row["alpaca_paper_enabled"]):
            raise RegistryConfigError(
                f"registry {sid}: status {row['status']} requires "
                "paper_enabled=false and alpaca_paper_enabled=false "
                "(valid-but-unscannable; enabling requires an explicit "
                "status change — fail-closed)")
        if row.get("required_permission_level") != "operator":
            raise RegistryConfigError(
                f"registry {sid}: required_permission_level must be 'operator'")
        bad_tiers = set(row.get("allowed_underlying_tiers") or []) - set(REQUIRED_TIERS)
        if bad_tiers:
            raise RegistryConfigError(f"registry {sid}: unknown tiers {sorted(bad_tiers)}")
        gates = row.get("liquidity_gates") or {}
        for gk in ("max_spread_pct", "min_oi", "min_volume"):
            if not isinstance(gates.get(gk), (int, float)):
                raise RegistryConfigError(f"registry {sid}: liquidity_gates.{gk} must be numeric")
        if int(row.get("max_contracts_paper") or 0) < 1:
            raise RegistryConfigError(f"registry {sid}: max_contracts_paper must be >= 1")
        if _f(row.get("max_premium_paper")) <= 0:
            raise RegistryConfigError(f"registry {sid}: max_premium_paper must be > 0")
        # ── the fail-closed live wall ──
        if (row["live_enabled"] or row["live_exception_allowed"]) and not live_ok:
            raise LivePolicyViolation(
                f"registry {sid}: live_enabled/live_exception_allowed is true but "
                f"{LIVE_POLICY_ENV} != '{LIVE_POLICY_EXPLICIT}' — refusing to load "
                "(paper-only policy, fail-closed)")
        if row["alpaca_paper_enabled"] and not row["paper_enabled"]:
            raise RegistryConfigError(
                f"registry {sid}: alpaca_paper_enabled requires paper_enabled")
    return raw


def registry_entry(strategy_id: str, *, registry: Optional[dict] = None) -> Optional[dict]:
    """The validated registry row for one strategy (None if unknown)."""
    reg = registry if registry is not None else load_strategy_registry()
    row = (reg.get("strategies") or {}).get(strategy_id)
    return dict(row) if isinstance(row, dict) else None


def strategy_allowed_for_entry(entry: dict, strategy_id: str) -> bool:
    """True if a universe entry's strategy_allowlist admits the strategy.

    Entries with no allowlist (e.g. test-injected underlyings) are allowed —
    the allowlist narrows scanning, it is not an execution gate (execution
    stays behind the desk's own paper/manual-review walls).
    """
    allow = entry.get("strategy_allowlist")
    if not allow:
        return True
    return strategy_id in allow
