"""LQ-20261107-307: a torn final credit-journal record no longer switches the Anthropic lane off.

2026-11-03T14:00:31Z (disk full): ``anthropic_credit.jsonl`` was left ending in a 21-byte unterminated fragment
after 18,633 complete rows. ``CreditBook._read`` raised CREDIT_UNAVAILABLE on it, so every process saw the lane
off (and /v3/prospectus with it) for four days. Three changes, each pinned here:

* the reader skips ONLY a torn final record; damage above it still fails closed;
* ``_append`` cuts its own partial row back when the write or fsync fails (the writer that tore it);
* the next writer archives a torn tail beside the journal before appending, so no row is glued onto it.

Fixtures only: synthetic policy, tmp_path journals, the diagnostic sender stubbed. No network, no real journal.
"""
from __future__ import annotations

import errno
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import anthropic_credit as ac  # noqa: E402
from scripts.lib import jsonl_tail  # noqa: E402
from scripts.lib.anthropic_credit import CreditBook, CreditDenied  # noqa: E402

LIVE = json.loads((ROOT / "config/anthropic_credit_policy.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)
FRAGMENT = b'{"at":"2026-11-03T14:'  # the live fragment's shape: 21 bytes, no newline


def policy():
    return dict(deepcopy(LIVE), enabled=True, promotion_id="synthetic-lq307", credit_usd="200",
                total_cap_usd="190", daily_cap_usd="10", daily_cap_overrides=[], tier_daily_cap_shares=None,
                starts_at="2026-11-01T00:00:00Z", expires_at="2027-06-01T00:00:00Z",
                per_call_caps_usd={t: "5.00" for t in ("bulk", "mid", "standard", "high", "highest",
                                                       "long_form", "premium")},
                emergency_process_caps=None,
                renewal={"mode": "one_time", "monthly_allowance_usd": "190", "renews_on_day": None})


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    reports = []
    monkeypatch.setattr(jsonl_tail, "report", lambda path, n, **kw: reports.append((Path(path).name, n, kw)))
    return reports


def tear(book: CreditBook, fragment: bytes = FRAGMENT) -> None:
    with book.path.open("ab") as fh:
        fh.write(fragment)


def test_snapshot_reads_every_complete_row_above_a_torn_tail(tmp_path, quiet):
    book = CreditBook(tmp_path, policy())
    book.reserve("a", "proc", Decimal("0.10"), tier="bulk", now=NOW)
    book.settle("a", Decimal("0.04"), now=NOW)
    tear(book)
    snap = book.snapshot(now=NOW)
    assert snap["status"] == "OK"
    assert snap["credit_used_usd"] == "0.04" and snap["settled_calls"] == 1
    assert quiet and quiet[0][1] == len(FRAGMENT)
    assert book.path.read_bytes().endswith(FRAGMENT)  # a read never writes


def test_a_torn_settle_keeps_its_reserve_holding_the_full_projection(tmp_path):
    # The torn row is the most recent write: a settle that raised. The reserve it would have closed stays open
    # and keeps holding its projected amount, so skipping the fragment can never under-count spend.
    book = CreditBook(tmp_path, policy())
    book.reserve("a", "proc", Decimal("0.30"), tier="bulk", now=NOW)
    settle_row = json.dumps({"event": "settle", "actual": "0.05"}).encode()
    tear(book, settle_row[: len(settle_row) // 2])
    snap = book.snapshot(now=NOW)
    assert snap["reserved_usd"] == "0.30" and snap["open_reservations"] == 1


def test_the_next_write_archives_the_fragment_and_keeps_the_chain(tmp_path):
    book = CreditBook(tmp_path, policy())
    book.reserve("a", "proc", Decimal("0.10"), tier="bulk", now=NOW)
    tear(book)
    book.reserve("b", "proc", Decimal("0.10"), tier="bulk", now=NOW)
    archives = list(book.path.parent.glob("anthropic_credit.jsonl.corrupt-tail-*"))
    assert [a.read_bytes() for a in archives] == [FRAGMENT]
    rows = book._read()
    assert [r["sequence"] for r in rows] == [1, 2] and rows[1]["previous"] == rows[0]["checksum"]
    assert book.snapshot(now=NOW)["reserved_usd"] == "0.20"


@pytest.mark.parametrize("damage", [b"{not json}\n", b'{"broken":\n'])
def test_damage_above_the_last_line_still_fails_closed(tmp_path, damage):
    book = CreditBook(tmp_path, policy())
    book.reserve("a", "proc", Decimal("0.10"), tier="bulk", now=NOW)
    with book.path.open("ab") as fh:
        fh.write(damage)
    tear(book)
    for call in (lambda: book.snapshot(now=NOW),
                 lambda: book.reserve("b", "proc", Decimal("0.10"), tier="bulk", now=NOW)):
        with pytest.raises(CreditDenied, match="CREDIT_UNAVAILABLE"):
            call()


def test_a_journal_that_is_only_a_fragment_fails_closed(tmp_path):
    book = CreditBook(tmp_path, policy())
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_bytes(FRAGMENT)
    with pytest.raises(CreditDenied, match="CREDIT_UNAVAILABLE"):
        book.snapshot(now=NOW)


@pytest.mark.parametrize("fail_at", ["write", "fsync"])
def test_a_failed_append_cuts_its_partial_row_back(tmp_path, monkeypatch, fail_at):
    book = CreditBook(tmp_path, policy())
    book.reserve("a", "proc", Decimal("0.10"), tier="bulk", now=NOW)
    before = book.path.read_bytes()
    real_write, real_fsync = ac.os.write, ac.os.fsync
    state = {"armed": True}

    def short_write(fd, data):
        if state["armed"]:
            state["armed"] = False
            real_write(fd, data[:17])  # part of the row lands, then the disk is full
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(fd, data)

    def failing_fsync(fd):
        if state["armed"] and fail_at == "fsync":
            state["armed"] = False
            raise OSError(errno.EIO, "I/O error")
        return real_fsync(fd)

    if fail_at == "write":
        monkeypatch.setattr(ac.os, "write", short_write)
    else:
        monkeypatch.setattr(ac.os, "fsync", failing_fsync)
    with pytest.raises(CreditDenied, match="CREDIT_UNAVAILABLE"):
        book.reserve("b", "proc", Decimal("0.10"), tier="bulk", now=NOW)
    assert book.path.read_bytes() == before  # no torn row left behind
    monkeypatch.setattr(ac.os, "write", real_write)
    monkeypatch.setattr(ac.os, "fsync", real_fsync)
    book.reserve("b", "proc", Decimal("0.10"), tier="bulk", now=NOW)
    assert book.snapshot(now=NOW)["reserved_usd"] == "0.20"
    assert not list(book.path.parent.glob("*.corrupt-tail-*"))
