"""A desk answer as a person reads it on a phone. Offline, pure.

2026-09-14: the operator received the AXTI answer's bookkeeping tail as its own message and wrote "Gibberish".
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import telegram_desk_render as r  # noqa: E402

COVERS = ["scripts/lib/telegram_desk_render.py"]
ALLOWED = {"b", "i", "u", "s", "tg-spoiler", "a", "code", "pre", "blockquote"}

SECTION = ("🟢 Trade-AI data · Analysts (Yahoo targets, as of Jun 24, 82 days old — stale): Buy · 4 analysts · "
           "mean target $96.50 (low $73.00, high $125.00) · +49.0% vs $64.76 <stale>\n")
AXTI = (
    "Key: 🟢 green = Trade-AI's own stored data · 🔵 blue = looked up outside Trade-AI for this reply · 🟣 purple = written by an AI model (DeepSeek), check before acting\n"
    "🟣 AI model (DeepSeek) wrote the summary below from Trade-AI facts:\n"
    "*AXTI — house view first*\n\n"
    "*Levels (2026-09-14):* last close `64.76`; live `58.93` @13:30 ET. RSI 42.4.\n\n"
    + ("\n".join([SECTION] * 3) + "\n\n") * 12
    + "Origin: 🟢 Trade-AI data (11 stores) · 🔵 Looked up outside Trade-AI: nothing · 🟣 AI model (DeepSeek): intent classification only, general knowledge where labelled\n"
    "Sources: CIO snapshot (cash, sector_exposure, risk) | ticker_prices (daily closes) | re-entry desk | symbol_profiles | "
    "catalyst_events | yahoo_analyst_targets_history | sector_momentum_latest.json | industry_momentum_latest.json | "
    "hermes_research_intelligence | symbol thesis store | holdings.json | deepseek-flash — general knowledge where labelled; numbers from the stores above\n"
    "Went outside: deepseek-flash — intent classification only; no facts; deepseek-flash — general knowledge where labelled\n"
    "READ_ONLY_ADVISORY"
)


def test_a_long_answer_becomes_labelled_parts_within_telegrams_limit():
    parts = r.render_desk_reply(AXTI)
    assert len(parts) >= 2
    assert all(r.utf16_len(p) <= r.TELEGRAM_TEXT_LIMIT for p in parts)
    assert parts[0].startswith(f"<i>Part 1 of {len(parts)}</i>") and parts[-1].startswith(f"<i>Part {len(parts)} of {len(parts)}</i>")


def test_only_telegram_tags_and_every_value_escaped():
    joined = "\n".join(r.render_desk_reply(AXTI))
    assert {m.group(1) for m in re.finditer(r"</?([a-z-]+)", joined)} <= ALLOWED
    assert "&lt;stale&gt;" in joined and "<stale>" not in joined
    assert "<b>AXTI — house view first</b>" in joined and "<code>64.76</code>" in joined


def test_the_bookkeeping_tail_is_one_plain_line_and_a_collapsed_detail():
    parts = r.render_desk_reply(AXTI)
    visible = re.sub(r"<blockquote expandable>.*?</blockquote>", "", "\n".join(parts), flags=re.S)
    for raw in ("ticker_prices", "yahoo_analyst_targets_history", "sector_momentum_latest.json", "Went outside:",
                "Origin:", "Sources:", "READ_ONLY_ADVISORY", "Key: 🟢 green"):
        assert raw not in visible, raw
    assert "🟢 11 Trade-AI sources" in parts[-1] and "advisory only — no orders" in parts[-1]
    detail = re.search(r"<blockquote expandable>(.*?)</blockquote>", parts[-1], re.S).group(1)
    assert "Trade-AI daily prices" in detail and "analyst targets (Yahoo)" in detail and "your holdings" in detail
    assert "DeepSeek (general knowledge where labelled)" in detail


def test_a_model_only_went_outside_line_is_not_an_outside_lookup():
    parts = r.render_desk_reply(AXTI)
    assert "looked up outside Trade-AI" not in parts[-1]
    real = r.render_desk_reply("*HPE*\nSources: re-entry desk\nWent outside: brave_search — news for HPE; "
                               "deepseek-flash — wording only\nREAD_ONLY_ADVISORY")
    assert "🔵 looked up outside Trade-AI" in real[-1] and "brave_search — news for HPE" in real[-1]


def test_a_short_answer_is_one_message_without_a_part_label():
    parts = r.render_desk_reply("*SCHG*: price $35.16\nSources: re-entry desk | holdings.json\nREAD_ONLY_ADVISORY")
    assert len(parts) == 1 and not parts[0].startswith("<i>Part") and "🟢 2 Trade-AI sources" in parts[0]


def test_plain_source_names():
    assert r.plain_source("ticker_prices (daily closes)") == "Trade-AI daily prices"
    assert r.plain_source("some_new_store.json") == "some new store"
