"""Rich Telegram layouts, 2026-09-14. Offline, pure.

Operator: "we're still not getting rich, rich, deep HTML context in the Telegram ... no emphasis in links on
everything that can go back to the command center or to the source ... install the bot API and let's make
this happen."
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import telegram_rich as tr  # noqa: E402

COVERS = ["scripts/lib/telegram_rich.py"]
ALLOWED_TAGS = {"b", "i", "u", "s", "tg-spoiler", "a", "code", "pre", "blockquote"}

ARMP = {
    "symbol": "ARMP",
    "price": 6.24,
    "gap_pct": 15.8,
    "rvol": 70.4,
    "float_m": 11.6,
    "volume": 3155156,
    "score": 53,
    "run_label": "1000",
    "scanned_at": "2026-09-14 11:32",
    "catalyst": "Armata Pharmaceuticals shares rise 8% after FDA grants AP-SA02 Breakthrough Therapy <designation>",
    "catalyst_url": "https://example.com/armp-fda",
}


def _tags(html_text: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"</?([a-z-]+)", html_text)}


def test_only_telegram_supported_tags_are_emitted_and_values_are_escaped():
    out = tr.go_alert(ARMP, tier="A+", passed=["price", "float", "rvol"]).render()
    assert _tags(out["text"]) <= ALLOWED_TAGS
    assert "&lt;designation&gt;" in out["text"] and "<designation>" not in out["text"]
    assert out["parse_mode"] == "HTML"


def test_the_ticker_links_to_command_center_finviz_and_yahoo(monkeypatch):
    # 2026-09-15 lean: GO title + primary button land on Trading (scalp facts), not Watch Intelligence.
    monkeypatch.setattr(tr, "cc_base", lambda: "https://cc.example")
    out = tr.go_alert(ARMP, tier="A+", passed=["price"]).render()
    assert '<b><a href="https://cc.example/v3/trading?tab=Scalp&amp;symbol=ARMP">A+ ARMP — momentum scalp setup</a></b>' in out["text"]
    urls = [b["url"] for b in out["reply_markup"]["inline_keyboard"][0]]
    assert "https://finviz.com/quote.ashx?t=ARMP" in urls and "https://finance.yahoo.com/quote/ARMP" in urls
    assert "ARMP in Command Center" not in out["text"] and "finviz.com/quote.ashx" not in out["text"]


def test_why_is_a_quote_and_evidence_is_collapsible():
    out = tr.go_alert(ARMP, tier="GO", passed=["price", "float"]).render()
    assert "<blockquote>Catalyst:" in out["text"]
    assert "<blockquote expandable>Meets Trade-AI scalp criteria: price, float" in out["text"]


def test_buttons_and_the_chart_preview(monkeypatch):
    monkeypatch.setattr(tr, "cc_base", lambda: "https://cc.example")
    out = tr.go_alert(ARMP, tier="A+", passed=["price"]).render()
    row = out["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in row] == ["📊 Trading", "📈 Finviz", "💹 Yahoo"]
    assert row[0]["url"] == "https://cc.example/v3/trading?tab=Scalp&symbol=ARMP"
    assert out["link_preview_options"]["url"].startswith("https://charts2-node.finviz.com/chart.ashx?")
    assert out["link_preview_options"]["prefer_large_media"] is True


def test_only_https_links_survive():
    m = tr.RichMessage(
        title="t",
        sources=[("bad", "javascript:alert(1)"), ("plain", "http://x.example"), ("good", "https://ok.example")],
    )
    text = m.render()["text"]
    assert "javascript:" not in text and "http://x.example" not in text and 'href="https://ok.example"' in text


def test_long_evidence_is_trimmed_to_telegrams_limit_without_breaking_tags():
    m = tr.RichMessage(title="Material change", evidence=[f"line {i} " + "x" * 200 for i in range(100)])
    text = m.render()["text"]
    assert len(text) <= tr.MAX_TEXT
    assert text.count("<blockquote expandable>") == text.count("</blockquote>") == 1
    assert "…" in text


def test_symbols_come_from_the_producer_never_from_the_text(monkeypatch):
    monkeypatch.setattr(tr, "cc_base", lambda: "https://cc.example")
    m = tr.material_change(
        [
            {
                "symbol": "ETON",
                "kind": "new catalyst",
                "headline": "AP and F and TROW mentioned",
                "url": "https://n.example/1",
            }
        ]
    )
    text = m.render()["text"]
    assert "intelligence/ETON" in text and "intelligence/AP" not in text and "intelligence/TROW" not in text


def test_a_message_without_a_chart_disables_the_preview():
    out = tr.RichMessage(title="Spend").render()
    assert out["link_preview_options"] == {"is_disabled": True} and out["reply_markup"] is None


def test_operator_footer_has_no_internal_authority_token_and_the_transport_picks_html():
    from telegram_transport import parse_mode_for
    out = tr.go_alert(ARMP, tier="GO", passed=["price", "float"]).render()
    assert "READ_ONLY_ADVISORY" not in out["text"] and out["authority"] == "READ_ONLY_ADVISORY"
    assert "Advisory only" in out["text"]
    assert parse_mode_for(out["text"]) == "HTML"


def test_scan_time_is_readable():
    out = tr.go_alert(ARMP, tier="GO", passed=["price"]).render()
    assert "Score 53 · scanned 11:32 ET (10:00 run)" in out["text"]
    assert "scan 1000" not in out["text"]


def test_source_line_keeps_only_links_not_already_on_a_button():
    out = tr.go_alert(ARMP, tier="GO", passed=["price"]).render()
    assert 'Source: <a href="https://example.com/armp-fda">ARMP news</a>' in out["text"]
    no_news = dict(ARMP, catalyst_url="")
    assert "Source:" not in tr.go_alert(no_news, tier="GO", passed=["price"]).render()["text"]
