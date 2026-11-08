"""Market Outlook Engine v1 (FABLE-OUTLOOK-METHODOLOGY-LQ-946 §2, §4.6; WU-2 LQ-20261107-966).

One advisement per evaluation: eleven categories, each a weighted mean of normalized indicators in [-1, +1] with a
coverage fraction; S in [-100, +100] over the measured categories only; confidence from coverage, freshness,
agreement, event risk and hit rate; the band the CIO consumes and the brief renders. Advisory only — the engine
never sizes, orders, stops or writes to a broker (MBI_BEHAVIOR = 0).

Modules:
    policy.py      load config/market_outlook_policy.yaml + its sha256 (policy_version)
    sources.py     the read layer (Postgres + MRE runtime JSON), as-of correct, banned feeds refused
    normalize.py   indicator -> signal in [-1, +1] (§2.1); every constant from the policy
    categories.py  the eleven categories: sub-score, coverage, state, per-indicator audit trail (§2.2)
    regime.py      VIX band x MRE tier multipliers and the MRE stance cap (§2.4, §2.7)
    scoring.py     S, bands, hysteresis, FOMC window (§2.3, §2.7)
    confidence.py  coverage x freshness x agreement x event x hit rate (§2.5)
    levels.py      key levels SPX / NDX / RUT (§4.2)
    calendar.py    this week's catalysts and the event tilt / surprise (§2.6, §4.5)
    record.py      the MarketOutlookRecord@v1 contract (§4.6) — field names are a cross-team contract
    brief.py       the dry-run report (§2.10) and record summary
    state_root.py  the persistent-state root the runtime JSON lives under (never a checkout)
    sessions_shim.py  the one import point for the MRE's NYSE session clock
"""

SCHEMA_POLICY = "MarketOutlookPolicy@v1"
SCHEMA_RECORD = "MarketOutlookRecord@v1"
SCHEMA_RUN_RECEIPT = "MarketOutlookRunReceipt@v1"
CATEGORY_KEYS = (
    "cash_indices",
    "futures",
    "volatility",
    "breadth",
    "leadership",
    "global",
    "rates",
    "credit",
    "commodities",
    "events",
    "positioning",
)
STATES = ("COLLECTED", "PARTIAL", "UNKNOWN")
BANDS = ("RISK_OFF", "DEFENSIVE", "NEUTRAL", "RISK_ON")

__all__ = [
    "SCHEMA_POLICY",
    "SCHEMA_RECORD",
    "SCHEMA_RUN_RECEIPT",
    "CATEGORY_KEYS",
    "STATES",
    "BANDS",
]
