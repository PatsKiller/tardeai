"""ANCHOR: LANE_OUTPUT_SIGNAL_PARSES_LQ1691_20261109 — a json_key signal must point at a JSON document.

LQ-20261107-1691. ``reconcile-watch-outcomes`` declared

    "output_signal": {"kind": "json_key", "key": "ok_at", "path": "logs/watch_outcomes.log"}

``observe_signal`` reads a ``json_key`` signal with ``json.loads(<whole file>)``. The declared path is a
plain-text cron log (``[watch-outcomes] …`` lines), so the read raises ``JSONDecodeError`` and the function
returns ``readable: false``. The supervisor breach detector reports an unreadable signal as NO_OUTPUT, and no
run — green or red — can ever clear it. Measured 2026-11-09: three OPEN ``reconcile-watch-outcomes:NO_OUTPUT``
breaches (11-07, 11-08, 11-09) quoting this exact JSONDecodeError, in a 2,766-row breach log.

The lane writes a LaneRunReceipt to ``<state_root>/data/runtime/reconcile-watch-outcomes_last.json``
(``scripts/lib/lane_last_receipt.py`` §receipt_path). ``json_key``/``ok_at`` over that receipt is the honest
declaration: a failed run carries ``ok_at: null`` and stays silent, while any successful run sets it.

These pins are hermetic: config files are read as text, ``observe_signal`` is called with an explicit
temporary root, and no ledger, database, network or clock is touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import lane_last_receipt as LLR  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ALLOWLIST = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
CONTRACTS = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))

WATCH = "reconcile-watch-outcomes"
RECEIPT = f"data/runtime/{WATCH}_last.json"


def _rows():
    return REGISTRY["lanes"] if isinstance(REGISTRY, dict) else REGISTRY


def _row(lane: str = WATCH) -> dict:
    return next(r for r in _rows() if r.get("lane_id") == lane)


def _entry(lane: str = WATCH) -> dict:
    return next(e for e in ALLOWLIST["lanes"] if e.get("lane_id") == lane)


def _contract(lane: str = WATCH) -> dict:
    return next(c for c in CONTRACTS["contracts"] if c.get("id") == lane) if "contracts" in CONTRACTS \
        else next(c for c in CONTRACTS["lanes"] if c.get("id") == lane)


def test_every_observable_json_key_signal_points_at_a_json_document():
    """A ``json_key`` signal is parsed whole; anything that is not a JSON document is unreadable forever.

    RETIRED rows are exempt: nothing observes them. Exactly one row failed this rule when it was written
    (``reconcile-watch-outcomes`` -> ``logs/watch_outcomes.log``); the guard is registry-wide so the class
    cannot come back.
    """
    bad = []
    for row in _rows():
        if str(row.get("state") or "").upper() == "RETIRED":
            continue
        sig = row.get("output_signal") or {}
        if sig.get("kind") != "json_key":
            continue
        path = str(sig.get("path") or "")
        if not path.endswith(".json"):
            bad.append((row.get("lane_id"), path))
    assert not bad, f"json_key output_signal over a non-JSON path (unreadable forever): {bad}"


def test_the_watch_signal_declares_the_receipt_the_script_writes():
    row = _row()
    assert row["output_signal"] == {"kind": "json_key", "path": RECEIPT, "key": "ok_at"}
    # The receipt path is not a naming convention guessed by hand: it is the path the writer uses.
    assert str(LLR.receipt_path(WATCH)).endswith(RECEIPT)
    # The allowlist must agree with the registry, or the dispatcher and the status read disagree.
    assert _entry()["output_signal"] == RECEIPT


def test_the_health_contract_evidence_names_the_receipt_not_the_text_log():
    contract = _contract()
    evidence = contract["evidence"]
    assert evidence["receipt"] == RECEIPT
    assert not any(str(v).startswith("logs/watch_outcomes.log") for v in evidence["verify"])


def _write_receipt(root: Path, ok_at) -> None:
    p = root / RECEIPT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": "LaneRunReceipt@v2", "lane_id": WATCH, "ok_at": ok_at}),
                 encoding="utf-8")


def test_observe_signal_reads_the_receipt_and_lets_a_green_run_clear_the_breach(tmp_path):
    sig = _row()["output_signal"]
    _write_receipt(tmp_path, "2026-11-15T14:50:03+00:00")
    seen = LR.observe_signal(sig, root=tmp_path)
    assert seen["readable"] is True
    assert seen["last_output_at"] is not None
    assert seen["last_output_at"].isoformat().startswith("2026-11-15T14:50:03")


def test_a_failed_run_stays_silent_rather_than_unreadable(tmp_path):
    """``ok_at: null`` is a quiet receipt, not a broken one: readable, no output time.

    This is the difference the fix buys. ``readable: false`` is what the breach detector cannot clear.
    """
    sig = _row()["output_signal"]
    _write_receipt(tmp_path, None)
    seen = LR.observe_signal(sig, root=tmp_path)
    assert seen["readable"] is True
    assert seen["last_output_at"] is None


def test_the_old_declaration_on_a_text_log_is_unreadable_by_construction(tmp_path):
    """Fail-before fixture: the defect itself, so a future edit that restores it is caught by this file."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "watch_outcomes.log").write_text(
        "[watch-outcomes] dependency_unavailable — no producer\n", encoding="utf-8")
    old = {"kind": "json_key", "key": "ok_at", "path": "logs/watch_outcomes.log"}
    with pytest.raises(json.JSONDecodeError):
        # the exact call observe_signal makes; its broad except is why the lane reported NO_OUTPUT forever
        json.loads((tmp_path / "logs" / "watch_outcomes.log").read_text(encoding="utf-8"))
    assert LR.observe_signal(old, root=tmp_path)["readable"] is False
