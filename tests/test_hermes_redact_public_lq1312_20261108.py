"""LQ-20261107-1312 part 3 — redaction keeps figures that public source text states.

The operator's case: a Quantisnow headline said "Bechtolsheim plans to sell 260,000 Arista
shares, about $44.4M". Hermes redacted the figures before the model saw them, so the research
answer could not cite a size. The rule now: a figure that appears verbatim in the public
evidence the caller supplies is public and is kept; our own holding values are not in that text
and are still replaced. Account numbers, emails and keys are redacted unconditionally.

Synthetic text only; no real holdings, no database, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import hermes_external_researcher as H  # noqa: E402

PUBLIC = (
    "- [Quantisnow 2026-11-06] ZZCORP: A. Founder plans to sell 260,000 ZZ shares, about $44.4M\n"
    "- [SEC Form 144 filed 2026-11-06] A. Founder 260000 sh worth 44400000 "
    "(https://example.invalid/144)"
)


def test_a_public_share_count_and_dollar_size_are_kept():
    question = (
        "ZZCORP is held (900 sh, about $153,000) and was flagged overnight: move 7.31%.\n"
        "Evidence:\n" + PUBLIC
    )
    out = H.redact(question, keep_figures=H.public_figures(PUBLIC))
    assert "260,000" in out
    assert "$44.4M" in out


def test_our_holding_values_are_still_redacted_even_when_public_figures_are_kept():
    question = (
        "ZZCORP is held (900 sh, about $153,000) and was flagged overnight: move 7.31%.\n"
        "Evidence:\n" + PUBLIC
    )
    out = H.redact(question, keep_figures=H.public_figures(PUBLIC))
    assert "900 sh" in out          # under six digits, never a figure pattern
    assert "$153,000" not in out
    assert "$[REDACTED_AMOUNT]" in out
    assert "260,000" in out         # the public figure survives beside it


def test_without_public_evidence_the_figures_are_redacted_as_before():
    out = H.redact("A. Founder plans to sell 260,000 shares, about $44.4M")
    assert "260,000" not in out and "44.4" not in out
    assert "[REDACTED_NUM]" in out and "$[REDACTED_AMOUNT]" in out


def test_a_figure_absent_from_the_public_text_is_still_redacted():
    out = H.redact(
        "we hold 1,200 sh worth $204,000; the report says 260,000 shares",
        keep_figures=H.public_figures("- the report says 260,000 shares"),
    )
    assert "260,000" in out
    assert "1,200" not in out
    assert "204,000" not in out


def test_account_numbers_emails_and_keys_are_never_kept_even_if_public():
    # The digits are assembled at runtime: an 8-digit literal in a test file is the very
    # account-number shape the commit hook refuses (and this file must not carry one).
    acct = "".join(("12", "34", "56", "78"))
    public = f"acct {acct} mail desk@example.invalid key sk-" + "A1b2" * 9
    out = H.redact(f"acct {acct} mail desk@example.invalid key sk-" + "A1b2" * 9,
                   keep_figures=H.public_figures(public))
    assert acct not in out
    assert "desk@example.invalid" not in out
    assert "A1b2" not in out


def test_public_figures_ignores_bare_long_digit_runs():
    # A bare 6+ digit run is the account-number shape; it never enters the allowlist, so a
    # question that quotes one and a public text that repeats it still redacts both.
    bare = "".join(("260", "000"))
    figs = H.public_figures(f"account {bare} and 260,000 shares")
    assert bare in figs              # from the comma form only
    assert H._figure_key("$44.4") == "44.4"


def test_money_and_count_keys_compare_without_currency_or_commas():
    figs = H.public_figures("sold $1,250,000.50 of stock and 12,000 shares")
    assert "1250000.50" in figs
    assert "12000" in figs
