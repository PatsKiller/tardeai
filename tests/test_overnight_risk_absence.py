"""The only model-assisted field on any operator surface must not vanish silently.

`Overnight Risk Analysis` is sourced from `risk_synthesis_results` and is the one
M-class field in the P9.0 provenance census. It sat behind a bare
`except Exception: pass`, so the morning brief rendered complete while the
section disappeared.

It has produced nothing since 2026-05-23. The cause is NOT the cost cap — the
deep overnight LLM window was retired on 2026-06-01 (cron tagged
PHASE102-RETIRED), two months before `LLM_GLOBAL_DAILY_USD_CAP` went missing in
the 2026-07-21 secrets migration. Re-enabling it is a tracked P1 with ~1,900
jobs pending.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SRC = (ROOT / "scripts/aegis_morning_brief_delivery.py").read_text(encoding="utf-8")


def test_the_swallow_is_gone():
    i = SRC.index("Overnight risk synthesis")
    block = SRC[i:i + 2200]
    assert "except Exception:\n        pass" not in block
    assert "_risk_error" in block


def test_a_query_failure_is_reported_not_hidden():
    i = SRC.index("Overnight risk synthesis")
    block = SRC[i:i + 2200]
    assert "query failed" in block


def test_absence_is_stated_rather_than_omitted():
    """A brief that looks complete while its only judgment field is missing is
    the defect this programme is about."""
    i = SRC.index("Overnight risk synthesis")
    block = SRC[i:i + 2200]
    assert "none in the last 18h" in block


def test_the_absence_line_distinguishes_quiet_from_dead(monkeypatch):
    """Silence and staleness read identically without the age."""
    import aegis_morning_brief_delivery as mod
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(mod, "_db_query",
                        lambda *a, **k: {"last_at": datetime.now(timezone.utc) - timedelta(days=96)})
    out = mod._overnight_synthesis_age()
    assert "96d ago" in out and "retired" in out

    monkeypatch.setattr(mod, "_db_query",
                        lambda *a, **k: {"last_at": datetime.now(timezone.utc) - timedelta(hours=20)})
    assert "retired" not in mod._overnight_synthesis_age()


def test_never_recorded_is_its_own_message(monkeypatch):
    import aegis_morning_brief_delivery as mod
    monkeypatch.setattr(mod, "_db_query", lambda *a, **k: {"last_at": None})
    assert "ever been recorded" in mod._overnight_synthesis_age()


def test_the_age_helper_cannot_break_the_brief(monkeypatch):
    """A diagnostic that can break the path it observes is worse than none."""
    import aegis_morning_brief_delivery as mod

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "_db_query", boom)
    assert mod._overnight_synthesis_age() == ""
