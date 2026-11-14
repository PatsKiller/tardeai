"""LQ-20261113-3103 part 1: stored-reader provenance fields (product, schema_version, etag).

(1) every stored route's ``_product`` meta carries product, served_from, schema_version, seq, as_of, built_at (+etag);
(3) the verifier's own checks (lead/scratch/verify/stored_reader_verify.py), ported hermetically.
Synthetic fixtures only: no DB, no network, no live files.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

from scripts.lib.cc_products import cio_pages_route as cpr  # noqa: E402
from scripts.lib.cc_products import product_route as pr  # noqa: E402
from scripts.lib.cc_products.product_builder import parse_ts  # noqa: E402

NOW = datetime(2026, 11, 13, 23, 55, 0, tzinfo=timezone.utc)
SRC = datetime(2026, 11, 13, 22, 0, 0, tzinfo=timezone.utc)  # a source clock well before any read time
REQUIRED = ("product", "served_from", "schema_version", "seq", "as_of", "built_at")


def _env(**kw):
    env = {"product": "reports.analyst_links", "scope": "global", "status": "OK", "as_of": SRC.isoformat(),
           "built_at": (SRC + timedelta(minutes=2)).isoformat(), "next_refresh_at": None, "stale_after_s": 129600,
           "hard_expiry_s": 604800, "age_s": 100.0, "seq": 7, "etag": "sha256:abc", "reason": None, "data": {"a": 1},
           "last_good": None, "served_from": "pg", "source_watermarks": {}, "build_status": "OK",
           "build_failure": None, "schema_version": 3}
    env.update(kw)
    return env


# ------------------------------------------------------------------------------- (1) meta carries provenance


@pytest.mark.parametrize("make_meta", [
    lambda env: cpr._meta(env, status="OK", reason=None, greyed=False, now=NOW),
    lambda env: pr._meta(env, status="OK", greyed=False, now=NOW),
], ids=["cio_pages_route", "product_route"])
def test_every_stored_route_meta_exposes_the_provenance_fields(make_meta):
    meta = make_meta(_env())
    for k in REQUIRED:
        assert meta.get(k) is not None, f"_product.{k} dropped from the served meta"
    assert meta["schema_version"] == 3 and meta["etag"] == "sha256:abc"
    assert meta["product"] == "reports.analyst_links" and meta["served_from"] == "pg" and meta["seq"] == 7


def test_the_field_list_is_a_superset_of_the_verifier_contract():
    for k in (*REQUIRED, "etag"):
        assert k in cpr._PRODUCT_FIELDS


# ------------------------------------------------------------- (3) the verifier's checks, hermetic


def verifier_checks(meta: dict, *, catalogue_schema: int, db_seq: int, now: datetime, body) -> list[str]:
    """Port of stored_reader_verify.py's per-route checks. Returns the failures (empty = PASS)."""
    bad = []
    if not meta:
        return ["_product meta missing"]
    if not meta.get("product"):
        bad.append("product identity missing")
    if meta.get("served_from") not in ("hot", "pg"):
        bad.append("served_from not hot/pg")
    if meta.get("schema_version") is None:
        bad.append("schema_version missing")
    elif meta["schema_version"] != catalogue_schema:
        bad.append("schema_version != catalogue")
    if meta.get("status") not in ("OK", "STALE"):
        bad.append("status not OK/STALE")
    a, b = parse_ts(meta.get("as_of")), parse_ts(meta.get("built_at"))
    if a is None or b is None:
        bad.append("as_of/built_at missing")
    else:
        if a > b:
            bad.append("as_of after built_at")
        if abs((now - a).total_seconds() - float(meta.get("age_s") or 0)) > 120:
            bad.append("age_s inconsistent with as_of")
    if meta.get("seq") != db_seq:
        bad.append("seq != db row")
    if not body:
        bad.append("empty body")
    return bad


def test_verifier_passes_a_served_meta_and_names_each_defect():
    env = _env(age_s=(NOW - SRC).total_seconds())
    meta = pr._meta(env, status="OK", greyed=False, now=NOW)
    assert verifier_checks(meta, catalogue_schema=3, db_seq=7, now=NOW, body={"a": 1}) == []
    no_schema = {k: v for k, v in meta.items() if k != "schema_version"}
    assert verifier_checks(no_schema, catalogue_schema=3, db_seq=7, now=NOW, body={"a": 1}) == ["schema_version missing"]
    future = dict(meta, as_of=(parse_ts(meta["built_at"]) + timedelta(seconds=45)).isoformat())
    assert "as_of after built_at" in verifier_checks(future, catalogue_schema=3, db_seq=7, now=NOW, body={"a": 1})




# ------------------------------------------- REVIEW-3102 R1/R3: every cio.pages shape names its product and schema
def _serve(read_product):
    return cpr.serve_cio_pages(read_product=read_product, fetch_row=lambda *a, **k: None, now=NOW)


def _shapes():
    ok = _env(product="cio.pages")
    return {
        "OK": lambda *a, **k: dict(ok, data={"pages": [1]}),
        "STALE": lambda *a, **k: dict(ok, status="STALE", data={"pages": [1]}),
        "greyed UNKNOWN": lambda *a, **k: dict(ok, status="UNKNOWN", reason="hard expiry", data=None, last_good={"pages": [1]}),
        "BUILDING": lambda *a, **k: {"status": "BUILDING", "reason": "not built yet", "data": None},
        "store down": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    }


@pytest.mark.parametrize("shape", ["OK", "STALE", "greyed UNKNOWN", "BUILDING", "store down"])
def test_every_cio_pages_shape_carries_product_and_an_int_schema_version(shape):
    meta = _serve(_shapes()[shape])["_product"]
    assert meta["product"] == "cio.pages"
    assert isinstance(meta["schema_version"], int) and not isinstance(meta["schema_version"], bool)


def test_the_no_row_shapes_carry_the_reader_expected_schema():
    assert _serve(_shapes()["BUILDING"])["_product"]["schema_version"] == cpr.READER_SCHEMA_VERSION == 1
    assert _serve(_shapes()["store down"])["_product"]["schema_version"] == 1


def test_a_stored_row_keeps_its_own_schema_version():
    assert _serve(_shapes()["OK"])["_product"]["schema_version"] == 3


def test_null_as_of_says_why():
    assert _serve(_shapes()["BUILDING"])["_product"]["as_of_reason"] == "never built"
    assert _serve(_shapes()["store down"])["_product"]["as_of_reason"] == "store unavailable"
    assert "as_of_reason" not in _serve(_shapes()["OK"])["_product"]
