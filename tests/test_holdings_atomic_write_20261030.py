"""Holdings writes are atomic: a failed write never leaves a truncated file.

Root cause (DSN-20261030): disk ENOSPC during a deploy truncated holdings.json
(ticker_snapshot_latest.json and finviz_quote_cache.json too) to 0 bytes because
two write paths were NON-ATOMIC — ``Path.write_text``/``Path.write_bytes`` open
the target in truncate ("wb"/"w") mode *first*, then write. Under ENOSPC the
truncate succeeds and the write fails, leaving the durable file at 0 bytes; the
next producer then crashes reading it (JSONDecodeError), so it never self-heals.

This test proves the new mechanism:
  * ``scripts/lib/atomic_json_store.atomic_write_bytes`` writes exact bytes via a
    same-directory temp file + fsync + os.replace, so the target is never
    truncated in place — a simulated failure leaves the prior bytes intact;
  * the two call sites route through it (portfolio_repricer holdings refresh,
    schwab_position_sync backup restore) rather than a truncating write.

Hermetic: everything runs in tmp_path with side-effect writers monkeypatched out;
no live holdings.json, no broker, no network, no DB.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.atomic_json_store import atomic_write_bytes  # noqa: E402

GOOD = b'{"holdings": [{"symbol": "SCHD", "shares": 100.0}], "portfolio_totals": {"total_value": 12345.67}}'
PRIOR = b'{"holdings": [{"symbol": "VTI", "shares": 10.0}], "portfolio_totals": {"total_value": 9999.0}}'


def _leftover_names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


# ── the helper itself is truncation-proof ────────────────────────────────────

def test_atomic_write_bytes_writes_exact_bytes(tmp_path):
    target = tmp_path / "holdings.json"
    atomic_write_bytes(target, GOOD)
    assert target.read_bytes() == GOOD, "payload must round-trip byte-for-byte"


def test_replace_failure_leaves_prior_content_intact(tmp_path, monkeypatch):
    target = tmp_path / "holdings.json"
    target.write_bytes(PRIOR)

    real_replace = os.replace

    def enospc_replace(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", enospc_replace)

    with pytest.raises(OSError):
        atomic_write_bytes(target, GOOD)

    assert target.read_bytes() == PRIOR, "a failed replace must not truncate the target"
    assert _leftover_names(tmp_path) == ["holdings.json"], "temp file must be cleaned up"


def test_fsync_failure_leaves_prior_content_intact(tmp_path, monkeypatch):
    target = tmp_path / "holdings.json"
    target.write_bytes(PRIOR)

    def enospc_fsync(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", enospc_fsync)

    with pytest.raises(OSError):
        atomic_write_bytes(target, GOOD)

    assert target.read_bytes() == PRIOR, "a failed fsync must not truncate the target"
    assert _leftover_names(tmp_path) == ["holdings.json"], "temp file must be cleaned up"


# ── the schwab restore path restores the backup atomically ───────────────────

def test_schwab_restore_path_restores_backup_atomically(tmp_path, monkeypatch):
    """protected_holdings_write's post-write restore must not truncate the file.

    Force the post-write assertion to fail so the restore path runs, and prove
    the prior snapshot comes back byte-for-byte (not a 0-byte file).
    """
    from scripts import schwab_position_sync as sps

    hp = tmp_path / "holdings.json"
    hp.write_bytes(PRIOR)

    class _Ok:
        ok = True
        reason_code = "VALID_COMPLETE"
        reason = "ok"
        total = 9999.0
        position_count = 1
        missing_accounts = []

    monkeypatch.setattr(sps, "validate_payload", lambda doc, last_good=None: _Ok())
    monkeypatch.setattr(sps, "reconcile_totals", lambda doc, **kw: None)
    monkeypatch.setattr(sps, "_record", lambda *a, **k: None)
    monkeypatch.setattr(sps, "_alert", lambda *a, **k: None)

    def boom(path=None, last_good=None):
        raise AssertionError("simulated post-write assert failure")

    monkeypatch.setattr(sps, "canonical_assert", boom)

    result = sps.protected_holdings_write(
        {"holdings": [{"symbol": "SCHD", "shares": 5.0}],
         "portfolio_totals": {"total_value": 54321.0}},
        source="test_restore",
        account_key="test",
        protect_basis=False,
        target_path=str(hp),
    )

    assert result["wrote"] is False
    assert result["status"] == "rejected_postwrite"
    assert hp.read_bytes() == PRIOR, "restore must leave the prior snapshot intact, not truncate it"


# ── the call sites no longer use a truncating write ──────────────────────────

def _no_truncating_write(source: str, receiver: str, filename: str) -> None:
    tree = ast.parse(source)
    offenders = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("write_text", "write_bytes"):
                recv = node.func.value
                if isinstance(recv, ast.Name) and recv.id == receiver:
                    offenders.add(node.func.attr)
    assert not offenders, (
        f"{filename} still writes {receiver} via {sorted(offenders)}; "
        "route it through atomic_write_bytes (temp + fsync + os.replace)")


def test_repricer_holdings_write_is_atomic():
    src = (ROOT / "scripts" / "portfolio_repricer.py").read_text(encoding="utf-8")
    _no_truncating_write(src, "_target", "scripts/portfolio_repricer.py")
    assert "atomic_write_bytes" in src, "the repricer must route the holdings write through the helper"


def test_schwab_restore_write_is_atomic():
    src = (ROOT / "scripts" / "schwab_position_sync.py").read_text(encoding="utf-8")
    _no_truncating_write(src, "HP", "scripts/schwab_position_sync.py")
    assert "atomic_write_bytes" in src, "the restore path must route through the helper"
