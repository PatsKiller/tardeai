"""Wave 3E — notification decisions rendered as a Command Center block.

Operator scope, verbatim: **CC block only, INTERDICT stays on, no Telegram
producer.** That makes this pure rendering: it displays decisions
`NotificationPolicy@v1` already computed, constructs no message, selects no
adapter and reaches no channel.

These tests exist to keep it that way. A "render-only" surface is one refactor
away from a producer, and the refactor always looks reasonable at the time.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_command_center import build_notification_block

REPO = Path(__file__).resolve().parents[1]
CC = REPO / "scripts" / "lib" / "cio_command_center.py"
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def _plan(pid, stype, material=True, symbols=None, status="draft"):
    return {"plan_id": pid, "situation_type": stype, "material": material,
            "symbols": symbols or [], "status": status}


def _book():
    return [
        _plan("p_s6a", "S6_CONCENTRATION_OR_DISPOSITION", symbols=["SCHD"]),
        _plan("p_s6b", "S6_CONCENTRATION_OR_DISPOSITION", symbols=["DIV"]),
        _plan("p_s1", "S1_POSITION_LIFECYCLE", symbols=["V"]),
        _plan("p_s5", "S5_CASH_DEPLOYMENT"),
        _plan("p_cold", "S3_REENTRY_CANDIDATE", material=False, symbols=["XLI"]),
        _plan("p_closed", "S6_CONCENTRATION_OR_DISPOSITION", symbols=["BND"],
              status="cancelled"),
    ]


# ------------------------------------------------------------------ scope

def test_block_declares_no_producer_and_no_send():
    b = build_notification_block(_book(), now=NOW)
    assert b["producer"] is None
    assert b["channel"] == "command_center"
    assert b["telegram_sent"] is False
    assert b["would_send_any"] is False
    assert all(i["would_send"] is False for i in b["items"])


def test_interdict_and_notify_flags_are_reported_not_changed():
    b = build_notification_block(_book(), now=NOW)
    assert b["interdicted"] is True
    assert b["notify_enabled"] is False


def test_module_gained_no_delivery_import():
    """Render-only is one refactor away from a producer. Hold the line."""
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                                     CC.read_text(encoding="utf-8", errors="replace")))
    for bad in ("cio_notification_delivery", "send_cio_message",
                "api.telegram.org", "RealTelegramAdapter",
                "cio_telegram_transport", "FakeDeliveryAdapter"):
        assert bad not in code, bad


def test_block_never_flips_an_env_var():
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                                     CC.read_text(encoding="utf-8", errors="replace")))
    assert "os.environ[" not in code
    assert "putenv" not in code


def test_block_carries_no_imperative():
    from scripts.lib.execution_language import find_imperative

    b = build_notification_block(_book(), now=NOW)
    assert not find_imperative(str(b))


# ------------------------------------------------------------- rendering

def test_only_open_plans_are_considered():
    b = build_notification_block(_book(), now=NOW)
    assert b["considered"] == 5, "the cancelled plan must not be considered"


def test_s6_surfaces_and_nothing_is_immediate():
    b = build_notification_block(_book(), now=NOW)
    assert b["surfaced_n"] == 2
    assert b["immediate_n"] == 0
    assert {i["situation_type"] for i in b["items"]} == {
        "S6_CONCENTRATION_OR_DISPOSITION"}


def test_suppressed_reasons_are_shown_not_just_counted():
    """4 surfaced is only credible next to what was considered and dropped."""
    b = build_notification_block(_book(), now=NOW)
    assert b["suppressed_n"] == 3
    reasons = b["suppressed_by_reason"]
    assert reasons["s1_observational_default_suppressed"] == 1
    assert reasons["s5_cash_deployment_default_suppressed"] == 1
    assert reasons["not_material"] == 1


def test_counts_reconcile():
    b = build_notification_block(_book(), now=NOW)
    assert (b["surfaced_n"] + b["digest_n"] + b["immediate_n"]
            + b["suppressed_n"]) == b["considered"]


def test_items_are_capped():
    many = [_plan(f"p{i}", "S6_CONCENTRATION_OR_DISPOSITION", symbols=[f"S{i}"])
            for i in range(25)]
    b = build_notification_block(many, cap=10, now=NOW)
    assert len(b["items"]) == 10
    assert b["surfaced_n"] == 25, "cap trims display, never the count"


def test_empty_book_is_available_not_broken():
    b = build_notification_block([], now=NOW)
    assert b["available"] is True
    assert b["considered"] == 0
    assert b["items"] == []


def test_none_book_does_not_raise():
    assert build_notification_block(None, now=NOW)["considered"] == 0


def test_policy_unavailable_degrades_visibly(monkeypatch):
    """A missing policy must say so, not render an empty quiet block.

    Blocks the module in sys.modules rather than patching __import__: the
    policy is already imported by the time this runs, so an __import__ hook
    never fires and the test would pass vacuously.
    """
    import sys as _sys

    import scripts.lib as _pkg

    # `from scripts.lib import cio_notification_policy` resolves via the
    # package ATTRIBUTE once the package is loaded, so blocking sys.modules
    # alone is not enough — the import succeeds and the test passes vacuously.
    monkeypatch.setitem(_sys.modules, "scripts.lib.cio_notification_policy", None)
    monkeypatch.delattr(_pkg, "cio_notification_policy", raising=False)
    b = build_notification_block(_book(), now=NOW)
    assert b["available"] is False
    assert b["reason"] == "policy_unavailable"
    assert b["telegram_sent"] is False
    assert b["would_send_any"] is False


# ------------------------------------------------------------ mounted

def test_block_is_mounted_on_office_home_with_the_full_store():
    """Fed `coverage_plans`, not the 12-row CIO NOW window.

    Reading the window made the block report `suppressed_n: 12` against 450 real
    open plans — a count that looks like the whole picture and is not, which is
    the same error as showing only the survivors. NOW stays capped at 5 cards;
    the block is not a card.
    """
    code = CC.read_text(encoding="utf-8", errors="replace")
    assert 'home["notifications"] = build_notification_block(' in code
    assert "coverage_plans if coverage_plans else plans" in code, (
        "the block must read the full open store, not the NOW window")


def test_the_full_store_and_the_window_give_different_counts():
    """Guards the distinction the mount relies on."""
    window = [{"plan_id": f"w{i}", "situation_type": "S1_POSITION_LIFECYCLE",
               "symbols": ["V"], "status": "draft", "material": False}
              for i in range(3)]
    full = window + [
        {"plan_id": "s6", "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
         "symbols": ["SCHD"], "status": "draft", "material": True}]
    assert build_notification_block(window, now=NOW)["surfaced_n"] == 0
    assert build_notification_block(full, now=NOW)["surfaced_n"] == 1


def test_office_home_still_reports_telegram_sent_false():
    code = CC.read_text(encoding="utf-8", errors="replace")
    assert 'home["telegram_sent"] = False' in code


# ============================ plan-source regressions (2026-08-29)

S6 = "S6_CONCENTRATION_OR_DISPOSITION"


def _p(pid, stype=S6, sym="AMANX", material=True, status="draft"):
    return {"plan_id": pid, "situation_type": stype, "symbols": [sym],
            "status": status, "material": material}


def test_a_material_s6_actually_surfaces():
    """Regression pin for #653.

    The block was pointed at `_coverage_plan_index()`, whose projection carried
    no `material` key — so `NotificationPolicy.decide()` read it as falsy and
    every row suppressed `not_material`. Live went to 475 considered / 475
    suppressed / **0 surfaced**: a count that looked plausible while the surface
    could never show anything.
    """
    b = build_notification_block([_p("a")], now=NOW)
    assert b["surfaced_n"] == 1, "a material S6 must reach the block"
    assert b["suppressed_n"] == 0


def test_a_suppressed_row_does_not_claim_the_subject_slot():
    """A non-material row iterated first must not shadow a material one.

    The dup key is (situation_type, first symbol) and was claimed
    unconditionally, so the first ('S6…','AMANX') row — material=False —
    suppressed as not_material AND took the slot, making the later material
    AMANX fire suppress as duplicate_subject. A concentration fire vanished on
    iteration order.
    """
    b = build_notification_block([_p("cold", material=False), _p("hot")], now=NOW)
    assert b["surfaced_n"] == 1
    assert b["suppressed_by_reason"].get("duplicate_subject") is None
    assert b["suppressed_by_reason"]["not_material"] == 1


def test_a_genuine_duplicate_is_still_collapsed():
    """The dup rule must still work — two material rows on one subject."""
    b = build_notification_block([_p("one"), _p("two")], now=NOW)
    assert b["surfaced_n"] == 1
    assert b["suppressed_by_reason"]["duplicate_subject"] == 1


def test_different_symbols_do_not_collapse_into_each_other():
    b = build_notification_block([_p("a", sym="SCHD"), _p("b", sym="DIV")],
                                 now=NOW)
    assert b["surfaced_n"] == 2


def test_the_coverage_projection_carries_material_and_plan_id():
    """The projection a consumer branches on must not drop that field."""
    import re

    src = (REPO / "scripts" / "api_v3_cio.py").read_text(encoding="utf-8",
                                                         errors="replace")
    body = src.split("def _coverage_plan_index", 1)[1].split("\ndef ", 1)[0]
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", body))
    assert '"material"' in code, "coverage projection must carry material"
    assert '"plan_id"' in code, "coverage projection must carry plan_id"


def test_open_plans_kpi_counts_the_store_not_the_window():
    """`attention.open_plans` is defined as the durable store."""
    from scripts.lib.cio_command_center import build_cio_now

    window = [{"plan_id": f"w{i}", "status": "draft"} for i in range(12)]
    store = [{"plan_id": f"s{i}", "status": "draft"} for i in range(458)]
    assert build_cio_now(plans=window)["attention"]["open_plans"] == 12
    got = build_cio_now(plans=window, all_open_plans=store)
    assert got["attention"]["open_plans"] == 458
    assert len(got.get("cards") or []) <= 5, "cards stay capped at 5"
