#!/usr/bin/env python3
"""news_ingestion tail rotation helpers."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import news_ingestion as ni  # noqa: E402


def test_select_tail_batch_rotates():
    universe = [("AAA", "a"), ("BBB", "b"), ("CCC", "c"), ("DDD", "d")]
    priority = {"AAA"}
    batch, nxt, n = ni.select_tail_batch(universe, priority, batch_size=2, offset=0)
    assert [b[0] for b in batch] == ["BBB", "CCC"]
    assert nxt == 2
    assert n == 3


def test_select_tail_batch_wraps():
    universe = [("AAA", "a"), ("BBB", "b"), ("CCC", "c")]
    batch, nxt, n = ni.select_tail_batch(universe, set(), batch_size=2, offset=2)
    assert [b[0] for b in batch] == ["CCC", "AAA"]
    assert nxt == 1
    assert n == 3


def test_select_tail_batch_excludes_priority():
    universe = [("HOLD", "h"), ("TAIL1", "t"), ("TAIL2", "t")]
    batch, _, n = ni.select_tail_batch(universe, {"HOLD"}, batch_size=10, offset=0)
    assert [b[0] for b in batch] == ["TAIL1", "TAIL2"]
    assert n == 2


def test_heartbeat_needle_constant():
    assert "heartbeat ok" in ni.HEARTBEAT_NEEDLE