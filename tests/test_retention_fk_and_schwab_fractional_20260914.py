"""Retention no longer aborts on referenced rows; fractional Schwab positions get a per-share price.

2026-09-14:
* db_retention failed nightly on aegis_steph_escalations (1,212 expired, 3 still
  referenced) and watchlist_agent_jobs (69,248 expired, 6 referenced): one DELETE,
  one foreign-key violation, nothing pruned. Operator: retention may keep
  hard-deleting.
* holdings.json price for SCHG 0.2294 sh read 8.03 (its value); the transport
  computes marketValue / max(quantity, 1). Operator approved the fix; the
  transport is broker-subsystem code, so the per-share price is derived in the
  read-only position sync.
Offline: fake cursors, no database.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/db_retention.py", "scripts/schwab_position_sync.py"]


def _load(relpath: str):
    name = "rfk_" + relpath.replace("/", "_").removesuffix(".py")
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchall(self):
        return self.rows


def test_fk_guard_excludes_rows_a_child_still_references():
    dr = _load("scripts/db_retention.py")
    cur = _Cur([("watchlist_agent_results", "job_id", "id")])
    guard = dr.fk_guard(cur, "watchlist_agent_jobs")
    assert guard == ' AND NOT EXISTS (SELECT 1 FROM watchlist_agent_results ch WHERE ch."job_id" = t."id")'
    assert cur.sql[0][1] == ("watchlist_agent_jobs",)


def test_no_foreign_keys_means_the_statement_is_unchanged():
    dr = _load("scripts/db_retention.py")
    assert dr.fk_guard(_Cur([]), "market_quotes") == ""


def test_retention_statement_uses_the_guard():
    src = (ROOT / "scripts" / "db_retention.py").read_text(encoding="utf-8")
    assert "DELETE FROM {table} t WHERE t.{col} < now() - interval '{days} days'{guard}" in src
    assert "SELECT count(*) FROM {table} t WHERE t.{col} < now() - interval '{days} days'{guard}" in src


def test_fractional_schwab_position_gets_a_per_share_price():
    src = (ROOT / "scripts" / "schwab_position_sync.py").read_text(encoding="utf-8")
    assert "price = round(mv / qty, 6)" in src
    # the rule itself, applied to the measured rows
    def rule(price, mv, qty):
        if mv and qty and (price is None or (0 < abs(qty) < 1 and abs(price - mv) < 0.01)):
            return round(mv / qty, 6)
        return price
    assert abs(rule(8.03, 8.03, 0.2294) - 35.004) < 0.01
    assert rule(34.475, 344758.65, 10000.2508) == 34.475   # whole positions keep the broker price
    assert abs(rule(None, 85.23, 11.8795) - 7.1746) < 0.001
