"""Stoplight `--dry-run` writes nothing: no row, no commit, no snapshot file, no send.

Live verification 2026-10-31 (agent_scratch/live-verify/MATRIX.md, #2322 row): `--dry-run` only suppressed the
Telegram send. record_transition still INSERTed into inverse_stoplight_transitions and committed, and the snapshot file
was rewritten, so a dry run consumed the transition and the next real 17:55 run saw prev == state_key and sent no card.

The fake connection below FAILS THE TEST on any INSERT/UPDATE/DELETE/CREATE or commit() while strict. A positive
control runs the same evaluation without dry run and proves the fake does see the writes. Hermetic: bars, holdings and
the desk snapshot are synthetic; no DB, no Schwab, no Telegram.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import defense_inverse_stoplights as dis  # noqa: E402

WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE")


class FakeCursor:
    def __init__(self, conn):
        self.connection = conn
        self.rowcount = 0
        self._last = ""

    def execute(self, sql, params=None):
        verb = sql.lstrip().split(None, 1)[0].upper()
        if verb in WRITE_VERBS:
            self.connection.writes.append(verb)
            if self.connection.strict:
                raise AssertionError(f"dry run executed a write: {' '.join(sql.split())[:120]}")
        self._last = sql
        self.rowcount = 1

    def fetchone(self):
        if "SELECT new_state FROM inverse_stoplight_transitions" in self._last:
            return ("AMBER",)  # differs from what the lights compute → a transition is due
        if "RETURNING" in self._last:
            return (7,)
        return None

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, strict: bool):
        self.strict, self.writes, self.commits, self.rollbacks = strict, [], 0, 0

    def commit(self):
        self.commits += 1
        if self.strict:
            raise AssertionError("dry run committed")

    def rollback(self):
        self.rollbacks += 1

    def cursor(self):
        return FakeCursor(self)


def _bars(n=80):
    out, px = [], 500.0
    for i in range(n):
        px *= 0.995  # steady decline: index under its averages
        out.append({"d": f"2026-{7 + i // 28:02d}-{1 + i % 28:02d}", "o": px, "h": px * 1.01, "l": px * 0.99, "c": px})
    return out


@pytest.fixture
def lane(monkeypatch, tmp_path):
    monkeypatch.setattr(dis, "SNAP", tmp_path / "inverse_stoplights_latest.json")
    monkeypatch.setattr(dis, "_bars", lambda cur, sym, n=80: _bars(n))
    monkeypatch.setattr(dis, "_bars_fresh", lambda bars, stale_days=None: True)
    holdings = {
        "as_of": "2099-01-01",
        "holdings": [{"symbol": "PSQ", "shares": 10, "cost_basis": 300.0, "price": 31.0, "account": "acct-x"}],
    }
    monkeypatch.setattr(dis, "_read_holdings", lambda: (holdings, "hash", True))
    monkeypatch.setattr(dis, "ROOT", tmp_path)  # desk snapshot unreadable → THESIS AMBER path, deterministic
    return tmp_path


def test_dry_run_writes_no_row_commits_nothing_and_leaves_the_snapshot(lane):
    conn = FakeConn(strict=True)
    out = dis.evaluate_all(conn.cursor(), conn, notify=False, dry_run=True)
    assert conn.writes == [] and conn.commits == 0
    assert conn.rollbacks == 1  # the session is rolled back (releases any FOR UPDATE lock)
    assert not (lane / "inverse_stoplights_latest.json").exists()
    assert out["candidates"], "the lights are still evaluated"
    would = out["would_write"]
    assert any("inverse_stoplight_transitions" in w for w in would), would
    assert any("inverse_position_cycles" in w for w in would), would


def test_positive_control_the_fake_sees_real_writes(lane):
    conn = FakeConn(strict=False)
    dis.evaluate_all(conn.cursor(), conn, notify=False, dry_run=False)
    assert "INSERT" in conn.writes and conn.commits > 0
    assert (lane / "inverse_stoplights_latest.json").exists()


def test_dry_run_still_previews_the_card_without_sending(lane, monkeypatch):
    sent = []
    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", lambda *a, **k: sent.append(a) or True)
    desk = lane / "data" / "runtime"
    desk.mkdir(parents=True)
    (desk / "defense_recommendations_latest.json").write_text(
        '{"data": {"groups": {"short_side": [{"title": "HEDGE QQQ exposure with PSQ"}]}}}'
    )  # the desk's own HEDGE card → THESIS GREEN, a notifiable transition
    conn = FakeConn(strict=True)
    out = dis.evaluate_all(conn.cursor(), conn, notify=True, dry_run=True)
    assert conn.writes == [] and conn.commits == 0 and sent == []
    assert out["notifications"], "the would-be cards are still rendered in dry run"
    assert all(n["sent"] is False for n in out["notifications"])
