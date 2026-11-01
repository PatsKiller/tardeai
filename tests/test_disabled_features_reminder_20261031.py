"""A feature switched off on purpose carries a review date, and the reminder fires when it passes.

Operator 2026-10-31: "there needs to be a reminder to switch it back on. We just don't want to leave it off".
Firing test: scripts/check_disabled_features.py sends its P2 through an injected sender (never the real one).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts import check_disabled_features as chk
from scripts.lib import disabled_features as df
from scripts.lib import market_risk_projection as proj
from scripts.lib.market_risk import cio_context

COVERS = ["scripts/check_disabled_features.py"]

BLOCK = {
    "reason": "test reason",
    "disabled_at": "2026-10-31",
    "review_by": "2026-11-07",
    "owner": "coordinator",
    "reenable_plan": "review passes",
}


def _cfg(tmp_path: Path, name: str, blk: dict | None, *, json_file: bool = False) -> Path:
    d = tmp_path / "config"
    d.mkdir(exist_ok=True)
    body = {"schema": "X@v1", "enabled": True}
    if blk is not None:
        body["disabled_until"] = blk
    p = d / (name + (".json" if json_file else ".yaml"))
    p.write_text(json.dumps(body) if json_file else __import__("yaml").safe_dump(body), encoding="utf-8")
    return d


def test_curation_config_carries_the_reminder():
    e = df.entry_for(df.CONFIG_DIR / "market_risk_curation.yaml", today=date(2026, 10, 31))
    assert e and e["review_by"] == "2026-11-07" and e["owner"] == "coordinator" and not e.get("error")
    assert "BLUE/YELLOW/GREEN" in e["reenable_plan"]


def test_note_and_overdue_boundary():
    e = df.entry_for(df.CONFIG_DIR / "market_risk_curation.yaml", today=date(2026, 11, 7))
    assert df.note(e, "curation") == "curation: OFF — pending review, due 2026-11-07"
    late = df.entry_for(df.CONFIG_DIR / "market_risk_curation.yaml", today=date(2026, 11, 8))
    assert late["overdue"] and df.note(late, "curation").startswith("curation: OFF — OVERDUE since 2026-11-07")
    assert df.note(None, "curation") == "curation: ON"


def test_projection_and_ask_facts_show_the_status():
    mr = proj.build(None, None)
    assert mr["curation"]["state"] == "OFF" and "due 2026-11-07" in mr["curation"]["note"]
    facts = cio_context.ask_facts(mr)
    assert facts["curation"]["note"] == mr["curation"]["note"]


def test_scan_finds_yaml_and_json_and_flags_malformed(tmp_path):
    d = _cfg(tmp_path, "a_feature", BLOCK)
    _cfg(tmp_path, "b_feature", {**BLOCK, "review_by": "2026-10-01"}, json_file=True)
    _cfg(tmp_path, "c_broken", {"reason": "x"})
    _cfg(tmp_path, "d_plain", None)
    found = {e["name"]: e for e in df.scan(d, today=date(2026, 10, 31))}
    assert set(found) == {"a_feature", "b_feature", "c_broken"}
    assert not found["a_feature"]["overdue"] and found["b_feature"]["overdue"]
    assert found["c_broken"]["overdue"] and "missing" in found["c_broken"]["error"]


def test_firing_overdue_sends_one_p2_through_the_sender(tmp_path):
    d = _cfg(tmp_path, "late_feature", {**BLOCK, "review_by": "2026-10-01"})
    sent: list[tuple] = []

    def sender(msg, **kw):
        sent.append((msg, kw))
        return True

    rc = chk.run(apply=True, config_dir=d, today=date(2026, 10, 31), sender=sender)
    assert rc == 3 and len(sent) == 1
    msg, kw = sent[0]
    assert "Disabled feature overdue" in msg and "late_feature" in msg
    assert kw["priority"] == "P2" and kw["dedupe_minutes"] == 1380 and kw["producer"] == chk.PRODUCER
    assert "2026-10-31" in msg  # the date in the body keeps the next day's page from being deduped (review F9)


def test_nothing_overdue_sends_nothing(tmp_path):
    d = _cfg(tmp_path, "fine", BLOCK)
    sent = []
    assert chk.run(apply=True, config_dir=d, today=date(2026, 10, 31), sender=lambda m, **k: sent.append(m)) == 0
    assert sent == []


def test_dry_run_never_sends(tmp_path, monkeypatch):
    d = _cfg(tmp_path, "late", {**BLOCK, "review_by": "2026-10-01"})
    monkeypatch.setattr(chk, "deliver", lambda *a, **k: pytest.fail("dry run must not deliver"))
    assert chk.run(apply=False, config_dir=d, today=date(2026, 10, 31)) == 3


def test_harness_refuses_the_real_sender(monkeypatch):
    from scripts import telegram_alert as ta

    calls = []
    monkeypatch.setattr(ta, "send_telegram", lambda *a, **k: calls.append(a) or True)
    monkeypatch.setenv("TRADE_AI_CI", "1")
    assert chk.deliver("x") is False
    assert calls == [], "the real sender was reached under a test harness"


# ── review #2399, F9-F13 ───────────────────────────────────────────────────────────────────────────────────────


def test_f9_body_carries_the_day_so_each_day_differs():
    e = df.entry_for(df.CONFIG_DIR / "market_risk_curation.yaml", today=date(2026, 11, 8))
    a, b = chk.message_for(e, date(2026, 11, 8)), chk.message_for(e, date(2026, 11, 9))
    assert "2026-11-08" in a and "2026-11-09" in b and a != b


def test_f10_step_is_declared_off_and_the_table_validates():
    from scripts import health_tick as ht

    table = ht.load_table(Path(df.PROJECT_ROOT) / "config" / "health_tick_steps.json")
    step = next(s for s in table["steps"] if s["step_id"] == "disabled-features-reminder")
    assert step["enabled"] is False and step["command"][1:] == ["scripts/check_disabled_features.py", "--apply"]
    assert table["steps"][-1]["step_id"] == "pipeline-watchdog"
    from datetime import datetime, timezone

    nine = datetime(2026, 11, 9, 9, 5, tzinfo=timezone.utc)
    assert ht.step_is_due(step, nine, 5) is False  # off until the operator's word
    assert ht.step_is_due(dict(step, enabled=True), nine, 5) is True


def test_f10_enabled_must_be_a_bool(tmp_path):
    from scripts import health_tick as ht

    t = json.loads((Path(df.PROJECT_ROOT) / "config" / "health_tick_steps.json").read_text())
    t["steps"][0]["enabled"] = "no"
    p = tmp_path / "s.json"
    p.write_text(json.dumps(t))
    with pytest.raises(ValueError, match="enabled must be"):
        ht.load_table(p)


def test_f11_status_comes_from_the_curation_config(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    real = (Path(df.PROJECT_ROOT) / "config" / "market_risk_curation.yaml").read_text()
    (d / "market_risk_curation.yaml").write_text(real)
    assert proj.curation_status(d)["note"] == "curation: OFF — pending review, due 2026-11-07"
    on = real.replace("skip_tiers: [RED, ORANGE, YELLOW, BLUE, GREEN, NONE]", "skip_tiers: [ORANGE, RED]")
    (d / "market_risk_curation.yaml").write_text(on)
    st = proj.curation_status(d)
    assert (
        st["state"] == "ON"
        and st["tiers_on"] == ["BLUE", "GREEN", "YELLOW"]
        and "review block still present" in st["note"]
    )
    import yaml

    doc = yaml.safe_load(real)
    doc.pop("disabled_until")
    (d / "market_risk_curation.yaml").write_text(yaml.safe_dump(doc))
    st = proj.curation_status(d)
    assert st["state"] == "OFF" and st["note"] == "curation: OFF — no valid review date set" and st["overdue"]


@pytest.mark.parametrize(
    "name,body",
    [
        ("a.yaml", "disabled_until: [1, 2]\n"),
        ("b.yaml", "disabled_until:\n"),
        ("c.yaml", "disabled_until:\n  review_by: 2026-13-45\n"),
        ("e.yaml", b"\xff\xfe\x00bad"),
        ("f.yaml", "a:\n\t- b\n"),
        ("g.yaml", "x: !!python/object/apply:os.system ['echo PWNED']\n"),
        ("h.json", '{"a":' * 5000 + "1" + "}" * 5000),
        ("i.yaml", "a: " + "[" * 5000 + "]" * 5000 + "\n"),
    ],
)
def test_f12_one_bad_file_never_stops_the_scan(tmp_path, name, body):
    d = _cfg(tmp_path, "good_feature", {**BLOCK, "review_by": "2026-10-01"})
    (d / name).write_bytes(body if isinstance(body, bytes) else body.encode())
    names = {e["name"] for e in df.scan(d, today=date(2026, 10, 31))}
    assert "good_feature" in names


def test_f12_directories_and_broken_links_are_skipped(tmp_path):
    d = _cfg(tmp_path, "good_feature", BLOCK)
    (d / "dir.json").mkdir()
    (d / "broken.yaml").symlink_to(tmp_path / "nope.yaml")
    assert [e["name"] for e in df.scan(d, today=date(2026, 10, 31))] == ["good_feature"]


def test_f13_dotfiles_are_never_read_and_errors_carry_no_block_text(tmp_path):
    d = _cfg(tmp_path, "x", None)
    (d / ".hidden.json").write_text('{"disabled_until": {"reason": "SECRET-TOKEN-abc123", "review_by": "2020-01-01"}}')
    (d / ".env").write_text("disabled_until: SECRET\n")
    (d / "leak.json").write_text('{"disabled_until": {"reason": "SECRET-TOKEN-xyz", "review_by": "bad"}}')
    found = df.scan(d, today=date(2026, 10, 31))
    assert [e["file"] for e in found] == ["leak.json"]
    e = found[0]
    assert set(e) == {"name", "file", "review_by", "error", "overdue"}
    assert "SECRET" not in json.dumps(e) and "SECRET" not in chk.message_for(e, date(2026, 10, 31))


def test_f12_a_name_that_is_not_text_falls_back_to_the_file_stem(tmp_path):
    d = _cfg(tmp_path, "stem_name", {**BLOCK, "name": {"x": 1}})
    assert df.scan(d, today=date(2026, 10, 31))[0]["name"] == "stem_name"
