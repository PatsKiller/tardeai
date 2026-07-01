#!/usr/bin/env python3
"""watch_directive_canonical.py — canonical family keys for trend watch-directives.

Shared by:
  - watch_directive_dedup.py     (one-time cleanup: group near-dups into a family survivor)
  - hermes_think_tank.py         (creation-time guard: collapse a new near-dup onto the
                                  existing family directive instead of creating another)

A "family" is a deliberately BROAD theme. The point is to stop dozens of near-identical
labels ("M&A surge", "M&A and consolidation", "event-driven M&A…") from each becoming a
separate directive that fragments the same hit signal. Fine-grained intent is still
expressible via explicit operator ticker/sector directives, which are never family-collapsed.

Keep this list conservative — every regex here also drives the archival cleanup, so a
too-greedy pattern silently merges directives that shouldn't be merged.
"""
import re

# (family_slug, match_regex) — matched against the normalized label
FAMILIES = [
    # NOTE: patterns match the NORMALIZED label (punctuation → spaces, lowercased), so "M&A"
    # arrives as the bigram "m a" — the \bm a\b alternative is what actually catches bare "M&A …".
    ("m_and_a",            r"\bm a\b|merger|acquisition|manda|consolidation|strategic deal|deal (flow|wave|cycle|surge)|contract (win|momentum|activit)"),
    ("data_center",        r"data ?cent(er|re)|ai datacenter"),
    ("power_grid",         r"power grid|grid buildout|electricity demand|utilities infrastructure|utilities buildout|utilities demand|power infrastructure|nuclear (energy|power)"),
    ("small_cap_rotation", r"small.?cap"),
    ("semi_supply_chain",  r"semiconductor supply"),
    ("defense_spending",   r"defense spend|defense.?geopolitical|defense spending (catalyst|surge|acceleration)|geopolitical (spending|catalyst)"),
    ("biotech_catalyst",   r"biotech.*(catalyst|rerating|readout|squeeze)|specialty pharma"),
    ("options_framework",  r"\boption\b.*(strateg|framework|greeks|volatility|hedg|condor|collar)"),
    ("sector_rotation",    r"sector rotation (mechanics|swing|framework|timing)|rotation out of|style rotation"),
]


def norm_label(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def canonical_family(label: str):
    """Return the family slug a label belongs to, or None if it isn't a known near-dup family."""
    n = norm_label(label)
    for slug, rx in FAMILIES:
        if re.search(rx, n):
            return slug
    return None
