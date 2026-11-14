"""LQ-20261113-3136: Home's clock basis is named (release-2 native; ``as_of`` itself is unchanged).

* every slice mark carries ``clock_basis`` = source | build_time (build_time wherever the read_at fallback is used, and
  for clocks a producer stamps with its own now);
* ``_product`` carries as_of_basis, source_as_of (oldest real source clock or null), source_time_available/_reason;
* the stored-route envelope carries them and never copies ``as_of`` into ``source_as_of``.
Synthetic fixtures only: no DB, no network, no live files.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent

from scripts.lib.cc_products import builders as B  # noqa: E402
from scripts.lib.cc_products import cio_pages_route as cpr  # noqa: E402
from scripts.lib.cc_products import product_route as pr  # noqa: E402
from scripts.lib.cc_products.product_builder import parse_ts  # noqa: E402

NOW = datetime(2026, 11, 13, 23, 55, 0, tzinfo=timezone.utc)
SNAP = "2026-11-13T23:48:00+00:00"
class _Clock:
    """Freeze ``datetime.now`` inside builders so the test chooses the read time."""

    def __init__(self, monkeypatch, at):
        real = B.datetime

        class _D(real):
            @classmethod
            def now(cls, tz=None):
                return at if tz is None else at.astimezone(tz)

        monkeypatch.setattr(B, "datetime", _D)


def _ctx(tmp_path):
    return SimpleNamespace(code_root=ROOT, portfolio_state_dir=tmp_path, db_query=lambda *a, **k: [],
                           db_query_raising=lambda *a, **k: [], get_conn=lambda: None)


def _status(computed_at, read_from="snapshot", verdict="YES"):
    return {"trade_ready": {"verdict": verdict, "computed_at": computed_at, "read_from": read_from}}


def _home(monkeypatch, tmp_path, *, status=None, inc_clock="2026-11-13T23:50:00+00:00", fail=None):
    import lib.home_incidents as hi
    import lib.home_priorities_live as hp
    import lib.home_status_live as hs
    import lib.home_v010_api as hv

    sys.path.insert(0, str(ROOT / "scripts"))

    def _inc(q):
        if fail == "incidents":
            raise RuntimeError("db down")
        return {"snapshot": ({"computed_at": inc_clock} if inc_clock else {}), "rows": []}

    monkeypatch.setattr(hi, "build", _inc)
    monkeypatch.setattr(hp, "build", lambda *a, **k: {"rank": {}})
    monkeypatch.setattr(hs, "serve", lambda *a, **k: status if status is not None else _status(NOW.isoformat(), "computed"))
    monkeypatch.setattr(hv, "home_gates", lambda *a, **k: {"snapshot": {"computed_at": "2026-11-13T16:00:00+00:00"}})
    _Clock(monkeypatch, NOW)
    return B.build_home(_ctx(tmp_path))


def _prod(out):
    return out["source_watermarks"]["_product"]


def _basis(out):
    return {k: v.get("clock_basis") for k, v in out["source_watermarks"].items() if k != "_product"}


def test_with_no_source_clock_everything_is_build_time_and_source_time_is_unavailable(monkeypatch, tmp_path):
    out = _home(monkeypatch, tmp_path)  # status computed on the request: no snapshot
    p = _prod(out)
    assert p["as_of_basis"] == "build_time"
    assert p["source_as_of"] is None and p["source_time_available"] is False
    assert "source time unavailable" in p["source_time_reason"]
    b = _basis(out)
    assert b["incidents"] == b["priorities_live"] == b["status"] == b["gates"] == "build_time"


def test_read_at_fallback_is_always_build_time(monkeypatch, tmp_path):
    out = _home(monkeypatch, tmp_path, inc_clock=None)
    assert parse_ts(out["source_watermarks"]["incidents"]["as_of"]) == NOW
    assert out["source_watermarks"]["incidents"]["clock_basis"] == "build_time"


def test_a_clock_the_producer_stamps_with_its_own_now_is_still_build_time(monkeypatch, tmp_path):
    # home_incidents.build stamps snapshot.computed_at = now: present, but not an observation of any source.
    out = _home(monkeypatch, tmp_path, inc_clock="2026-11-13T23:50:00+00:00")
    assert out["source_watermarks"]["incidents"]["clock_basis"] == "build_time"
    assert out["source_watermarks"]["incidents"]["as_of"] == "2026-11-13T23:50:00+00:00"  # value unchanged


def test_a_snapshot_status_clock_is_a_source_clock(monkeypatch, tmp_path):
    out = _home(monkeypatch, tmp_path, status=_status(SNAP))
    assert _basis(out)["status"] == "source"
    p = _prod(out)
    assert parse_ts(p["source_as_of"]) == parse_ts(SNAP) and p["source_time_available"] is True
    assert p["source_time_reason"] is None
    assert parse_ts(out["as_of"]) == parse_ts(SNAP) and p["as_of_basis"] == "source_clock"


def test_status_computed_on_the_request_or_unknown_is_build_time_even_with_a_computed_at(monkeypatch, tmp_path):
    for st in (_status(SNAP, "computed"), _status(SNAP, "snapshot", "UNKNOWN")):
        out = _home(monkeypatch, tmp_path, status=st)
        assert _basis(out)["status"] == "build_time", st
        assert _prod(out)["source_as_of"] is None


def test_as_of_value_is_unchanged_by_the_label(monkeypatch, tmp_path):
    # release-2 rule: as_of = oldest live slice clock (since_close excluded); gates/priorities are read_at.
    out = _home(monkeypatch, tmp_path, status=_status(SNAP))
    assert parse_ts(out["as_of"]) == parse_ts(SNAP)
    out2 = _home(monkeypatch, tmp_path)
    assert parse_ts(out2["as_of"]) == parse_ts("2026-11-13T23:50:00+00:00")  # the incident clock, as before


def test_a_failed_slice_has_no_basis(monkeypatch, tmp_path):
    out = _home(monkeypatch, tmp_path, fail="incidents")
    m = out["source_watermarks"]["incidents"]
    assert m["as_of"] is None and m["clock_basis"] is None


def test_slice_clocks_in_the_body_carry_the_basis(monkeypatch, tmp_path):
    out = _home(monkeypatch, tmp_path, status=_status(SNAP))
    assert out["data"]["slice_clocks"]["status"]["clock_basis"] == "source"
    assert "_product" not in out["data"]["slice_clocks"]


def _env(prod):
    return {"product": "home", "as_of": "2026-11-13T23:50:00+00:00", "seq": 3, "source_watermarks": {"_product": prod}}


def test_envelope_labels_build_time_and_never_copies_as_of_into_source_as_of():
    for make in (lambda e: cpr._meta(e, status="OK", reason=None, greyed=False, now=NOW),
                 lambda e: pr._meta(e, status="OK", greyed=False, now=NOW)):
        m = make(_env({"as_of_basis": "build_time", "source_as_of": None, "source_time_reason": "source time unavailable: x"}))
        assert m["as_of_basis"] == "build_time" and m["source_as_of"] is None
        assert m["source_time_available"] is False and m["source_time_reason"].startswith("source time unavailable")
        assert m["as_of"] == "2026-11-13T23:50:00+00:00"


def test_envelope_exposes_a_real_source_time():
    m = cpr._meta(_env({"as_of_basis": "source_clock", "source_as_of": SNAP}), status="OK", reason=None, greyed=False, now=NOW)
    assert m["as_of_basis"] == "source_clock" and m["source_as_of"] == SNAP and m["source_time_available"] is True
    assert "source_time_reason" not in m


def test_a_product_with_no_basis_in_its_marks_carries_none_of_the_fields():
    m = cpr._meta(_env({}), status="OK", reason=None, greyed=False, now=NOW)
    assert "as_of_basis" not in m and "source_as_of" not in m


def test_a_slice_with_no_clock_has_no_basis(monkeypatch, tmp_path):
    # since_close with no snapshot file has no generated_at: no clock, so no basis (never "source" for a null).
    out = _home(monkeypatch, tmp_path)
    m = out["source_watermarks"]["since_close"]
    assert m["as_of"] is None and m["clock_basis"] is None
