"""An uninitialised inbound checkpoint must not read as "nothing has happened".

Measured 2026-09-05: `communication_inbound_checkpoint` held 0 rows while the
legacy poller's own file recorded update_id 113864091. The cutover created the
tables and never seeded them.

`get_checkpoint_offset()` returned 0 in that state. The poller then requests
`offset = 0 + 1`, Telegram replays its entire retained backlog, and
`claim_update(u)` denies none of it because `u <= 0` is false for every update.
Among that backlog are approve/reject callbacks.

Replay denial has therefore been inoperative since cutover — not failing, and
not reporting anything. It simply could never say no.

For this control a HIGHER offset is the safe direction: it denies more. So an
uninitialised checkpoint takes the highest value any source knows about.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms import inbound  # noqa: E402

LEGACY = 113864091


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMS_INBOUND_STATE_DIR", str(tmp_path))
    # No database: exercise the file/legacy path deterministically.
    monkeypatch.setattr(inbound, "_db_conn", lambda: None)
    return tmp_path


def _write_legacy(tmp_path: Path, value: int) -> None:
    (tmp_path / ".telegram_callback_offset").write_text(str(value), encoding="utf-8")


# ── the defect ──────────────────────────────────────────────────────────────

def test_an_uninitialised_checkpoint_adopts_the_legacy_offset(_isolated_state):
    """The incident: DB/file checkpoint empty, legacy file at 113864091."""
    _write_legacy(_isolated_state, LEGACY)
    assert inbound.get_checkpoint_offset() == LEGACY


def test_without_the_seed_every_old_update_would_be_replayable(_isolated_state):
    """Shows what offset 0 costs, in the terms that matter: denial."""
    _write_legacy(_isolated_state, LEGACY)
    offset = inbound.get_checkpoint_offset()
    # An update from before the cutover must be refused.
    assert inbound.claim_update(LEGACY - 5).already_processed is True
    assert offset >= LEGACY


def test_a_genuinely_new_update_is_still_claimable(_isolated_state):
    """The seed must not wall off real traffic — that would be a mute button."""
    _write_legacy(_isolated_state, LEGACY)
    assert inbound.claim_update(LEGACY + 1).already_processed is False


# ── the direction of the default ────────────────────────────────────────────

def test_the_highest_known_source_wins(_isolated_state):
    """A higher offset denies more, so it is the safe direction."""
    _write_legacy(_isolated_state, 500)
    assert inbound.get_checkpoint_offset() >= 500
    _write_legacy(_isolated_state, 900)
    assert inbound.get_checkpoint_offset() >= 900


def test_a_missing_legacy_file_is_not_an_error(_isolated_state):
    """No legacy file is a legitimate state — a clean install. It must yield 0
    rather than raising, because raising here would take the poller down."""
    assert inbound.get_checkpoint_offset() == 0


def test_an_unreadable_legacy_file_yields_zero_rather_than_raising(_isolated_state):
    (_isolated_state / ".telegram_callback_offset").write_text("not a number")
    assert inbound.get_checkpoint_offset() == 0


def test_the_seed_never_returns_a_negative_offset(_isolated_state):
    _write_legacy(_isolated_state, -42)
    assert inbound.get_checkpoint_offset() >= 0


# ── what this module must NOT do ────────────────────────────────────────────

def test_reading_the_legacy_file_does_not_write_it(_isolated_state):
    """The legacy path still owns that file. The two offsets converge because
    commit_checkpoint advances the DB one, not because this module edits the old
    one — two writers to a durable offset is how they diverge."""
    _write_legacy(_isolated_state, LEGACY)
    before = (_isolated_state / ".telegram_callback_offset").read_bytes()
    inbound.get_checkpoint_offset()
    inbound.get_checkpoint_offset()
    assert (_isolated_state / ".telegram_callback_offset").read_bytes() == before


def test_the_legacy_read_is_confined_to_the_seed_path():
    """It must inform an UNINITIALISED checkpoint only. Once the checkpoint is
    real, the legacy file is history and must not raise the committed offset."""
    import inspect
    src = inspect.getsource(inbound.get_checkpoint_offset)
    seeded = src.split("if row:", 1)[1]
    assert "_seed_offset()" in seeded
    # The committed value returned for a real row is the row, untouched.
    assert "return int(row[0])" in src
