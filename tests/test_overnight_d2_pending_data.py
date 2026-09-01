"""WAVE D2 — OUTCOME_PENDING_DATA triage.

PENDING_DATA must not sit forever. Classify each row:
  future_dated / obtainable / stuck_waiting_data / never_resolvable

Obtainable → may resolve once prices exist.
Never-resolvable → expire explicitly (status + reason), append-only.
Dry-run default; --apply-pending-data requires TRADEAI_PENDING_DATA_APPLY=1.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts.lib.outcome_resolution import (
    CLASS_FUTURE,
    CLASS_NEVER,
    CLASS_OBTAINABLE,
    CLASS_STUCK,
    PENDING_APPLY_ENV,
    STATUS_EXPIRED,
    STATUS_PENDING_DATA,
    STATUS_RESOLVED,
    classify_pending_checkpoint,
    pending_data_checkpoints,
    resolution_row,
    triage_pending_data,
)

NOW = datetime(2026, 8, 31, 4, 0, tzinfo=timezone.utc)


def _pending(**over):
    base = {
        "checkpoint_id": "pd1",
        "decision_id": "plan_1",
        "status": STATUS_PENDING_DATA,
        "due_at": (NOW - timedelta(days=2)).isoformat(),
        "created_at": (NOW - timedelta(days=3)).isoformat(),
        "horizon": "1_session",
        "resolution_reason": "no_price_history_for_comparison",
        "original_decision_state": {
            "symbol": "SCHD",
            "recommendation": "TRIM",
            "as_of": (NOW - timedelta(days=3)).isoformat(),
        },
    }
    base.update(over)
    return base


def _prices(table):
    """table: symbol -> (close, date) or None sentinel via missing key.

    Ignores on_or_before — both ends of the comparison see the same row.
    Prefer ``_prices_by_date`` when testing move / exact-equal behaviour.
    """
    def lookup(symbol, on_or_before):
        return table.get(symbol)
    return lookup


def _prices_by_date(table):
    """table: symbol -> list of (close, date) ascending. Closest on_or_before wins."""
    def lookup(symbol, on_or_before):
        rows = table.get(symbol) or []
        best = None
        for close, date in rows:
            if str(date) <= str(on_or_before):
                best = (close, date)
        return best
    return lookup


# ── classification ──────────────────────────────────────────────────────────

def test_future_dated_pending_is_left_alone():
    """Horizon not yet reached — not stuck, not expired."""
    future = (NOW + timedelta(days=3)).isoformat()
    item = classify_pending_checkpoint(
        _pending(due_at=future),
        price_lookup=_prices({}),
        now=NOW,
    )
    assert item["class"] == CLASS_FUTURE
    assert item["action"] == "leave"
    assert item["reason"] == "due_at_in_future"


def test_obtainable_when_both_price_ends_exist():
    """Distinct dates and a non-zero move → resolve."""
    item = classify_pending_checkpoint(
        _pending(),
        price_lookup=_prices_by_date({
            "SCHD": [(35.03, "2026-08-28"), (35.10, "2026-08-31")],
        }),
        registry_lookup=lambda s: True,
        now=NOW,
    )
    assert item["class"] == CLASS_OBTAINABLE
    assert item["action"] == "resolve"
    assert item["realized_state"]["symbol"] == "SCHD"
    assert item["realized_state"]["change_pct"] != 0.0
    assert "change_pct" in item["realized_state"]


def test_exact_equal_endpoints_left_stuck():
    """Same close on distinct dates — refuse; do not manufacture a 0.00% outcome."""
    item = classify_pending_checkpoint(
        _pending(),
        price_lookup=_prices_by_date({
            "SCHD": [(34.88, "2026-08-28"), (34.88, "2026-08-31")],
        }),
        registry_lookup=lambda s: True,
        now=NOW,
    )
    assert item["class"] == CLASS_STUCK
    assert item["action"] == "leave"
    assert item["reason"] == "exact_equal_endpoints"
    assert item["realized_state"]["change_pct"] == 0.0


def test_stuck_when_price_history_still_missing():
    item = classify_pending_checkpoint(
        _pending(),
        price_lookup=_prices({}),
        registry_lookup=lambda s: True,
        now=NOW,
    )
    assert item["class"] == CLASS_STUCK
    assert item["action"] == "leave"
    assert item["reason"] == "no_price_history_either_end"


def test_cash_decision_pending_is_never_resolvable_and_expires():
    """A PENDING_DATA row that should have been NOT_PRICE_RESOLVABLE."""
    cp = _pending(
        original_decision_state={
            "symbol": "CASH",
            "recommendation": "HOLD_CASH",
            "as_of": (NOW - timedelta(days=3)).isoformat(),
        },
    )
    item = classify_pending_checkpoint(
        cp,
        price_lookup=_prices({"CASH": (10.0, "2026-08-28")}),
        registry_lookup=lambda s: True,
        now=NOW,
    )
    assert item["class"] == CLASS_NEVER
    assert item["action"] == "expire"
    assert "portfolio_cash_decision" in item["reason"]


def test_missing_decision_timestamp_expires():
    cp = _pending(
        created_at=None,
        original_decision_state={"symbol": "SCHD", "recommendation": "TRIM"},
    )
    item = classify_pending_checkpoint(
        cp,
        price_lookup=_prices({"SCHD": (35.0, "2026-08-28")}),
        registry_lookup=lambda s: True,
        now=NOW,
    )
    assert item["class"] == CLASS_NEVER
    assert item["reason"] == "no_decision_timestamp"
    assert item["action"] == "expire"


def test_unregistered_pseudo_symbol_expires():
    cp = _pending(
        original_decision_state={
            "symbol": "ZZZZ",
            "recommendation": "TRIM",
            "as_of": (NOW - timedelta(days=3)).isoformat(),
        },
    )
    item = classify_pending_checkpoint(
        cp,
        price_lookup=_prices({}),
        registry_lookup=lambda s: s == "SCHD",
        now=NOW,
    )
    assert item["class"] == CLASS_NEVER
    assert item["reason"] == "subject_not_a_registered_security"


# ── triage census ───────────────────────────────────────────────────────────

def test_triage_counts_split_future_obtainable_stuck_never():
    rows = [
        _pending(checkpoint_id="fut", due_at=(NOW + timedelta(days=1)).isoformat()),
        _pending(checkpoint_id="ok"),
        _pending(checkpoint_id="stuck",
                 original_decision_state={
                     "symbol": "XLI",
                     "recommendation": "HOLD",
                     "as_of": (NOW - timedelta(days=3)).isoformat(),
                 }),
        _pending(
            checkpoint_id="cash",
            original_decision_state={
                "symbol": "CASH",
                "recommendation": "HOLD_CASH",
                "as_of": (NOW - timedelta(days=3)).isoformat(),
            },
        ),
    ]
    # SCHD has a real move → "ok" obtainable; XLI missing → stuck; cash never; fut future.
    out = triage_pending_data(
        rows,
        price_lookup=_prices_by_date({
            "SCHD": [(35.0, "2026-08-28"), (35.2, "2026-08-31")],
        }),
        registry_lookup=lambda s: True,
        now=NOW,
    )
    assert out["schema"] == "PendingDataTriage@v1"
    assert out["pending_total"] == 4
    assert out["counts"][CLASS_FUTURE] == 1
    assert out["counts"][CLASS_OBTAINABLE] == 1
    assert out["counts"][CLASS_STUCK] == 1
    assert out["counts"][CLASS_NEVER] == 1
    assert out["apply_env"] == PENDING_APPLY_ENV


def test_pending_data_checkpoints_uses_latest_only():
    """Append-only: a later RESOLVED version must drop the row from pending."""
    original = _pending(checkpoint_id="cpX")
    resolved = resolution_row(original, "out-1", STATUS_RESOLVED, now=NOW)
    assert pending_data_checkpoints([original, resolved]) == []


def test_expire_receipt_is_append_only_and_explicit():
    row = resolution_row(
        _pending(),
        None,
        STATUS_EXPIRED,
        reason="pending_data_expired:portfolio_cash_decision_hold_cash",
        now=NOW,
    )
    assert row["status"] == STATUS_EXPIRED
    assert row["outcome_id"] is None
    assert row["resolution_reason"].startswith("pending_data_expired:")
    assert row["observational_only"] is True
    assert row["trading"] is False
    assert row["memory_behavior_influence"] == 0


# ── runner env gate ─────────────────────────────────────────────────────────

def test_apply_pending_refused_without_env(tmp_path, monkeypatch):
    """--apply-pending-data is a no-write without TRADEAI_PENDING_DATA_APPLY=1."""
    monkeypatch.delenv(PENDING_APPLY_ENV, raising=False)

    # Build a tiny fake store the runner can read.
    root = tmp_path
    ck = root / "data" / "cio" / "outcome_checkpoints.jsonl"
    ck.parent.mkdir(parents=True)
    # never-resolvable cash pending → would expire if armed
    row = _pending(
        checkpoint_id="cash1",
        original_decision_state={
            "symbol": "CASH",
            "recommendation": "HOLD_CASH",
            "as_of": (NOW - timedelta(days=3)).isoformat(),
        },
    )
    ck.write_text(json.dumps(row) + "\n", encoding="utf-8")

    import scripts.resolve_due_checkpoints as rdc

    monkeypatch.setattr(rdc, "_state_root", lambda: root)
    monkeypatch.setattr(rdc, "_price_lookup_factory", lambda: _prices({}))
    monkeypatch.setattr(rdc, "_registry_lookup_factory", lambda: (lambda s: True))

    out = rdc.run_pending_triage(apply=True)
    assert out["apply_refused"] is not None
    assert out["apply_refused"]["reason"] == "APPLY_REFUSED"
    assert out["applied"] is False
    assert out["expired"] == 0
    # Store untouched — still one PENDING line, no EXPIRED append.
    lines = [json.loads(l) for l in ck.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["status"] == STATUS_PENDING_DATA


def test_apply_pending_expires_never_when_env_armed(tmp_path, monkeypatch):
    monkeypatch.setenv(PENDING_APPLY_ENV, "1")

    root = tmp_path
    ck = root / "data" / "cio" / "outcome_checkpoints.jsonl"
    ck.parent.mkdir(parents=True)
    row = _pending(
        checkpoint_id="cash2",
        original_decision_state={
            "symbol": "CASH",
            "recommendation": "HOLD_CASH",
            "as_of": (NOW - timedelta(days=3)).isoformat(),
        },
    )
    ck.write_text(json.dumps(row) + "\n", encoding="utf-8")

    import scripts.resolve_due_checkpoints as rdc

    monkeypatch.setattr(rdc, "_state_root", lambda: root)
    monkeypatch.setattr(rdc, "_price_lookup_factory", lambda: _prices({}))
    monkeypatch.setattr(rdc, "_registry_lookup_factory", lambda: (lambda s: True))

    out = rdc.run_pending_triage(apply=True)
    assert out["apply_refused"] is None
    assert out["applied"] is True
    assert out["expired"] == 1
    assert out["never_resolvable"] == 1

    lines = [json.loads(l) for l in ck.read_text().splitlines() if l.strip()]
    assert len(lines) == 2, "expire must append, not rewrite"
    assert lines[0]["status"] == STATUS_PENDING_DATA
    assert lines[1]["status"] == STATUS_EXPIRED
    assert "pending_data_expired:" in lines[1]["resolution_reason"]


def test_apply_pending_resolves_obtainable_when_env_armed(tmp_path, monkeypatch):
    monkeypatch.setenv(PENDING_APPLY_ENV, "1")

    root = tmp_path
    ck = root / "data" / "cio" / "outcome_checkpoints.jsonl"
    obs = root / "data" / "cio" / "outcome_observations.jsonl"
    ck.parent.mkdir(parents=True)
    ck.write_text(json.dumps(_pending(checkpoint_id="schd1")) + "\n", encoding="utf-8")

    import scripts.resolve_due_checkpoints as rdc

    monkeypatch.setattr(rdc, "_state_root", lambda: root)
    monkeypatch.setattr(
        rdc, "_price_lookup_factory",
        lambda: _prices_by_date({
            "SCHD": [(35.03, "2026-08-28"), (35.20, "2026-08-31")],
        }),
    )
    monkeypatch.setattr(rdc, "_registry_lookup_factory", lambda: (lambda s: True))

    out = rdc.run_pending_triage(apply=True)
    assert out["resolved"] == 1
    assert out["obtainable"] == 1
    lines = [json.loads(l) for l in ck.read_text().splitlines() if l.strip()]
    assert lines[-1]["status"] == STATUS_RESOLVED
    assert lines[-1]["outcome_id"]
    assert obs.exists() and obs.read_text().strip(), "observation must be persisted"


def test_apply_pending_skips_exact_equal_endpoints(tmp_path, monkeypatch):
    """Exact-equal closes must not become RESOLVED observations."""
    monkeypatch.setenv(PENDING_APPLY_ENV, "1")

    root = tmp_path
    ck = root / "data" / "cio" / "outcome_checkpoints.jsonl"
    obs = root / "data" / "cio" / "outcome_observations.jsonl"
    ck.parent.mkdir(parents=True)
    ck.write_text(json.dumps(_pending(checkpoint_id="flat1")) + "\n", encoding="utf-8")

    import scripts.resolve_due_checkpoints as rdc

    monkeypatch.setattr(rdc, "_state_root", lambda: root)
    monkeypatch.setattr(
        rdc, "_price_lookup_factory",
        lambda: _prices_by_date({
            "SCHD": [(34.88, "2026-08-28"), (34.88, "2026-08-31")],
        }),
    )
    monkeypatch.setattr(rdc, "_registry_lookup_factory", lambda: (lambda s: True))

    out = rdc.run_pending_triage(apply=True)
    assert out["resolved"] == 0
    assert out["obtainable"] == 0
    assert out["stuck_waiting_data"] == 1
    assert out["reasons"].get("exact_equal_endpoints") == 1
    lines = [json.loads(l) for l in ck.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["status"] == STATUS_PENDING_DATA
    assert not obs.exists() or not obs.read_text().strip()


def test_parse_as_of_date_pins_end_of_utc_day():
    import scripts.resolve_due_checkpoints as rdc

    dt = rdc._parse_as_of("2026-08-30")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 8 and dt.day == 30
    assert dt.hour == 23 and dt.minute == 59
    assert dt.tzinfo is not None


def test_as_of_selects_prior_horizon_price(tmp_path, monkeypatch):
    """Pinned as_of must use that day's close, not a later copy-forward row."""
    monkeypatch.setenv(PENDING_APPLY_ENV, "1")
    root = tmp_path
    ck = root / "data" / "cio" / "outcome_checkpoints.jsonl"
    ck.parent.mkdir(parents=True)
    ck.write_text(json.dumps(_pending(checkpoint_id="asof1")) + "\n", encoding="utf-8")

    import scripts.resolve_due_checkpoints as rdc

    monkeypatch.setattr(rdc, "_state_root", lambda: root)
    # 08-31 is a copy of an outlier; 08-30 is the honest prior close.
    monkeypatch.setattr(
        rdc, "_price_lookup_factory",
        lambda: _prices_by_date({
            "SCHD": [
                (34.88, "2026-08-28"),
                (34.90, "2026-08-30"),
                (35.11, "2026-08-31"),  # copy-forward / weekend artifact
            ],
        }),
    )
    monkeypatch.setattr(rdc, "_registry_lookup_factory", lambda: (lambda s: True))

    pinned = rdc._parse_as_of("2026-08-30")
    out = rdc.run_pending_triage(apply=True, now=pinned)
    assert out["resolved"] == 1
    assert out["resolve_samples"][0]["horizon_price_date"] == "2026-08-30"
    assert out["resolve_samples"][0]["change_pct"] == 0.0573


def test_dry_run_triage_never_writes(tmp_path, monkeypatch):
    monkeypatch.setenv(PENDING_APPLY_ENV, "1")  # armed env must not matter without apply
    root = tmp_path
    ck = root / "data" / "cio" / "outcome_checkpoints.jsonl"
    ck.parent.mkdir(parents=True)
    before = json.dumps(_pending(checkpoint_id="dry1")) + "\n"
    ck.write_text(before, encoding="utf-8")

    import scripts.resolve_due_checkpoints as rdc

    monkeypatch.setattr(rdc, "_state_root", lambda: root)
    monkeypatch.setattr(
        rdc, "_price_lookup_factory",
        lambda: _prices({"SCHD": (35.03, "2026-08-28")}),
    )
    monkeypatch.setattr(rdc, "_registry_lookup_factory", lambda: (lambda s: True))

    out = rdc.run_pending_triage(apply=False)
    assert out["applied"] is False
    assert out["obtainable"] == 1
    assert out["resolved"] == 0
    assert ck.read_text() == before
