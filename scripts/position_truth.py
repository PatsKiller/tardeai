#!/usr/bin/env python3
"""position_truth.py — live ownership is ground truth for every model call.

WHY THIS EXISTS
---------------
On 2026-07-20 the agent `steph` recommended TRIM on BETA, reasoning from an
assumed 17.3% / $1.3M holding. Ground truth: 0 shares, $0, never traded in any
account. The synthesis caught the contradiction and recorded it —

    "Steph narrative assumes existing 17.3% overweight position and $1.3M
     holding; directly contradicts PORTFOLIO POSITION ground truth of 0 shares
     and $0 value"

— and then a downstream cron re-stamped that same discarded TRIM onto the card
74 minutes later, and would have every 30 minutes after that.

Two defects, and this module addresses the upstream one. The materializer fix
(58993792) suppresses a discarded rec at the card; it matches free-text prose,
which works but is brittle. This module prevents the hallucination from being
produced by injecting authoritative ownership BEFORE the model is asked, and
emits a STRUCTURED contradiction record rather than a sentence to be re-parsed.

THE ASYMMETRY
-------------
A false "you hold this" is far more dangerous than a false "you do not". The
first produces TRIM/EXIT/COVERED_CALL advice on a position that does not exist —
advice which, if acted on, sells something you never owned or writes calls
against shares you cannot deliver. The second merely suppresses an entry.

So detection errs toward flagging: an ambiguous claim about holding something we
do not hold is reported, and the burden is on the narrative to be unambiguous.

PURE: no database. `ownership_from_holdings` reads a supplied dict; the DB-backed
loader is a thin separate function.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Actions that only make sense against an existing position. A narrative
# recommending one of these for an unheld symbol is contradicting ground truth
# whether or not it states a share count.
HELD_ONLY_ACTIONS = frozenset({
    "TRIM", "EXIT", "SELL", "REDUCE", "REBALANCE_TRIM", "COVERED_CALL",
    "PROTECTIVE_PUT", "COLLAR", "HOLD", "ADD", "ADD_ON_PULLBACK",
})

# The subset whose execution would dispose of, or encumber, shares. These are
# the ones that could cause a real trade against a phantom position.
DISPOSAL_ACTIONS = frozenset({
    "TRIM", "EXIT", "SELL", "REDUCE", "REBALANCE_TRIM", "COVERED_CALL", "COLLAR",
})

# Language asserting an existing position.
_CLAIMS_HELD = re.compile(
    r"\b("
    r"existing\s+position|current\s+position|our\s+position|the\s+position"
    r"|already\s+(own|hold)|currently\s+(own|hold|holding)s?"
    r"|overweight|underweight|concentration|portfolio\s+heat"
    r"|your\s+(stake|holding|shares)|we\s+(own|hold)"
    r"|cost\s+basis|unrealized|book\s+value"
    r"|trim(ming)?\s+the|reduce\s+the|exit(ing)?\s+the"
    r")\b",
    re.I,
)

# A percentage-of-portfolio or dollar claim, e.g. "17.3% overweight", "$1.3M holding".
_CLAIMS_SIZE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(of\s+(the\s+)?portfolio|overweight|underweight|allocation|position|weight)"
    r"|\$\s?(\d+(?:\.\d+)?)\s*([MKB])\b\s*(holding|position|stake|value)",
    re.I,
)


@dataclass(frozen=True)
class Ownership:
    """Authoritative live ownership for one symbol."""
    symbol: str
    held: bool
    shares: float = 0.0
    market_value: float = 0.0
    accounts: tuple = field(default_factory=tuple)
    source: str = ""
    as_of: str = ""
    uncommitted_shares: Optional[float] = None

    def to_block(self) -> str:
        """The text injected into every model prompt. Deliberately blunt and
        positioned as ground truth, because narrative context is what the model
        otherwise pattern-matches against."""
        if not self.held:
            return (
                "PORTFOLIO POSITION — GROUND TRUTH (authoritative, overrides any\n"
                "other context, narrative, or prior analysis you have seen):\n"
                f"  {self.symbol}: NOT CURRENTLY HELD\n"
                "  Shares: 0\n"
                "  Market value: $0\n"
                f"  Source: {self.source or 'live holdings'}\n"
                f"  As of: {self.as_of or 'unknown'}\n"
                "\n"
                "You therefore MUST NOT recommend trimming, reducing, exiting,\n"
                "selling, writing covered calls against, or collaring this symbol.\n"
                "There is nothing to trim. Do not reason about concentration,\n"
                "portfolio heat, or overweight/underweight for a position of zero.\n"
                "If your analysis suggests otherwise, your premise is wrong."
            )
        accounts = ", ".join(self.accounts) if self.accounts else "unspecified"
        unc = ("  Uncommitted shares: "
               f"{self.uncommitted_shares:,.0f}\n" if self.uncommitted_shares is not None else "")
        return (
            "PORTFOLIO POSITION — GROUND TRUTH (authoritative, overrides any\n"
            "other context, narrative, or prior analysis you have seen):\n"
            f"  {self.symbol}: CURRENTLY HELD\n"
            f"  Shares: {self.shares:,.4f}\n"
            f"  Market value: ${self.market_value:,.2f}\n"
            f"{unc}"
            f"  Accounts: {accounts}\n"
            f"  Source: {self.source or 'live holdings'}\n"
            f"  As of: {self.as_of or 'unknown'}\n"
            "\n"
            "Do not assert a different share count, market value, or weight."
        )

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "held": self.held, "shares": self.shares,
                "market_value": self.market_value, "accounts": list(self.accounts),
                "source": self.source, "as_of": self.as_of,
                "uncommitted_shares": self.uncommitted_shares}


@dataclass(frozen=True)
class Contradiction:
    """A structured record that a narrative conflicts with ground truth.

    Structured on purpose: the existing card-side suppression matches prose,
    which works but silently stops working if the wording changes."""
    symbol: str
    agent: str
    kind: str                 # PHANTOM_POSITION | SIZE_MISMATCH | DISPOSAL_OF_NOTHING
    severity: str             # CRITICAL | HIGH | MEDIUM
    detail: str
    evidence: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "agent": self.agent, "kind": self.kind,
                "severity": self.severity, "detail": self.detail,
                "evidence": self.evidence[:400], "recommendation": self.recommendation}


def detect_contradictions(*, ownership: Ownership, narrative: str = "",
                          recommendation: str = "", agent: str = "") -> list:
    """Structured contradictions between a narrative and live ownership.

    Only claims that would MATERIALLY mislead are reported. A narrative that
    merely mentions the word "position" while recommending BUY on an unheld name
    is not flagged; one that recommends TRIM on it is.
    """
    out: list = []
    text = str(narrative or "")
    rec = str(recommendation or "").strip().upper()

    if not ownership.held:
        # The dangerous case: advice to dispose of something not owned.
        if rec in DISPOSAL_ACTIONS:
            out.append(Contradiction(
                symbol=ownership.symbol, agent=agent, kind="DISPOSAL_OF_NOTHING",
                severity="CRITICAL",
                detail=f"recommends {rec} on a symbol with 0 shares held — there is "
                       f"nothing to dispose of or encumber",
                recommendation=rec))

        claims_held = bool(_CLAIMS_HELD.search(text))
        size = _CLAIMS_SIZE.search(text)
        if size:
            out.append(Contradiction(
                symbol=ownership.symbol, agent=agent, kind="PHANTOM_POSITION",
                severity="CRITICAL",
                detail=f"asserts a position size for a symbol with 0 shares and $0 value",
                evidence=text[max(0, size.start() - 90):size.end() + 90],
                recommendation=rec))
        elif claims_held:
            m = _CLAIMS_HELD.search(text)
            out.append(Contradiction(
                symbol=ownership.symbol, agent=agent, kind="PHANTOM_POSITION",
                severity="HIGH",
                detail="narrative reasons from an existing position; ground truth is 0 shares",
                evidence=text[max(0, m.start() - 90):m.end() + 90],
                recommendation=rec))
        return out

    # Held: check a stated size against the truth, when one is stated.
    size = _CLAIMS_SIZE.search(text)
    if size and ownership.market_value > 0:
        claimed = None
        if size.group(4):
            mult = {"K": 1e3, "M": 1e6, "B": 1e9}[size.group(5).upper()]
            claimed = float(size.group(4)) * mult
        if claimed is not None:
            ratio = claimed / ownership.market_value if ownership.market_value else 0
            if ratio > 3 or ratio < 0.33:
                out.append(Contradiction(
                    symbol=ownership.symbol, agent=agent, kind="SIZE_MISMATCH",
                    severity="HIGH",
                    detail=f"narrative implies ${claimed:,.0f} against a live "
                           f"${ownership.market_value:,.2f}",
                    evidence=text[max(0, size.start() - 90):size.end() + 90],
                    recommendation=rec))
    return out


def is_recommendation_admissible(*, ownership: Ownership, recommendation: str) -> tuple:
    """(admissible, reason). The gate that keeps a hallucinated holding out of the
    packet and the card, independent of whether prose analysis caught it."""
    rec = str(recommendation or "").strip().upper()
    if not rec:
        return True, ""
    if not ownership.held and rec in DISPOSAL_ACTIONS:
        return False, (f"{rec} requires an existing position; {ownership.symbol} has "
                       f"0 shares held as of {ownership.as_of or 'unknown'}")
    return True, ""


def ownership_from_holdings(symbol: str, holdings: dict) -> Ownership:
    """Build Ownership from a parsed holdings.json payload.

    A symbol absent from the file is NOT-HELD, which is correct: the file is the
    complete position list. But `source`/`as_of` are carried so a consumer can
    see how old that claim is rather than trusting it blindly.
    """
    sym = str(symbol or "").upper()
    rows = (holdings or {}).get("holdings") or []
    as_of = str((holdings or {}).get("generated_at") or (holdings or {}).get("as_of") or "")
    mine = [r for r in rows if str(r.get("symbol", "")).upper() == sym]
    if not mine:
        return Ownership(sym, held=False, source="holdings.json", as_of=as_of)
    shares = sum(float(r.get("quantity") or r.get("shares") or 0) for r in mine)
    mv = sum(float(r.get("market_value") or 0) for r in mine)
    accts = tuple(sorted({str(r.get("account") or "") for r in mine if r.get("account")}))
    return Ownership(sym, held=shares > 0 or mv > 0, shares=shares, market_value=mv,
                     accounts=accts, source="holdings.json", as_of=as_of)
