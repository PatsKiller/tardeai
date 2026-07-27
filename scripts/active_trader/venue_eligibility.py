"""Active Trader Stage 1a — venue eligibility (pure, read-only; NO order, NO send).

Encodes the product contract:

  1. Schwab is the PRIMARY venue when eligible.
  2. A Schwab compliance-blocked symbol/account (call-broker / low-float restriction):
       - surfaces the explicit block reason to the operator,
       - NEVER silently auto-routes to Moomoo/Alpaca,
       - REQUIRES an operator prompt to switch venue (operator must confirm).
  3. Moomoo / Alpaca are execution alternates ONLY when the operator opts in
     (Moomoo also carries the L2 + tape data role).

PURE: takes a symbol + proposed venue + a capability snapshot (which MAY be a fixture)
and returns an EligibilityResult. No I/O, no network, no order, no send. Fail-closed:
when eligibility cannot be determined the status is `unknown`, and a Schwab block never
results in `auto_route=True`.

Statuses: eligible | blocked_schwab_compliance | unknown | restricted
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional

CONTRACT = "active-trader-venue-eligibility-v1"

SCHWAB = "schwab"
MOOMOO = "moomoo"
ALPACA = "alpaca"
KNOWN_VENUES = (SCHWAB, MOOMOO, ALPACA)
ALTERNATE_VENUES = (MOOMOO, ALPACA)

# Eligibility statuses
ELIGIBLE = "eligible"
BLOCKED_SCHWAB_COMPLIANCE = "blocked_schwab_compliance"
UNKNOWN = "unknown"
RESTRICTED = "restricted"

# Recognized Schwab compliance block codes
BLOCK_CALL_BROKER = "call_broker"
BLOCK_LOW_FLOAT = "low_float_restriction"

_BLOCK_REASON = {
    BLOCK_CALL_BROKER: "Schwab requires calling the trade desk to place this order.",
    BLOCK_LOW_FLOAT: "Schwab restricts this low-float / hard-to-borrow symbol.",
}


@dataclass(frozen=True)
class EligibilityResult:
    symbol: str
    proposed_venue: str
    status: str
    reason: str
    block_code: Optional[str] = None
    prompt_required: bool = False
    alternate_venues: tuple[str, ...] = ()
    auto_route: bool = False          # HARD: a Schwab block NEVER silently auto-routes
    detail: str = ""
    contract: str = CONTRACT

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["alternate_venues"] = list(self.alternate_venues)
        return d


def _s(v: Any) -> str:
    return str(v or "").strip()


def normalize_venue(v: Any) -> str:
    return _s(v).lower()


def _block_reason(code: str) -> str:
    return _BLOCK_REASON.get(code, "Schwab compliance restriction on this symbol/account.")


def _available_alternates(venues: Mapping[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    for v in ALTERNATE_VENUES:
        info = venues.get(v)
        if isinstance(info, Mapping) and info.get("available"):
            out.append(v)
    return tuple(out)


def evaluate_eligibility(
    symbol: str,
    proposed_venue: str,
    capability_snapshot: Mapping[str, Any] | None,
) -> EligibilityResult:
    """Decide venue eligibility for a symbol. Never mutates, never routes, never sends."""
    sym = _s(symbol).upper()
    venue = normalize_venue(proposed_venue) or SCHWAB  # Schwab is primary by default

    # ── fail-closed guards ────────────────────────────────────────────────────
    if not sym:
        return EligibilityResult(sym, venue, UNKNOWN, "no symbol supplied",
                                 detail="fail-closed: eligibility cannot be determined")
    if not isinstance(capability_snapshot, Mapping) or not capability_snapshot:
        return EligibilityResult(sym, venue, UNKNOWN, "no capability snapshot",
                                 detail="fail-closed: eligibility cannot be determined")
    if venue not in KNOWN_VENUES:
        return EligibilityResult(sym, venue, RESTRICTED, f"unknown venue {venue!r}",
                                 detail=f"venue must be one of {KNOWN_VENUES}")

    venues = capability_snapshot.get("venues")
    venues = venues if isinstance(venues, Mapping) else {}
    compliance = capability_snapshot.get("symbol_compliance")
    compliance = compliance if isinstance(compliance, Mapping) else {}
    sym_comp = compliance.get(sym)
    sym_comp = sym_comp if isinstance(sym_comp, Mapping) else None

    # ── Schwab (primary) ──────────────────────────────────────────────────────
    if venue == SCHWAB:
        vinfo = venues.get(SCHWAB)
        vinfo = vinfo if isinstance(vinfo, Mapping) else {}
        if not vinfo.get("available", False):
            return EligibilityResult(sym, venue, UNKNOWN, "Schwab capability unknown",
                                     detail="fail-closed: schwab venue not present/available in snapshot")

        if sym_comp and sym_comp.get("schwab_blocked"):
            code = _s(sym_comp.get("block_code")).lower() or "compliance_block"
            reason = _s(sym_comp.get("detail")) or _block_reason(code)
            return EligibilityResult(
                sym, venue, BLOCKED_SCHWAB_COMPLIANCE,
                reason=reason, block_code=code, prompt_required=True,
                alternate_venues=_available_alternates(venues), auto_route=False,
                detail="Schwab compliance-blocked — operator must confirm any venue switch; no auto-route.",
            )

        if sym_comp is not None:
            # explicitly covered and not blocked
            return EligibilityResult(sym, venue, ELIGIBLE,
                                     "Schwab eligible (no compliance block)", detail="primary venue")

        # symbol not explicitly listed: blocklist coverage means "not listed = not blocked"
        coverage = _s(vinfo.get("compliance_coverage") or "blocklist").lower()
        if coverage == "blocklist":
            return EligibilityResult(sym, venue, ELIGIBLE,
                                     "Schwab eligible (not on compliance blocklist)",
                                     detail="primary venue · blocklist coverage")
        # allowlist / unknown coverage → cannot confirm → fail-closed
        return EligibilityResult(sym, venue, UNKNOWN,
                                 "symbol not covered by Schwab compliance snapshot",
                                 detail="fail-closed: coverage is not an authoritative blocklist")

    # ── Alternate venue (moomoo / alpaca) ─────────────────────────────────────
    vinfo = venues.get(venue)
    vinfo = vinfo if isinstance(vinfo, Mapping) else {}
    if not vinfo.get("available", False):
        return EligibilityResult(sym, venue, UNKNOWN, f"{venue} capability unknown",
                                 detail="fail-closed")
    if not vinfo.get("operator_opt_in", False):
        return EligibilityResult(
            sym, venue, RESTRICTED,
            reason=f"{venue} is an execution alternate that requires operator opt-in",
            prompt_required=True,
            detail="operator must opt in before an alternate venue is usable",
        )
    return EligibilityResult(sym, venue, ELIGIBLE,
                             f"{venue} eligible (operator opted in)", detail="alternate venue")


def operator_prompt_required(block: EligibilityResult) -> dict[str, Any]:
    """Message TEMPLATE for the operator when Schwab is compliance-blocked. NO SEND.

    Returns a template describing the block and the alternate-venue choice the operator
    must explicitly confirm. It never routes, never sends, never auto-selects a venue —
    `auto_route` and `send` are hard-false. For a non-block result, prompt_required is
    false and the message is empty.
    """
    if not isinstance(block, EligibilityResult):
        raise TypeError("operator_prompt_required expects an EligibilityResult")
    is_block = block.status == BLOCKED_SCHWAB_COMPLIANCE
    alts = list(block.alternate_venues)
    alt_txt = " or ".join(v.capitalize() for v in alts) if alts else "an alternate venue"
    message = ""
    if is_block:
        message = (
            f"{block.symbol}: Schwab is compliance-blocked — {block.reason} "
            f"Switch to {alt_txt}? This will not happen automatically; confirm to proceed."
        )
    return {
        "contract": CONTRACT,
        "prompt_required": bool(is_block),
        "requires_operator_confirmation": bool(is_block),
        "auto_route": False,   # HARD
        "send": False,         # template only — never sent here
        "channel": "operator_confirm",
        "symbol": block.symbol,
        "block_code": block.block_code,
        "reason": block.reason if is_block else "",
        "alternate_venues": alts,
        "message": message,
    }
