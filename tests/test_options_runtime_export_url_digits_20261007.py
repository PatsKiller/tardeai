"""2026-10-07: the first options-tick receipt after the tranche C cutover showed step `export` FAILED. The
export's account-number guard had been refusing the whole snapshot for ~130 hourly runs because one NFLX
thesis catalyst quoted a news URL whose article id is an 8-digit run. A digit run inside a URL identifies
a page, not an account; the redactor now neutralises it and the guard stays as strict as before."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import export_options_runtime_snapshot as E  # noqa: E402

CFG = dict(E.DEFAULTS)
URL = "https://news.example.com/netflix-earnings-analysts-split/70123456"


def test_a_url_article_id_no_longer_counts_as_an_account_number():
    red = E.Redactor(CFG, terms=[])
    text = red.text(f"Earnings 2026-10-16 ({URL}). A second source agrees.")
    assert "70123456" not in text and "[n]" in text
    assert E.find_violations({"catalysts": [text]}, CFG, [], "$.t") == []


def test_a_bare_eight_digit_run_still_refuses_the_export():
    red = E.Redactor(CFG, terms=[])
    text = red.text("wire to 12345678 before close")
    assert E.find_violations({"note": text}, CFG, [], "$.t") == ["$.t.note: account-number-like value"]


def test_the_thesis_projection_carries_the_redacted_catalyst():
    red = E.Redactor(CFG, terms=[])
    row = {"event": "thesis", "symbol": "NFLX", "version": 3, "catalysts": [f"see {URL} for the split"],
           "thesis_id": "t-1"}
    out = red.texts(row["catalysts"])
    assert out == [f"see {URL.rsplit('/', 1)[0]}/[n] for the split"]
