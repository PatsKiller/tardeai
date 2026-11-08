"""FABLE-OUTLOOK-METHODOLOGY-LQ-946 WU-3 — the market-outlook brief, its CIO row and its delivery rules.

Every fixture is synthetic (invented index levels, invented catalysts, a reserved-domain address) because this
repository is public. Nothing here sends anything: the senders are recording stubs, and the one primitive that could
reach a phone is exercised with a temporary contact file.

What this file is for, in the operator's terms:
  * an UNKNOWN category is printed as UNKNOWN with its reason and never as a zero (a missing reading and a neutral
    reading are opposite facts);
  * the text is at most its class cap (300 by D1) and a cap too small is refused, never met by slicing the sentence;
  * a re-run of the same record sends nothing, and the row that proves the first delivery is never overwritten;
  * the brief states a stance and reaches no broker.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import critical_texts as ct  # noqa: E402
from scripts.lib import market_outlook_brief as mob  # noqa: E402
from scripts import email_notifier  # noqa: E402

FIXTURE = Path(__file__).with_name("fixtures") / "market_weekly_outlook_record_sample.json"
RECORD_ID = "outlook:2026-11-08:sunday:1"


def load_record():
    return mob.load_record_file(FIXTURE)


def policy():
    return mob.load_policy()


def record_variant(**over):
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    record.update(over)
    return record


def fixture_ok():
    return mob.validate_record(load_record()) == []


# ----------------------------------------------------------------------------- the contract
def test_the_fixture_is_a_valid_contract_record():
    record = load_record()
    assert mob.validate_record(record) == []
    assert record["record_id"] == RECORD_ID
    assert len(record["categories"]) == mob.CATEGORY_COUNT


def test_an_unknown_category_may_not_carry_a_subscore():
    """The honesty rule: a missing input is null, never 0 — a zero would claim it was read and was neutral."""
    record = record_variant()
    futures = next(c for c in record["categories"] if c["key"] == "futures_overnight")
    futures["subscore"] = 0.0
    errors = mob.validate_record(record)
    assert any("UNKNOWN" in error and "subscore" in error for error in errors), errors


def test_a_collected_category_must_have_a_reading():
    record = record_variant()
    credit = next(c for c in record["categories"] if c["key"] == "credit")
    credit["subscore"] = None
    assert any("credit" not in e and "COLLECTED" in e for e in mob.validate_record(record))


def test_the_actions_template_must_match_the_band():
    """A brief must never print one band's stance under another band's label."""
    record = record_variant()
    record["actions_template"]["band"] = "RISK-ON"
    assert any("actions_template.band" in e for e in mob.validate_record(record))


def test_a_record_with_a_bad_id_is_refused():
    record = record_variant()
    record["record_id"] = "outlook-2026-11-08"
    assert any("record_id" in e for e in mob.validate_record(record))


# ----------------------------------------------------------------------------- the text sentence
def test_the_text_carries_the_stance_the_action_and_the_record_id():
    text = mob.render_text(load_record(), policy=policy(), max_chars=300)
    assert len(text) <= 300
    assert text.startswith("OUTLOOK Sun 11/8: S -21 DEFENSIVE conf LOW.")
    assert "Catalysts: Tue 8:30 " in text and "HIGH" in text
    assert "Action: no new tranches, hold the 5% reserve." in text
    assert text.endswith(f"id {RECORD_ID}")


@pytest.mark.parametrize("cap", [120, 140, 160, 180, 200, 232, 233, 260, 300, 400])
def test_the_text_never_exceeds_its_cap_or_returns_something_wrong(cap):
    """Every cap either fits the sentence or refuses by name; no path returns a sliced brief."""
    try:
        text = mob.render_text(load_record(), policy=policy(), max_chars=cap)
    except mob.BriefError as exc:
        assert "cannot be texted" in str(exc) or "below the" in str(exc)
        return
    assert len(text) <= cap
    assert text.startswith("OUTLOOK Sun 11/8:")
    assert text.endswith(f"id {RECORD_ID}")


def test_a_cap_below_the_usable_minimum_is_refused_by_name():
    with pytest.raises(mob.BriefError) as excinfo:
        mob.render_text(load_record(), policy=policy(), max_chars=60)
    assert "max_chars" in str(excinfo.value) and "market_outlook" in str(excinfo.value)


def test_a_long_catalyst_list_is_dropped_from_the_end_before_the_tail():
    """The catalysts are also in the email; the action and the record id are not — so they are the last to go."""
    record = record_variant()
    record["catalysts"] = record["catalysts"] + [
        {"date_et": "2026-11-13", "time_et": "14:00", "event": "Synthetic auction", "impact": "MED",
         "consensus": None, "prior": None, "held_flag_per_account_id": []},
        {"date_et": "2026-11-13", "time_et": "16:00", "event": "Synthetic close", "impact": "LOW",
         "consensus": None, "prior": None, "held_flag_per_account_id": []},
    ]
    full = mob.render_text(record, policy=policy(), max_chars=600)
    tight = mob.render_text(record, policy=policy(), max_chars=200)
    assert len(tight) <= 200 < len(full)
    assert full.count(";") == 2          # three catalysts when there is room
    assert "Full report emailed." in full
    assert tight.count(";") == 1         # the tail goes first, then the third catalyst
    assert "Full report emailed." not in tight
    assert "Action: no new tranches" in tight
    assert tight.endswith(f"id {RECORD_ID}")


# ----------------------------------------------------------------------------- the email
def test_the_html_is_one_column_at_six_hundred_pixels_and_names_the_record():
    html = mob.render_html(load_record(), policy=policy())
    assert "max-width:600px" in html
    assert RECORD_ID in html
    assert "policy_version" not in html  # the footer prints the value, not the field name
    assert load_record()["policy_version"] in html
    assert "<script" not in html.lower()


def test_every_html_table_has_at_most_four_columns():
    """A five-column table cannot be read on a phone at 600 px, which is the whole point of the format."""
    html = mob.render_html(load_record(), policy=policy())
    for table in re.findall(r"<table.*?</table>", html, re.S):
        header_cells = table.count("<th ")
        assert 0 < header_cells <= 4, table[:200]
        assert table.count("<tr>") - 1 == table.count("<td ") // header_cells


def test_the_html_prints_unknown_with_its_reason_and_never_a_zero():
    html = mob.render_html(load_record(), policy=policy())
    assert "UNKNOWN" in html
    assert "no Sunday prints before 18:00 ET" in html
    # the futures row reads UNKNOWN in the sub-score cell, not 0.00
    assert re.search(r"Futures / overnight</td><td[^>]*>UNKNOWN</td>", html)
    assert not re.search(r"Futures / overnight</td><td[^>]*>[+-]?0\.00</td>", html)


def test_the_html_carries_all_eleven_sections_in_order():
    html = mob.render_html(load_record(), policy=policy())
    titles = ["The view", "Cross-asset scorecard", "Levels that matter", "This week&#x27;s catalysts",
              "Overnight so far", "Positioning", "What would change our view", "What we do", "Last week&#x27;s call",
              "Not measured"]
    # match the heading markup, not the bare words: "Positioning" is also a scorecard row
    positions = [html.index(f">{title}</h2>") for title in titles]
    assert positions == sorted(positions)


def test_the_html_escapes_operator_visible_text():
    record = record_variant()
    record["catalysts"][0]["event"] = "<b>CPI</b> & more"
    html = mob.render_html(record, policy=policy())
    assert "&lt;b&gt;CPI&lt;/b&gt; &amp; more" in html
    assert "<b>CPI</b>" not in html


# ----------------------------------------------------------------------------- telegram
def test_the_telegram_brief_has_every_section_and_folds_the_monday_plan():
    context = mob.BriefContext(monday_plan="NEXT-SESSION PLAN BRIEF\nPlan for the next session: Monday 2026-11-09")
    text = mob.render_telegram(load_record(), policy=policy(), context=context)
    for section in ("THE VIEW", "SCORECARD", "LEVELS", "CATALYSTS", "OVERNIGHT", "WHAT WOULD CHANGE THE VIEW",
                    "WHAT WE DO", "LAST WEEK'S CALL", "NOT MEASURED", "MONDAY PLAN"):
        assert section in text, section
    assert "NEXT-SESSION PLAN BRIEF" in text
    assert RECORD_ID in text


def test_the_telegram_brief_refuses_rather_than_cutting_a_long_message():
    small = dict(policy(), telegram_max_chars=200)
    with pytest.raises(mob.BriefError) as excinfo:
        mob.render_telegram(load_record(), policy=small)
    assert "over the 200-character policy cap" in str(excinfo.value)


def test_the_telegram_brief_is_plain_text_with_no_tags():
    """The raw Telegram sender carries no parse mode: an HTML tag would be shown to the operator as text."""
    text = mob.render_telegram(load_record(), policy=policy())
    assert not re.search(r"</?(b|i|u|s|code|pre|a|div|span|table|tr|td)\b", text)


# ----------------------------------------------------------------------------- keys and the subject
def test_the_dedupe_key_is_record_plus_channel():
    assert mob.dedupe_key(RECORD_ID, "email") == f"{RECORD_ID}:email"
    assert mob.dedupe_key(RECORD_ID, "TEXT") == f"{RECORD_ID}:text"


def test_a_dedupe_key_that_cannot_fit_the_column_is_refused_not_truncated():
    with pytest.raises(mob.BriefError):
        mob.dedupe_key("outlook:2026-11-08:sunday:1" + "-" * 90, "telegram")


def test_the_subject_names_the_day_the_band_and_the_confidence():
    assert mob.subject(load_record(), policy()) == "Trade AI Outlook - Sun 2026-11-08 - DEFENSIVE (S -21, conf LOW)"


# ----------------------------------------------------------------------------- CIO row
def test_the_cio_row_is_one_stance_with_a_stable_id():
    record = load_record()
    first = mob.cio_decision_row(record, policy())
    second = mob.cio_decision_row(record, policy())
    assert first["decision_id"] == second["decision_id"] == "cio-outlook-2026-11-08-sunday-1"
    assert first["symbol"] == "MARKET"
    assert first["strategy_type"] == "market_outlook"
    assert first["group_id"] == RECORD_ID
    assert first["action"] == record["band"]
    assert first["confidence_calibrated"] == pytest.approx(record["confidence"]["value"])
    assert len(first["supporting_signals"]) == mob.CATEGORY_COUNT
    assert first["metadata"]["broker_authority"].startswith("none")


def test_the_brief_reaches_no_broker():
    """MBI_BEHAVIOR = 0: the renderers and the lane contain no order path at all."""
    for path in (ROOT / "scripts" / "lib" / "market_outlook_brief.py", ROOT / "scripts" / "market_outlook_brief.py"):
        source = path.read_text(encoding="utf-8")
        for token in ("place_order", "submit_order", "cancel_order", "alpaca", "schwab", "broker_client"):
            assert token not in source.lower(), (path.name, token)


# ----------------------------------------------------------------------------- the plan
def test_a_delivered_channel_is_skipped_and_a_failed_one_is_retried():
    record = load_record()
    plans = mob.plan_channels(record, policy=policy(), channels=["email", "telegram"],
                              existing={"email": "sent", "telegram": "failed"})
    by_channel = {plan.channel: plan for plan in plans}
    assert by_channel["email"].action == "skip" and "already delivered" in by_channel["email"].reason
    assert by_channel["telegram"].action == "send"


def test_the_text_is_not_sent_on_a_daily_record():
    record = record_variant(mode="daily")
    plan = mob.plan_channels(record, policy=policy(), channels=["text"])[0]
    assert plan.action == "skip" and "not a text mode" in plan.reason


def test_the_text_is_sent_on_a_band_move_into_risk_off():
    record = record_variant(mode="daily", band="RISK-OFF", prior_band="DEFENSIVE")
    record["actions_template"]["band"] = "RISK-OFF"
    plan = mob.plan_channels(record, policy=policy(), channels=["text"])[0]
    assert plan.action == "send"


def test_the_text_is_skipped_when_the_class_is_switched_off():
    plan = mob.plan_channels(load_record(), policy=policy(), channels=["text"], text_class_enabled=False)[0]
    assert plan.action == "skip" and "switched off" in plan.reason


# ----------------------------------------------------------------------------- the delivery walk
def _deliver(record, policies, plans, sender, rows=None):
    rows = {} if rows is None else rows
    calls: list = []

    def write(entry):
        rows[entry["dedupe_key"]] = entry

    def send(*args, **kwargs):
        calls.append(kwargs)
        return sender(*args, **kwargs)

    outcome = mob.deliver_channels(
        record, policy=policies, plans=plans, senders={"email": send, "telegram": send, "text": send},
        read_status=lambda key: (rows.get(key) or {}).get("status"), write_log=write)
    return outcome, rows, calls


def test_a_second_run_through_the_same_record_sends_nothing_and_keeps_the_receipt():
    record = load_record()
    policies = policy()
    plans = mob.plan_channels(record, policy=policies, channels=["email"])

    def ok(*_a, **_k):
        return {"ok": True, "status": "sent", "provider_id": "msg-1",
                "detail": {"sent_at": "2026-11-09T01:00:00+00:00", "summary": RECORD_ID}}

    first, rows, calls = _deliver(record, policies, plans, ok)
    assert [r["status"] for r in first["results"]] == ["sent"]
    key = mob.dedupe_key(RECORD_ID, "email")
    assert rows[key]["status"] == "sent" and rows[key]["payload"]["provider_id"] == "msg-1"

    second, rows_after, calls_after = _deliver(record, policies, plans, ok, rows=rows)
    assert [r["status"] for r in second["results"]] == ["deduped"]
    assert len(calls_after) == 0
    # the row that proves the first delivery is untouched
    assert rows_after[key]["status"] == "sent" and rows_after[key]["payload"]["provider_id"] == "msg-1"


def test_a_failed_channel_records_failed_and_is_retried_on_the_next_run():
    record = load_record()
    policies = policy()
    plans = mob.plan_channels(record, policy=policies, channels=["telegram"])

    def fail(*_a, **_k):
        return {"ok": False, "status": "failed", "error": "gateway refused"}

    first, rows, _calls = _deliver(record, policies, plans, fail)
    key = mob.dedupe_key(RECORD_ID, "telegram")
    assert first["results"][0]["status"] == "failed" and rows[key]["status"] == "failed"

    def ok(*_a, **_k):
        return {"ok": True, "status": "sent", "provider_id": "tg-9"}

    second, rows_after, calls_after = _deliver(record, policies, plans, ok, rows=rows)
    assert second["results"][0]["status"] == "sent"
    assert len(calls_after) == 1
    assert rows_after[key]["status"] == "sent"


def test_a_sender_that_raises_fails_one_channel_without_stopping_the_others():
    record = load_record()
    policies = policy()
    plans = mob.plan_channels(record, policy=policies, channels=["email", "telegram"])
    rows: dict[str, dict] = {}

    def email(*_a, **_k):
        raise RuntimeError("gog exploded")

    def telegram(*_a, **_k):
        return {"ok": True, "status": "sent", "provider_id": "tg-1"}

    outcome = mob.deliver_channels(record, policy=policies, plans=plans,
                                   senders={"email": email, "telegram": telegram},
                                   read_status=lambda key: (rows.get(key) or {}).get("status"),
                                   write_log=lambda entry: rows.__setitem__(entry["dedupe_key"], entry))
    statuses = {r["channel"]: r["status"] for r in outcome["results"]}
    assert statuses == {"email": "failed", "telegram": "sent"}


# ----------------------------------------------------------------------------- the class row (D1)
def test_the_class_row_is_on_and_carries_three_hundred_characters():
    doc = json.loads((ROOT / "config" / "critical_text_classes.json").read_text(encoding="utf-8"))
    row = doc["classes"]["market_outlook"]
    assert row["enabled"] is True
    assert row["max_chars"] == 300
    loaded = ct.load_policy(ROOT / "config" / "critical_text_classes.json")
    assert ct.class_max_chars(loaded, "market_outlook") == 300


def test_a_class_without_its_own_cap_keeps_the_hundred_and_sixty_default():
    loaded = ct.load_policy(ROOT / "config" / "critical_text_classes.json")
    assert ct.class_max_chars(loaded, "market_event") == ct.MAX_TEXT_CHARS
    assert ct.class_max_chars(loaded, "not_a_class") == ct.MAX_TEXT_CHARS
    assert ct.class_max_chars({"classes": {"x": {"max_chars": "junk"}}}, "x") == ct.MAX_TEXT_CHARS


def test_the_outlook_body_is_sent_whole_and_checked():
    text = mob.render_text(load_record(), policy=policy(), max_chars=300)
    assert ct.format_text({"alert_class": "market_outlook", "body": text}, max_chars=300) == text
    with pytest.raises(ct.CriticalTextError) as over:
        ct.format_text({"alert_class": "market_outlook", "body": text}, max_chars=160)
    assert "over the 160-character cap" in str(over.value)
    with pytest.raises(ct.CriticalTextError) as label:
        ct.format_text({"alert_class": "market_outlook", "body": "S -21 DEFENSIVE"}, max_chars=300)
    assert "must start with its label" in str(label.value)
    with pytest.raises(ct.CriticalTextError) as link:
        ct.format_text({"alert_class": "market_outlook", "body": "OUTLOOK see https://example.invalid/x"}, max_chars=300)
    assert "may not carry a link" in str(link.value)


def test_the_primitive_carries_the_outlook_sentence_to_every_line_once(tmp_path):
    contact = tmp_path / "operator_contact.json"
    contact.write_text(json.dumps({"critical_sms_email_gateways": ["15550000009@example.invalid"]}), encoding="utf-8")
    config = tmp_path / "classes.json"
    config.write_text((ROOT / "config" / "critical_text_classes.json").read_text(encoding="utf-8"), encoding="utf-8")
    state = tmp_path / "state.json"
    text = mob.render_text(load_record(), policy=policy(), max_chars=300)
    sent: list[dict] = []

    def sender(subject, body, to=None, attachments=None):
        sent.append({"body": body, "to": to})
        return True

    event = {"alert_class": "market_outlook", "event_id": RECORD_ID, "body": text}
    first = ct.send_critical_text(event, sender=sender, contact_path=contact, config_path=config, state_path=state)
    assert first["sent"] is True and first["text"] == text and len(sent) == 1
    second = ct.send_critical_text(event, sender=sender, contact_path=contact, config_path=config, state_path=state,
                                   now=datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc))
    assert second["sent"] is False and "already texted" in second["reason"]
    assert len(sent) == 1


# ----------------------------------------------------------------------------- email html body
def test_the_email_sender_passes_the_html_body_to_gog(monkeypatch):
    captured: dict = {}

    class Result:
        returncode = 0
        stdout = '{"id": "18c0ffee0000000001"}'
        stderr = ""

    def run(args, **_kwargs):
        captured["args"] = args
        return Result()

    monkeypatch.setattr(email_notifier, "_get_keyring_password", lambda: "pw")
    monkeypatch.setattr(email_notifier, "_gog_bin", lambda: "/usr/bin/gog")
    monkeypatch.setattr(email_notifier.subprocess, "run", run)
    result = email_notifier.send_email_detailed("subject", "plain body", to="nobody@example.invalid",
                                                html="<p>html body</p>")
    assert result == {"ok": True, "provider_id": "18c0ffee0000000001", "error": None}
    args = captured["args"]
    assert "--body-html" in args and "<p>html body</p>" in args
    assert args[args.index("--body") + 1] == "plain body"


def test_the_plain_send_email_still_returns_a_bool(monkeypatch):
    monkeypatch.setattr(email_notifier, "_get_keyring_password", lambda: "")
    assert email_notifier.send_email("subject", "body") is False
