"""A state directory that exists twice must be reported. LINKED is the only OK.

On 2026-08-27 CURRENT/data/{portfolios/state,runtime} were linked to
persistent-state. The dev tree the 344 cron producers run from was not. For
eighteen days the producers wrote a copy nothing served, 40 of the 192 state
files the API reads were served stale while a fresh copy sat next door, and
79 append-only ledgers grew on both sides so no "newest wins" could heal it.
The health agent read the age of one copy and scored 75.

The defect is the second directory, not the age of any file. `check_dir` and
`diff_trees` are pure over paths, so these run against tmp trees, and the
firing test proves the alert reaches the transport and interrupts.
"""

from __future__ import annotations

import json
import os
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_served_copy_split as scs  # noqa: E402

# Declares to the C1 alarm gate that this file's send_telegram site is exercised.
COVERS = ["scripts/check_served_copy_split.py"]


def _tree(root: Path, files: dict[str, tuple[str, float]]) -> Path:
    """Build data/<sub>/... under root. files: rel → (content, age_hours)."""
    for rel, (content, age_h) in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        t = time.time() - age_h * 3600
        os.utime(p, (t, t))
    return root


@pytest.fixture
def linked(tmp_path):
    """The healthy shape: dev/data/runtime is a symlink onto the served store."""
    store = _tree(tmp_path / "persistent-state", {"data/runtime/x.json": ("{}", 1)})
    dev = tmp_path / "dev"
    (dev / "data").mkdir(parents=True)
    (dev / "data" / "runtime").symlink_to(store / "data" / "runtime")
    served = tmp_path / "CURRENT"
    (served / "data").mkdir(parents=True)
    (served / "data" / "runtime").symlink_to(store / "data" / "runtime")
    return dev, served


@pytest.fixture
def split(tmp_path):
    """The 2026-08-27 → 09-13 shape: two real directories, drifted."""
    dev = _tree(tmp_path / "dev", {
        "data/runtime/sector_momentum_latest.json": ('{"fresh":1}', 0.1),
        "data/runtime/only_dev.json": ("{}", 5),
        "data/runtime/cases.jsonl": ("a\nb\nc\n", 0.5),
    })
    served = _tree(tmp_path / "CURRENT", {
        "data/runtime/sector_momentum_latest.json": ('{"stale":1}', 448),
        "data/runtime/only_served.json": ("{}", 5),
        "data/runtime/cases.jsonl": ("a\nd\n", 300),
    })
    return dev, served


# ── the defect this gate exists for ──────────────────────────────────────────


def test_linked_directories_are_the_only_ok(linked):
    dev, served = linked
    f = scs.check_dir("runtime", dev, served)
    assert f["status"] == "LINKED"
    assert f["dev"] == f["served"]


def test_two_real_directories_are_split_even_if_identical(tmp_path):
    """Identity is the question, not content. Identical today drifts tomorrow."""
    dev = _tree(tmp_path / "dev", {"data/runtime/x.json": ("{}", 1)})
    served = _tree(tmp_path / "CURRENT", {"data/runtime/x.json": ("{}", 1)})
    f = scs.check_dir("runtime", dev, served)
    assert f["status"] == "SPLIT"
    assert f["differ"] == 0


def test_split_counts_drift_and_names_the_worst_file(split):
    dev, served = split
    f = scs.check_dir("runtime", dev, served)
    assert f["status"] == "SPLIT"
    assert f["in_both"] == 2 and f["differ"] == 2
    assert f["only_a"] == 1 and f["only_b"] == 1
    assert f["ledgers_diverged"] == 1
    assert f["worst"][0]["file"] == "sector_momentum_latest.json"
    assert f["worst"][0]["gap_hours"] > 400
    assert "1 append-only ledgers" in f["detail"]


def test_missing_side_is_not_a_pass(tmp_path):
    dev = _tree(tmp_path / "dev", {"data/runtime/x.json": ("{}", 1)})
    served = tmp_path / "CURRENT"
    served.mkdir()
    f = scs.check_dir("runtime", dev, served)
    assert f["status"] == "MISSING"
    assert "served side" in f["detail"]


def test_mtime_within_tolerance_and_same_size_is_not_drift(tmp_path):
    dev = _tree(tmp_path / "dev", {"data/runtime/x.json": ("{}", 1)})
    served = _tree(tmp_path / "CURRENT", {"data/runtime/x.json": ("{}", 1)})
    p = served / "data/runtime/x.json"
    t = (dev / "data/runtime/x.json").stat().st_mtime + scs.MTIME_TOLERANCE_S / 2
    os.utime(p, (t, t))
    assert scs.diff_trees(dev / "data/runtime", served / "data/runtime")["differ"] == 0


def test_declared_directories_are_every_served_store():
    """All seven directories CURRENT links into persistent-state. The first version
    declared three; Phase 0 of the One Source of Truth plan found the other four
    were split too (audit 24 dev-only files, state 13, paper_trading 1)."""
    assert set(scs.SPLIT_DIRS) == {"audit", "cio", "health", "paper_trading", "portfolios/state", "runtime", "state"}


# ── the archive tripwire ─────────────────────────────────────────────────────


def test_tripwire_is_quiet_when_nothing_references_the_archive(tmp_path):
    repo = tmp_path / "repo"; (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "ok.py").write_text("x = 1\n")
    assert scs.archive_tripwire("/arch/served_copy_split", repo=repo, crontab_text="* * * * * echo hi\n", unit_dir=tmp_path / "nounits") == []


def test_tripwire_fires_on_repo_crontab_and_unit_references(tmp_path):
    repo = tmp_path / "repo"; (repo / "scripts").mkdir(parents=True); units = tmp_path / "units"; units.mkdir()
    (repo / "scripts" / "bad.py").write_text('p = "/arch/served_copy_split/dev/runtime/x.json"\n')
    (units / "x.service").write_text("ExecStart=/bin/cat /arch/served_copy_split/dev/cio/a.jsonl\n")
    hits = scs.archive_tripwire("/arch/served_copy_split", repo=repo, crontab_text="5 * * * * cat /arch/served_copy_split/served/y\n", unit_dir=units)
    assert sorted(h["where"] for h in hits) == ["crontab", "repo", "systemd"]


def test_tripwire_finding_interrupts(wired, monkeypatch):
    monkeypatch.setattr(scs, "archive_tripwire", lambda *a, **k: [{"where": "crontab", "ref": "line 12"}])
    scs._alert([{"dir": "archive_tripwire", "status": "TRIPPED", "detail": "1 live reference(s) to the reconcile archive", "trips": [{"where": "crontab", "ref": "line 12"}]}])
    body = wired.sent[0]
    assert "ARCHIVE TRIPWIRE" in body and "crontab: line 12" in body
    from telegram_alert_router import classify_alert
    assert classify_alert(body) == "P0_INTERRUPT"


# ── main: exit code and receipt ──────────────────────────────────────────────


def test_main_exits_1_on_split_and_writes_receipt(split, monkeypatch, capsys):
    dev, served = split
    monkeypatch.setattr(scs, "archive_tripwire", lambda *a, **k: [])
    monkeypatch.setattr(scs, "SPLIT_DIRS", ("runtime",))
    monkeypatch.setattr(scs, "PROJECT_ROOT", dev)
    monkeypatch.setattr(sys, "argv", ["x", "--dev-root", str(dev), "--served-root", str(served)])
    assert scs.main() == 1
    receipt = json.loads((dev / "data/runtime" / scs.RECEIPT_NAME).read_text())
    assert receipt["schema"] == scs.SCHEMA
    assert receipt["split"] >= 1
    assert "SPLIT:runtime" in receipt["split_items"]
    assert "[SPLIT  ] data/runtime" in capsys.readouterr().out


def test_main_exits_0_when_every_dir_is_linked(linked, monkeypatch, tmp_path):
    dev, served = linked
    # the other six dirs absent on both sides would be MISSING; declare only runtime here.
    monkeypatch.setattr(scs, "SPLIT_DIRS", ("runtime",))
    monkeypatch.setattr(scs, "archive_tripwire", lambda *a, **k: [])
    monkeypatch.setattr(scs, "PROJECT_ROOT", tmp_path / "receipts")
    monkeypatch.setattr(sys, "argv", ["x", "--dev-root", str(dev), "--served-root", str(served)])
    assert scs.main() == 0
    receipt = json.loads((tmp_path / "receipts/data/runtime" / scs.RECEIPT_NAME).read_text())
    assert receipt["split"] == 0 and receipt["split_items"] == []


def test_main_refuses_to_run_without_a_served_root(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x", "--dev-root", str(tmp_path), "--served-root", str(tmp_path / "nope")])
    assert scs.main() == 2


# ── the alarm fires, interrupts, and does not re-fire ────────────────────────


class _Capture:
    def __init__(self):
        self.sent: list[str] = []

    def send_telegram(self, message, **kwargs):
        self.sent.append(message)
        return True


@pytest.fixture
def wired(monkeypatch, tmp_path):
    cap = _Capture()
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = cap.send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(scs, "STATE_PATH", tmp_path / "state.json")
    return cap


def _split_findings():
    return [
        {"dir": "runtime", "status": "SPLIT", "dev": "/d", "served": "/s",
         "detail": "152 files differ (20 append-only ledgers grew on both sides), 26469 only in dev, 16 only in served",
         "worst": [{"file": "sector_momentum_latest.json", "gap_hours": 448.0}]},
        {"dir": "cio", "status": "LINKED", "dev": "/x", "served": "/x"},
    ]


def test_alarm_fires_names_the_split_and_interrupts(wired):
    scs._alert(_split_findings())
    assert len(wired.sent) == 1
    body = wired.sent[0]
    assert body.startswith("[PLATFORM_AVAILABILITY]")
    assert "data/runtime: SPLIT" in body
    assert "sector_momentum_latest.json" in body
    assert "Do NOT reconcile by hand" in body
    from telegram_alert_router import classify_alert
    assert classify_alert(body) == "P0_INTERRUPT"


def test_alarm_does_not_repeat_for_an_unchanged_split(wired):
    scs._alert(_split_findings())
    scs._alert(_split_findings())
    assert len(wired.sent) == 1


def test_recovery_is_announced_once(wired):
    scs._alert(_split_findings())
    scs._alert([{"dir": "runtime", "status": "LINKED"}, {"dir": "cio", "status": "LINKED"}])
    assert len(wired.sent) == 2
    assert "✅" in wired.sent[1] and "cleared" in wired.sent[1]
    scs._alert([{"dir": "runtime", "status": "LINKED"}, {"dir": "cio", "status": "LINKED"}])
    assert len(wired.sent) == 2


def test_a_send_failure_does_not_advance_state(monkeypatch, tmp_path, capsys):
    def _boom(message, **kwargs):
        raise RuntimeError("transport down")
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = _boom
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(scs, "STATE_PATH", tmp_path / "s.json")
    scs._alert(_split_findings())
    assert not (tmp_path / "s.json").exists()
    assert "state not advanced" in capsys.readouterr().err


def test_negative_control_a_link_check_that_only_reads_age_would_miss_this(split):
    """The health agent's failure mode: the dev copy is 6 minutes old, so an
    age check on the dev tree passes. The link check does not."""
    dev, served = split
    dev_age_h = (time.time() - (dev / "data/runtime/sector_momentum_latest.json").stat().st_mtime) / 3600
    assert dev_age_h < 1, "the fresh copy looks healthy on its own"
    assert scs.check_dir("runtime", dev, served)["status"] == "SPLIT"
