"""Slice 4: persist operator product after CIO synthesis. Never persist UNAVAILABLE."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cio_operator_product import persist_operator_product_if_available
from scripts.lib.cio_run_worker import CIORunWorker


def test_unavailable_does_not_overwrite_last_good(tmp_path, monkeypatch):
    path = tmp_path / "data" / "cio" / "cio_operator_product.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"product_id":"last_good","available":true}', encoding="utf-8")
    before = path.read_text()

    def fake_build(*, root=None, persist=False, supplemental=None):
        assert persist is False
        return {"available": False, "status": "INVALID_SCHEMA", "product_id": None}

    monkeypatch.setattr(
        "scripts.lib.cio_operator_product.build_operator_product", fake_build,
    )
    rec = persist_operator_product_if_available(root=tmp_path)
    assert rec["persisted"] is False
    assert "not AVAILABLE" in rec["skipped_reason"]
    assert path.read_text() == before


def test_available_persist_path_hit_once(monkeypatch):
    calls: list[bool] = []

    def fake_build(*, root=None, persist=False, supplemental=None):
        calls.append(persist)
        return {
            "available": True,
            "status": "AVAILABLE",
            "product_id": "prod_op_1",
            "as_of": "2026-08-28T00:00:00+00:00",
            "persisted_path": "/tmp/cio_operator_product.json" if persist else None,
        }

    monkeypatch.setattr(
        "scripts.lib.cio_operator_product.build_operator_product", fake_build,
    )
    rec = persist_operator_product_if_available()
    assert rec["persisted"] is True
    assert rec["product_id"] == "prod_op_1"
    assert calls.count(False) == 1
    assert calls.count(True) == 1


def test_worker_persist_hook_once(monkeypatch):
    hits: list[bool] = []

    def fake_persist(**kwargs):
        hits.append(True)
        return {"persisted": True, "product_id": "prod_op_run"}

    monkeypatch.setattr(
        "scripts.lib.cio_operator_product.persist_operator_product_if_available",
        fake_persist,
    )
    worker = CIORunWorker(mode="shadow")
    rec = worker._persist_operator_product()
    assert rec["persisted"] is True
    assert hits == [True]
