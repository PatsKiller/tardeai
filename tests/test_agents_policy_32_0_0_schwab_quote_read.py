"""AGENTS.md 32.0.0 (PROPOSED, MAJOR) §23.20a — one broker market-data QUOTE lane on the n8n dispatcher.

LQ-20261107-1684 option B (operator GO 2026-11-09 15:45 ET): "n8n with a narrow exception for this one read-only
Schwab quote lane". Hermetic pins (pure functions + source parsing; nothing runs a lane, nothing reads a credential):

* while SCHWAB_QUOTE_READ_STATUS is PROPOSED the lane is refused on `schwab`, exactly as before the amendment;
* once ACTIVE, only the pinned shape is admitted: the one lane id, registry match, class `ingest`, allowlist command,
  pinned dry/live argv, flock lock and no broker credential name in env_names; any other lane, shape or forbidden
  token is still refused;
* a registry row cannot ratify itself (no row key changes the status);
* the import-graph half: the real entry script reaches the token manager only; a trade context, account read, other
  broker module or send in its reach is an error;
* the code constant and AGENTS.md agree: ACTIVE in code iff AGENTS.md is at >= 32.0.0 ACTIVE with an ACTIVE 32.0.0 row.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import advisory_lane_guard as G  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

LANE = "vix-index-quotes-schwab"
SCRIPT = "scripts/vix_index_quotes_schwab.py"


def _row(**over):
    row = {
        "lane_id": LANE,
        "scheduler": {"kind": "n8n", "expression": "dispatcher", "match": SCRIPT, "stage": "shadow"},
        "dispatch": {"mode": "dry_run", "class": "ingest", "cron": "*/15 * * * 1-4", "tz": "America/New_York"},
    }
    row.update(over)
    return row


def _entry(**over):
    entry = {
        "lane_id": LANE,
        "command": ["$PY", SCRIPT],
        "dry_run_arg": ["--dry-run", "--live-read"],
        "live_arg": None,
        "lock": "/tmp/tradeai_vix_index_quotes_schwab.lock",
        "lock_kind": "flock",
        "env_names": ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "TRADEAI_PERSISTENT_STATE_ROOT"],
    }
    entry.update(over)
    return entry


def _argv(entry):
    return {LANE: " ".join([*entry["command"], *(entry.get("dry_run_arg") or [])])}


@pytest.fixture
def allow(monkeypatch):
    """Point the module's allowlist read at a synthetic entry; returns a setter for per-test shapes."""
    state = {"entry": _entry()}
    monkeypatch.setattr(LD, "load_run_allowlist_entries", lambda path=None: {LANE: state["entry"]})

    def set_entry(entry):
        state["entry"] = entry
        return entry
    return set_entry


def _eligible(row, entry):
    return LD.dispatch_eligible(row, allowlist_argv=_argv(entry), exceptions={}, cutover_policy={})


# --------------------------------------------------------------------------------------------- PROPOSED: unchanged


def test_proposed_refuses_on_schwab(allow, monkeypatch):
    monkeypatch.setattr(LD, "SCHWAB_QUOTE_READ_STATUS", "PROPOSED")
    ok, reason = _eligible(_row(), _entry())
    assert not ok and reason.startswith("forbidden_token:schwab"), reason


def test_a_row_cannot_ratify_itself(allow, monkeypatch):
    monkeypatch.setattr(LD, "SCHWAB_QUOTE_READ_STATUS", "PROPOSED")
    row = _row(_schwab_quote_read_status="ACTIVE", schwab_quote_read_status="ACTIVE", status="ACTIVE")
    assert LD._schwab_quote_read_lift(row) == frozenset()
    assert not _eligible(row, _entry())[0]


# --------------------------------------------------------------------------------------------- ACTIVE: pinned shape


@pytest.fixture
def active(monkeypatch):
    monkeypatch.setattr(LD, "SCHWAB_QUOTE_READ_STATUS", "ACTIVE")


def test_active_admits_the_pinned_shape(allow, active):
    assert LD.schwab_quote_read_shape_problem(_row()) is None
    assert _eligible(_row(), _entry()) == (True, "eligible:schwab_quote_read_23_20a")


@pytest.mark.parametrize("dry,live", [(["--dry-run", "--live-read"], None), (["--dry-run", "--live-read"], ["--apply"])])
def test_active_admits_each_pinned_argv(allow, active, dry, live):
    e = allow(_entry(dry_run_arg=dry, live_arg=live))
    assert _eligible(_row(), e)[0]


def test_another_schwab_lane_is_refused(allow, active, monkeypatch):
    other = "schwab-quotes-everything"
    monkeypatch.setattr(LD, "load_run_allowlist_entries", lambda path=None: {other: _entry(lane_id=other)})
    row = _row(lane_id=other)
    assert LD._schwab_quote_read_lift(row) == frozenset()
    ok, reason = LD.dispatch_eligible(row, allowlist_argv={other: f"$PY {SCRIPT} --dry-run"}, exceptions={},
                                      cutover_policy={})
    assert not ok and "schwab" in reason


@pytest.mark.parametrize("over,problem", [
    ({"command": ["$PY", "scripts/other_schwab_reader.py"]}, "schwab_quote_read_command"),
    ({"command": ["$PY", SCRIPT, "--accounts"]}, "schwab_quote_read_command"),
    ({"dry_run_arg": ["--live-read"]}, "schwab_quote_read_dry_run_arg"),
    ({"dry_run_arg": ["--dry-run"]}, "schwab_quote_read_dry_run_arg"),
    ({"dry_run_arg": ["--dry-run", "--fixture", "/tmp/x.json"]}, "schwab_quote_read_dry_run_arg"),
    ({"dry_run_arg": "--dry-run"}, "schwab_quote_read_dry_run_arg"),
    ({"live_arg": ["--apply", "--orders"]}, "schwab_quote_read_live_arg"),
    ({"lock_kind": "none"}, "schwab_quote_read_lock"),
    ({"env_names": ["DB_HOST", "SCHWAB_APP_KEY"]}, "broker_credential_env:SCHWAB_APP_KEY"),
    ({"env_names": ["BROKER_TOKEN_PATH"]}, "broker_credential_env:BROKER_TOKEN_PATH"),
])
def test_a_wrong_allowlist_shape_is_refused(allow, active, over, problem):
    e = allow(_entry(**over))
    assert LD.schwab_quote_read_shape_problem(_row()) == problem
    assert not _eligible(_row(), e)[0]


@pytest.mark.parametrize("row,problem", [
    (_row(scheduler={"kind": "n8n", "match": "scripts/other.py"}), "schwab_quote_read_match"),
    (_row(dispatch={"mode": "dry_run", "class": "learn"}), "schwab_quote_read_class:'learn'"),
])
def test_a_wrong_registry_shape_is_refused(allow, active, row, problem):
    assert LD.schwab_quote_read_shape_problem(row) == problem
    assert LD._schwab_quote_read_lift(row) == frozenset()


def test_a_missing_allowlist_entry_is_refused(active, monkeypatch):
    monkeypatch.setattr(LD, "load_run_allowlist_entries", lambda path=None: {})
    assert LD.schwab_quote_read_shape_problem(_row()) == "schwab_quote_read_not_allowlisted"


def test_any_other_forbidden_token_still_blocks(allow, active):
    e = allow(_entry(live_arg=["--apply"]))
    argv = {LANE: f"$PY {SCRIPT} --dry-run place_order"}
    ok, reason = LD.dispatch_eligible(_row(), allowlist_argv=argv, exceptions={}, cutover_policy={})
    assert not ok and "schwab" not in reason.split(":", 1)[1].split("@")[0], reason
    assert e  # shape itself is fine; the extra token is what refuses


def test_only_schwab_is_lifted():
    assert LD.SCHWAB_QUOTE_READ_TOKENS == frozenset({"schwab"})
    assert LD.SCHWAB_QUOTE_READ_MODULES == frozenset({"schwab_token_manager"})
    assert "schwab" not in LD.EXEMPTIBLE_TOKENS  # the generic exception file can never lift it


# --------------------------------------------------------------------------------------------- import-graph half


def test_the_real_entry_script_reaches_the_token_manager_only():
    rep = G.scan_entry(SCRIPT)
    assert not rep.trade_context and not rep.account_reads, rep.problems()
    assert not (rep.sends or rep.direct_sends or rep.bypass_router)
    assert all(set(m.split(".")) & LD.SCHWAB_QUOTE_READ_MODULES for m in rep.broker_modules), rep.broker_modules
    assert LD.schwab_quote_read_static_errors(_row(), _entry()) == []


@pytest.mark.parametrize("field,value,needle", [
    ("trade_context", ["scripts/x.py:OpenSecTradeContext"], "trade_context"),
    ("account_reads", ["scripts/x.py:get_account"], "account_read"),
    ("broker_modules", ["schwab_transport"], "broker_module:schwab_transport"),
    ("sends", ["scripts/x.py:send_telegram"], "send:"),
    ("direct_sends", ["scripts/x.py:smtplib"], "send:"),
])
def test_a_reach_beyond_quotes_is_an_error(monkeypatch, field, value, needle):
    rep = G.GuardReport(entry=SCRIPT)
    getattr(rep, field).extend(value)
    monkeypatch.setattr(G, "scan_entry", lambda script: rep)
    errs = LD.schwab_quote_read_static_errors(_row(), _entry())
    assert errs and any(needle in e for e in errs), errs


def test_registry_scan_runs_the_quote_read_check(monkeypatch):
    seen = []
    monkeypatch.setattr(LD, "schwab_quote_read_static_errors", lambda r, entry=None: seen.append(r["lane_id"]) or [])
    try:
        LD.registry_dispatch_errors({"lanes": [_row()]})
    except Exception:  # noqa: BLE001 -- other checks may need the real files; only the call matters here
        pass
    assert seen == [LANE]


# --------------------------------------------------------------------------------------------- code ↔ AGENTS.md


def _agents_state():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    version = re.search(r"^Policy-Version:\s+(\S+)", text, re.M).group(1)
    status = re.search(r"^Status:\s+(\S+)", text, re.M).group(1)
    row = re.search(r"^\| 32\.0\.0 \| [^|]+ \| (\w+) \|", text, re.M)
    return tuple(int(x) for x in version.split(".")), status, (row.group(1) if row else None), text


def test_code_status_agrees_with_agents_md():
    version, status, row_status, text = _agents_state()
    ratified = version >= (32, 0, 0) and status == "ACTIVE" and row_status == "ACTIVE" and "## 23.20a" in text
    assert (LD.SCHWAB_QUOTE_READ_STATUS == "ACTIVE") == ratified, (version, status, row_status)
    assert LD.SCHWAB_QUOTE_READ_STATUS in ("PROPOSED", "ACTIVE")
    assert LD.SCHWAB_QUOTE_READ_POLICY_VERSION == "32.0.0"
