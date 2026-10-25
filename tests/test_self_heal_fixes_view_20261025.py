"""Ops → Releases & schedules → Fixes: the fix-log read model and the digest's daily self-heal line (2026-10-25).

Operator: "Arm the fixer and also a logger that tracks what was fixed". The writer is scripts/self_heal_train_monitor.py
(PR #2129, SelfHealFixLog@v1). Hermetic: tmp_path state root only.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import advice_digest as AD  # noqa: E402
from scripts.lib import self_heal_fixes_view as V  # noqa: E402

NOW = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)  # 17:00 ET


def row(fix_id, outcome, at, event="moved", **kw):
    return {
        "schema": "SelfHealFixLog@v1",
        "fix_id": fix_id,
        "outcome": outcome,
        "at": at.isoformat(),
        "event": event,
        "title": f"t {fix_id}",
        "source": "ci",
        "secret_extra": "never forwarded",
        **kw,
    }


def write_log(root: Path, rows) -> None:
    p = root / V.FIX_LOG_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n", encoding="utf-8")


def heartbeat(root: Path, at: datetime, mode="shadow") -> None:
    p = root / V.HEARTBEAT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "ok": True,
                "ok_at": at.isoformat(),
                "mode": mode,
                "policy": {"why": "AGENTS.md 20.2.0 < 20.4.0"},
                "ci": {"ci": "GREEN"},
            }
        )
    )


def test_missing_log_is_unavailable_with_its_reason_never_empty_green(tmp_path):
    d = V.payload(tmp_path, now=NOW)
    assert d["status"] == "UNAVAILABLE" and "not installed" in d["reason"] and d["rows"] == []
    assert d["monitor"]["stale"] is True


def test_latest_row_per_fix_filters_summary_history_and_field_allowlist(tmp_path):
    t = NOW - timedelta(hours=2)
    write_log(
        tmp_path,
        [
            row("a", "detected", t, event="detected"),
            row("a", "fix-PR-open", t + timedelta(minutes=5), pr_number=12, model_cost_usd=2.5),
            row("b", "fixed-released", t + timedelta(minutes=6), released_sha="r" * 40, verified_at=NOW.isoformat()),
            row("c", "gave-up", t + timedelta(minutes=7)),
            row("d", "shadow-proposed", t + timedelta(minutes=8)),
        ],
    )
    heartbeat(tmp_path, NOW - timedelta(minutes=3))
    d = V.payload(tmp_path, now=NOW)
    assert d["status"] == "OK" and [r["fix_id"] for r in d["rows"]] == ["d", "c", "b", "a"]
    assert d["summary"] == {"total": 4, "open": 1, "fixed": 1, "escalated": 1, "proposed": 1, "model_cost_usd": 2.5}
    assert all("secret_extra" not in r for r in d["rows"])
    assert d["monitor"]["stale"] is False and d["monitor"]["mode"] == "shadow"
    assert [r["fix_id"] for r in V.payload(tmp_path, now=NOW, filter_="open")["rows"]] == ["a"]
    assert [r["fix_id"] for r in V.payload(tmp_path, now=NOW, filter_="escalated")["rows"]] == ["c"]
    h = V.payload(tmp_path, now=NOW, fix_id="a")["history"]
    assert [r["outcome"] for r in h] == ["detected", "fix-PR-open"]
    page = V.payload(tmp_path, now=NOW, limit=2, offset=2)
    assert len(page["rows"]) == 2 and page["has_more"] is False and page["total"] == 4


def test_handle_is_get_only_and_validates_query(tmp_path):
    env = {"TRADEAI_STATE_ROOT": str(tmp_path)}
    assert V.handle("/api/v2/ops/self-heal-fixes", "POST", {}, env)[0] == 405
    assert V.handle("/api/v2/ops/self-heal-fixes", "GET", {"filter": ["nope"]}, env)[0] == 400
    assert V.handle("/api/v2/ops/self-heal-fixes", "GET", {"limit": ["x"]}, env)[0] == 400
    code, body = V.handle("/api/v2/ops/self-heal-fixes", "GET", {"filter": ["open"], "limit": ["500"]}, env)
    assert code == 200 and body["ok"] and body["data"]["limit"] == V.MAX_LIMIT


def test_digest_daily_self_heal_line_counts_today_only(tmp_path):
    today, yday = NOW - timedelta(hours=1), NOW - timedelta(days=1, hours=2)
    write_log(
        tmp_path,
        [
            row("old", "fixed-released", yday),
            row("a", "detected", today, event="detected"),
            row("a", "fixed-released", today + timedelta(minutes=1), model_cost_usd=3.25),
            row("b", "fix-PR-open", today),
            row("c", "escalated", today),
        ],
    )
    s = AD.collect_self_heal(tmp_path, NOW)
    assert s == {"detected": 1, "fixed": 1, "open": 1, "escalated": 1, "gave_up": 0, "proposed": 0, "cost_usd": 3.25}
    line = AD.self_heal_line(s)
    assert "SELF-HEAL TODAY" in line and "1 fixed" in line and "1 open" in line and "1 escalated" in line
    assert "$3.25 model" in line and "/v3/system/releases?tab=fixes" in line


def test_digest_line_absent_when_no_log_or_quiet_day(tmp_path):
    assert AD.collect_self_heal(tmp_path, NOW) is None and AD.self_heal_line(None) is None
    write_log(tmp_path, [row("old", "fixed-released", NOW - timedelta(days=2))])
    assert AD.self_heal_line(AD.collect_self_heal(tmp_path, NOW)) is None


def test_digest_renders_the_line_only_in_the_17_slot(monkeypatch):
    summary = {"detected": 2, "fixed": 1, "open": 0, "escalated": 0, "gave_up": 0, "proposed": 0, "cost_usd": 0.0}
    other = {"rows": [], "lane_health": [], "self_heal": summary}
    seventeen = "\n".join(AD.render("17", {}, [], {}, None, other, NOW))
    ten = "\n".join(AD.render("10", {}, [], {}, None, other, NOW))
    assert "SELF-HEAL TODAY" in seventeen and "SELF-HEAL TODAY" not in ten
