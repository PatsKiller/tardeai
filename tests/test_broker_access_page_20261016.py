"""Broker Access & Sync — read model + API route + CC page (operator 2026-10-16).

Fixtures only: temp state roots, a fake ``db_query`` keyed on SQL text, a temp holdings document and a temp operator
sync log. No broker, no network, no DB, no send. Access mode is pinned through TRADEAI_SCHWAB_ACCESS_MODE.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import broker_access as ba  # noqa: E402

NOW = datetime(2026, 10, 16, 21, 30, tzinfo=timezone.utc)  # 17:30 ET, market closed
ACCTS = ["schwab_rollover_ira", "schwab_roth_ira", "schwab_taxable"]

SYNC_LOG = """mode=APPLY schwab_access=read_only release=22890d36d Fri Oct 16 05:15:47 PM EDT 2026

=== Schwab positions (3 accounts)
  "schwab_roth_ira": {"status": "degraded_noop", "reason": "no Schwab login token (manager is system-of-record)"}
    rc=0

=== Schwab transactions (7 days)
 "reason": "no Schwab login token (manager is system-of-record)"
    rc=0

=== Alpaca live read
  "wrote": true, "account_number": "12345678"
    rc=0

=== moomoo live read
  "wrote": true
    rc=0

=== SnapTrade
{"ok": false, "error": "no account mapping \\u2014 fill config/snaptrade_accounts.json"}
    rc=1

=== Positions store (all brokers)
 "run_id": 282
    rc=1

=== Positions freshness check
 "stale": false
    rc=0

=== Stop health (read-only report)
stop_health: DEGRADED — STOP HEALTH — DEGRADED: Schwab stop data unavailable
    rc=0
"""


class FakeDB:
    def __init__(self, *, tokens=None, logins=None, runs=None, latest=None, alerts=None, tx=None, hist=None,
                 down=False):
        self.calls: list[str] = []
        self.tokens, self.logins, self.runs, self.latest = tokens, logins, runs, latest
        self.alerts, self.tx, self.hist, self.down = alerts, tx, hist, down

    def __call__(self, sql, params=None, fetch="all"):
        self.calls.append(sql)
        if self.down:
            return None
        if "FROM broker_oauth_tokens" in sql:
            return self.tokens or []
        if "event='reauth'" in sql:
            return self.logins or []
        if "FROM broker_oauth_token_audit" in sql:
            return []
        if "max(finished_at)" in sql:
            return self.runs if self.runs is not None else [{"last_complete": None}]
        if "FROM positions_sync_runs ORDER BY" in sql:
            return self.latest or []
        if "FROM alert_events" in sql:
            return self.alerts or []
        if "FROM trade_transactions" in sql:
            return self.tx or []
        if "FROM schwab_sync_history" in sql:
            return self.hist or []
        raise AssertionError(f"unexpected SQL {sql}")


def _holdings(tmp: Path) -> Path:
    def acct(state, last, reason):
        return {"state": state, "account_state": {"state": state, "last_sync_at": last, "state_reason": reason}}
    doc = {"account_summaries": {
        "schwab_taxable": acct("STALE", "2026-10-14T00:00:00+00:00", "last sync 69.3h ago exceeds window 24h"),
        "schwab_roth": acct("STALE", "2026-10-14T00:00:00+00:00", "last sync 69.3h ago exceeds window 24h"),
        "schwab_rollover_ira": acct("STALE", "2026-10-14T00:00:00+00:00", "last sync 69.3h ago exceeds window 24h"),
        "alpaca_taxable_live": acct("LIVE", "2026-10-16T00:00:00+00:00", "synced 21.3h ago (window 24h)"),
        "moomoo_taxable_live": {**acct("LIVE", "2026-10-16T20:45:00+00:00", "synced 0.5h ago"), "retired": True,
                                "retired_reason": "account closed by operator"},
    }}
    p = tmp / "store.json"
    p.write_text(json.dumps(doc))
    return p


def _state_root(tmp: Path, *, stop_status="degraded") -> Path:
    rt = tmp / "state" / "data" / "runtime"
    (rt / "sync_receipts").mkdir(parents=True)
    (rt / "sync_receipts" / "moomoo_taxable_live.json").write_text(json.dumps(
        {"account": "moomoo_taxable_live", "ok": True, "at": "2026-10-16T21:15:50+00:00", "error": None,
         "n_rows": 2, "wrote": True}))
    (rt / "moomoo_opend_health.json").write_text(json.dumps({"ok": True, "checked_at": "2026-10-16T21:20:00+00:00"}))
    (rt / "alpaca_live_read_fail_streak.json").write_text(json.dumps({"alpaca_taxable_live": 0}))
    (rt / "snaptrade_sync_state.json").write_text(json.dumps({"missing": {}}))
    (rt / "schwab_auto_reauth_state.json").write_text(json.dumps(
        {"last_attempt_at": "2026-08-11T12:00:01+00:00", "last_result": "fail",
         "last_error": "callback https://127.0.0.1/?code=SECRETCODE123&session=x", "attempts_count": 2}))
    hb = {"status": stop_status, "finished_at": "2026-10-16T21:15:51+00:00", "stops": 0 if stop_status != "ok" else 12,
          "alert_count": 0, "schwab_stops": {"status": "UNAVAILABLE" if stop_status == "degraded" else "OK",
                                             "reason": "schwab_read_failed: schwab_taxable: token degraded",
                                             "failed_accounts": ["schwab_taxable"], "paused": False}}
    (rt / "stop_health_last.json").write_text(json.dumps(hb))
    return tmp / "state"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "normal")
    monkeypatch.setenv("TRADEAI_TRADING_LOCK_AUDIT_PATH", str(tmp_path / "lock_audit.jsonl"))
    (tmp_path / "lock_audit.jsonl").write_text(
        json.dumps({"event": "refused", "ts": "2026-10-16T14:00:00+00:00", "broker": "schwab", "action": "place",
                    "caller": "x.submit"}) + "\n"
        + json.dumps({"event": "refused", "ts": "2026-10-15T14:00:00+00:00", "broker": "schwab"}) + "\n")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "sync_all_20261016T211547Z_apply.log").write_text(SYNC_LOG)
    (logs / "sync_all_20261015T100000Z_apply.log").write_text("mode=APPLY\n=== Old\n    rc=0\n")
    return {"root": _state_root(tmp_path), "holdings": _holdings(tmp_path), "logs": logs, "tmp": tmp_path}


def _build(env, db, **kw):
    return ba.build(env["root"], db, NOW, holdings_path=env["holdings"], sync_log_dir=env["logs"], **kw)


def _healthy_tokens():
    login = NOW - timedelta(days=2)
    return ([{"account_key": a, "refresh_expires_at": NOW + timedelta(days=5), "next_reauth_due_at": None,
              "access_expires_at": NOW, "degraded": False, "last_error": None, "updated_at": NOW,
              "has_token": True} for a in ACCTS],
            [{"account_key": a, "last_login": login} for a in ACCTS])


def _brokers(d):
    return {b["id"]: b for b in d["brokers"]}


def test_tokens_ok_and_needs_reauth(env):
    toks, logins = _healthy_tokens()
    d = _build(env, FakeDB(tokens=toks, logins=logins))
    rows = {t["account_key"]: t for t in d["schwab_tokens"]["accounts"]}
    assert set(rows) == set(ACCTS)
    assert all(r["state"] == "OK" and 4.9 < r["days_left"] < 5.1 for r in rows.values())
    toks[0] = {**toks[0], "degraded": True, "last_error": "HTTP 401 Unauthorized"}
    toks[1] = {**toks[1], "has_token": False}
    d = _build(env, FakeDB(tokens=toks, logins=logins))
    rows = {t["account_key"]: t for t in d["schwab_tokens"]["accounts"]}
    assert rows[ACCTS[0]]["state"] == "NEEDS_REAUTH" and "401" in rows[ACCTS[0]]["reason"]
    assert rows[ACCTS[1]]["state"] == "NEEDS_REAUTH"
    assert _brokers(d)["schwab_positions"]["state"] == "NEEDS_REAUTH"
    assert d["overall"] == "NEEDS_REAUTH"


def test_one_login_covers_every_account(env):
    """Live shape 2026-10-16: only schwab_taxable has a token row; the other accounts read through it."""
    toks, logins = _healthy_tokens()
    only = [{**toks[2], "degraded": True, "last_error": "Schwab rejected the login token (HTTP 401)"}]
    d = _build(env, FakeDB(tokens=only, logins=[logins[2]]))
    rows = {t["account_key"]: t for t in d["schwab_tokens"]["accounts"]}
    assert set(rows) == set(ACCTS) and all(r["state"] == "NEEDS_REAUTH" for r in rows.values())
    assert rows["schwab_roth_ira"]["token_source"] == "schwab_taxable"
    assert "shares the schwab_taxable login" in rows["schwab_roth_ira"]["reason"]
    assert rows["schwab_roth_ira"]["login_source"] == "audit:newest_any_account"
    healthy = _build(env, FakeDB(tokens=[toks[2]], logins=[logins[2]]))
    assert all(r["state"] == "OK" for r in healthy["schwab_tokens"]["accounts"])


def test_paused_mode_wins_but_keeps_token_condition(env, monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    toks, logins = _healthy_tokens()
    toks[0] = {**toks[0], "degraded": True}
    d = _build(env, FakeDB(tokens=toks, logins=logins))
    t = {r["account_key"]: r for r in d["schwab_tokens"]["accounts"]}
    assert t[ACCTS[0]]["state"] == "PAUSED" and t[ACCTS[0]]["token_condition"] == "NEEDS_REAUTH"
    b = _brokers(d)
    assert b["schwab_positions"]["state"] == "PAUSED" and "NEEDS_REAUTH" in b["schwab_positions"]["flags"]
    assert b["schwab_transactions"]["state"] == "PAUSED"
    assert d["relogin"]["warning"]


def test_empty_db_answers_are_never_ok(env):
    d = _build(env, FakeDB(down=True))
    assert all(t["state"] == "DEGRADED" for t in d["schwab_tokens"]["accounts"])
    assert d["schwab_tokens"]["db"] == "unavailable"
    b = _brokers(d)
    assert b["positions_store"]["state"] == "DEGRADED" and "no evidence" in b["positions_store"]["reason"]
    assert d["stop_health"]["alerts_db"] == "unavailable"
    d = ba.build(env["tmp"] / "empty", None, NOW, holdings_path=env["tmp"] / "missing.json",
                 sync_log_dir=env["tmp"] / "nolog")
    assert d["overall"] != "OK"
    assert all(b["state"] != "OK" for b in d["brokers"])
    assert d["stop_health"]["state"] == "DEGRADED" and d["operator_sync_log"]["present"] is False


def test_broker_rows_from_receipts(env):
    toks, logins = _healthy_tokens()
    db = FakeDB(tokens=toks, logins=logins,
                runs=[{"last_complete": NOW - timedelta(hours=10)}],
                latest=[{"run_id": 282, "status": "partial", "promoted": False, "accounts_ok": ["moomoo_taxable_live"],
                         "accounts_failed": json.dumps({"schwab_taxable": "no token"}),
                         "started_at": NOW, "finished_at": NOW}],
                tx=[{"account": "schwab_taxable", "last_trade_date": (NOW - timedelta(days=9)).date(), "n": 40}])
    b = _brokers(_build(env, db))
    assert b["schwab_positions"]["state"] == "STALE" and "69.3h" in b["schwab_positions"]["reason"]
    assert b["schwab_transactions"]["state"] == "STALE"
    assert b["alpaca_live"]["state"] == "OK"
    assert b["moomoo"]["state"] == "OK" and "retired" in (b["moomoo"]["note"] or "")
    assert b["snaptrade"]["state"] == "DEGRADED" and "no account mapping" in b["snaptrade"]["reason"]
    ps = b["positions_store"]
    assert ps["state"] == "DEGRADED" and "partial" in ps["reason"] and ps["freshness"]["stale"] is False
    assert ps["latest_run"]["accounts_failed"] == {"schwab_taxable": "no token"}


def test_positions_store_check_fresh_semantics(env):
    toks, logins = _healthy_tokens()
    db = FakeDB(tokens=toks, logins=logins, runs=[{"last_complete": NOW - timedelta(hours=80)}])
    ps = _brokers(_build(env, db))["positions_store"]
    assert ps["state"] == "STALE" and ps["freshness"]["limit_s"] == 72 * 3600  # closed-market limit
    assert ps["semantics"] == "positions_sync.py --check-fresh"


def test_alpaca_fail_streak_degrades(env):
    (env["root"] / "data/runtime/alpaca_live_read_fail_streak.json").write_text(json.dumps({"alpaca_taxable_live": 3}))
    b = _brokers(_build(env, FakeDB(down=True)))
    assert b["alpaca_live"]["state"] == "DEGRADED" and "×3" in b["alpaca_live"]["reason"]


def test_operator_log_parsed_not_echoed(env):
    d = _build(env, FakeDB(down=True))
    log = d["operator_sync_log"]
    assert log["path"] == "sync_all_20261016T211547Z_apply.log" and log["mode"] == "APPLY"
    assert log["release"] == "22890d36d" and log["ran_at"] == "2026-10-16T21:15:47+00:00"
    steps = {s["name"]: s for s in log["steps"]}
    assert steps["SnapTrade"]["rc"] == 1 and "no account mapping" in steps["SnapTrade"]["signals"]
    assert "needs re-auth" in steps["Schwab positions (3 accounts)"]["signals"]
    assert log["failed_steps"] == ["SnapTrade", "Positions store (all brokers)"]
    blob = json.dumps(d)
    assert "12345678" not in blob and "system-of-record" not in json.dumps(log)
    # with no token store, the log's own evidence still raises NEEDS_REAUTH on the Schwab rows
    assert "NEEDS_REAUTH" in _brokers(d)["schwab_positions"]["flags"]


def test_stop_health(env):
    alerts = [{"id": 7, "created_at": NOW, "symbol": "SPCX", "severity": "critical", "raw_text": "STOP ORPHANED",
               "lifecycle_state": "active"}]
    d = _build(env, FakeDB(down=False, alerts=alerts))
    sh = d["stop_health"]
    assert sh["state"] == "DEGRADED" and sh["headline"] == "DEGRADED: Schwab stop data unavailable"
    assert sh["open_alert_count"] == 1 and sh["open_alerts"][0]["symbol"] == "SPCX"


@pytest.mark.trading_locked
def test_trading_lock_and_no_secrets(env):
    d = _build(env, FakeDB(down=True))
    assert d["trading_lock"]["locked"] is True and d["trading_lock"]["refusals_today"] == 1
    blob = json.dumps(d)
    assert "SECRETCODE123" not in blob and "refresh_token_enc" not in blob
    assert ba.scrub("refresh_token=abc.def acct 987654321") == "refresh_token=[redacted] acct [number]"


def test_token_sql_never_selects_token_values():
    sql = ba.TOKEN_SQL.lower()
    assert "(refresh_token_enc is not null) as has_token" in sql
    selected = sql.split(" from ")[0]
    assert "access_token" not in selected and selected.count("refresh_token_enc") == 1


def test_sync_command_is_operator_run_and_disabled(env):
    d = _build(env, FakeDB(down=True))
    c = d["sync_command"]
    assert c["run_by"] == "operator" and c["run_action"] == {
        "enabled": False, "reason": "requires broker-read grant + ratified amendment"}
    assert c["apply"].endswith("sync_all_readonly.sh --apply")
    assert d["relogin"]["telegram"]["steps"][0]["command"] == "python3 scripts/schwab_auto_reauth.py --now"
    assert d["relogin"]["command_center"]["href"] == "/v3/system/schwab-reauth"
    assert {l["href"] for l in d["links"]} >= {"/v3/system/schwab-reauth", "/v3/coordination?tab=today"}


def test_cache(env):
    db = FakeDB(down=True)
    kw = dict(holdings_path=env["holdings"], sync_log_dir=env["logs"])
    ba._CACHE.clear()
    assert ba.get_broker_access(env["root"], db, NOW, **kw)["cache"] == "MISS"
    n = len(db.calls)
    assert ba.get_broker_access(env["root"], db, NOW, **kw)["cache"] == "HIT" and len(db.calls) == n
    assert ba.get_broker_access(env["root"], db, NOW, ttl_s=0, **kw)["cache"] == "MISS"


def test_read_model_never_imports_broker_clients():
    src = (ROOT / "scripts/lib/data_broker/broker_access.py").read_text()
    for banned in ("schwab_token_manager", "live_probe", "brokers.", "requests", "load_env", "urlopen",
                   "subprocess", "send_telegram", "env_bootstrap", "/.env", "'.env'", '".env"'):
        assert banned not in src, banned


def test_api_route_is_read_only_and_wired():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    i = src.index('base_path == "/api/v2/system/broker-access"')
    block = src[i:i + 600]
    assert "get_broker_access" in block and '405, {"ok": False, "error": "read_only"}' in block
    assert "db_query=_db_query" in block


def test_cc_page_wired_and_has_no_run_control():
    app = (ROOT / "apps/command-center-v3/src/App.tsx").read_text()
    assert 'path="system/broker-access"' in app and "BrokerAccessPage" in app
    nav = (ROOT / "apps/command-center-v3/src/components/NavRail.tsx").read_text()
    assert "'/system/broker-access'" in nav
    page = (ROOT / "apps/command-center-v3/src/pages/BrokerAccessPage.tsx").read_text()
    assert "/api/v2/system/broker-access" in page and "watchTokens" in page
    assert "method: 'POST'" not in page and "fetch(" not in page
    assert "disabled aria-disabled" in page
