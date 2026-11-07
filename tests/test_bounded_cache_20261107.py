"""ANCHOR: BOUNDED_CACHE_20261107 — LQ-20261107-202. Request- and symbol-keyed module caches stay capped."""
from scripts import api_v3_advisory as adv
from scripts.lib.bounded_cache import cap_dict


def test_cap_dict_evicts_oldest_first():
    d = {i: i for i in range(10)}
    assert cap_dict(d, 4) == 6 and list(d) == [6, 7, 8, 9]
    assert cap_dict(d, 4) == 0


def test_desk_view_cache_cannot_grow_with_row_class(monkeypatch):
    monkeypatch.setattr(adv, "_get_advisory_desk_uncached", lambda **kw: {"ok": True, "rows": []})
    adv._DESK_VIEW_CACHE.clear()
    for i in range(adv._DESK_VIEW_MAX * 5):
        adv.get_advisory_desk(row_class=f"syn-class-{i}")
    assert len(adv._DESK_VIEW_CACHE) <= adv._DESK_VIEW_MAX
    adv._DESK_VIEW_CACHE.clear()
