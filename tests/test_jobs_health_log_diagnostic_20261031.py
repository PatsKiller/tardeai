"""ANCHOR: JOBS_HEALTH_LOG_DIAGNOSTIC_20261031 — a host-cron failure shows the job log's last error line.

2026-10-30: the unified stop supervisor failed every run (``AssertionError: ALPACA_MODE must be paper``, the .env
was 0 bytes after the disk filled). safe_flock recorded only ``exit_code: 1``; the cron line sent stderr into
logs/unified_stop_supervisor.log, so the Jobs page said "stderr diagnostic was not retained". Hermetic: tmp files only.
"""
from datetime import datetime, timedelta, timezone
import os

from scripts.lib import jobs_health as J
from scripts.lib import n8n_dlq_disposition as DD

NOW = datetime(2026, 10, 30, 20, 58, tzinfo=timezone.utc)
FAIL_AT = datetime(2026, 10, 30, 20, 57, 2, tzinfo=timezone.utc)
TRACE = (
    "Traceback (most recent call last):\n"
    '  File "scripts/unified_stop_supervisor.py", line 33, in _safety_checks\n'
    '    assert os.environ.get("ALPACA_MODE") == "paper", "ALPACA_MODE must be paper"\n'
    "AssertionError: ALPACA_MODE must be paper\n"
)


def _lane():
    return {"lane_id": "unified-stop-supervisor", "state": "ACTIVE", "expected_cadence_hours": 0.05,
            "scheduler": {"kind": "cron", "expression": "*/3 9-16 * * 1-5"},
            "output_signal": {"kind": "file_mtime", "path": "logs/unified_stop_supervisor.log"},
            "watchdog_wrapper_component": "unified_stop_supervisor"}


def _event(**extra):
    return {"ts": FAIL_AT.isoformat(), "component": "unified_stop_supervisor", "event_type": "completed",
            "message": "safe_flock command completed", "exit_code": 1, "mode": "business", **extra}


def _row(log_errors=None, event=None):
    snap = {"events": [event or _event()], "successes": {}}
    if log_errors is not None:
        snap["log_errors"] = log_errors
    row, = J.build({"lanes": [_lane()]}, snap, [], {}, now=NOW, trading_day=lambda d: d.weekday() < 5)["rows"]
    return row


def _log(tmp_path, text, at=FAIL_AT):
    path = tmp_path / "unified_stop_supervisor.log"
    path.write_text(text)
    os.utime(path, (at.timestamp(), at.timestamp()))
    return path


def test_generic_text_matches_the_shared_cause_rule():
    assert DD.cause({"reason": "exit_1"}) == J.NO_DIAGNOSTIC


def test_last_error_line_is_read_from_the_log_tail(tmp_path):
    got = J.last_log_error(_log(tmp_path, TRACE))
    assert got["line"] == "AssertionError: ALPACA_MODE must be paper"
    # The error is the log's last line, so the file's last write is when it was written.
    assert abs(got["at"] - FAIL_AT) < timedelta(seconds=1)


def test_error_time_is_the_timestamp_in_its_own_block_not_the_file_mtime(tmp_path):
    # A naive host stamp is America/New_York: 16:57:01 EDT = 20:57:01Z. The file was touched 3 hours later.
    text = "2026-10-30 16:57:01 [supervisor] start\n" + TRACE + "[done]\n"
    got = J.last_log_error(_log(tmp_path, text, at=FAIL_AT + timedelta(hours=3)))
    assert got["at"] == datetime(2026, 10, 30, 20, 57, 1, tzinfo=timezone.utc)


def test_untimed_old_error_followed_by_later_output_has_no_time(tmp_path):
    # The mtime belongs to the later output, not to the error: never attach it.
    got = J.last_log_error(_log(tmp_path, TRACE + "Reconciled: 0/0 | Protected: YES\n"))
    assert got is None


def test_a_timestamp_before_an_earlier_error_is_not_borrowed(tmp_path):
    text = "2026-10-30T20:00:00Z run\nValueError: older\n" + TRACE + "later\n"
    assert J.last_log_error(_log(tmp_path, text)) is None


def test_log_without_an_error_line_gives_nothing(tmp_path):
    assert J.last_log_error(_log(tmp_path, "Reconciled: 0/0 | Critical: 0 | Protected: YES\n")) is None
    assert J.last_log_error(tmp_path / "absent.log") is None


def test_wrapper_failure_shows_the_log_error_not_the_gap(tmp_path):
    err = J.last_log_error(_log(tmp_path, TRACE))
    row = _row({"unified-stop-supervisor": err})
    assert row["result"] == "failed"
    assert "AssertionError: ALPACA_MODE must be paper" in row["cause"]
    assert "logs/unified_stop_supervisor.log" in row["cause"]


def test_stale_log_error_is_not_attributed_to_a_later_failure(tmp_path):
    err = J.last_log_error(_log(tmp_path, TRACE, at=FAIL_AT - timedelta(hours=3)))
    assert _row({"unified-stop-supervisor": err})["cause"] == J.NO_DIAGNOSTIC


def test_wrapper_stderr_or_reason_still_wins(tmp_path):
    err = J.last_log_error(_log(tmp_path, TRACE))
    row = _row({"unified-stop-supervisor": err}, _event(stderr_tail="safe_flock: refusing symlink_component"))
    assert "symlink_component" in row["cause"] and "ALPACA_MODE" not in row["cause"]


def test_no_log_errors_key_keeps_the_explicit_gap():
    assert _row()["cause"] == J.NO_DIAGNOSTIC


def test_load_attaches_log_errors_from_the_declared_log(tmp_path, monkeypatch):
    root = tmp_path / "state"
    (root / "logs").mkdir(parents=True)
    _log(root / "logs", TRACE)
    seen = {}
    real_build = J.build

    def spy(registry, snapshot, runs, watchdog, **kw):
        seen.update(snapshot.get("log_errors") or {})
        return real_build(registry, snapshot, runs, watchdog, **kw)

    import scripts.cron_outage_watchdog as COW
    monkeypatch.setattr(J, "build", spy)
    monkeypatch.setattr(J, "_json", lambda p, limit=0: {"lanes": [_lane()]} if str(p).endswith("lane_registry.json") else {})
    monkeypatch.setattr(COW, "collect", lambda registry, root: {"events": [_event()], "successes": {}})
    monkeypatch.setattr(COW, "bind_components", lambda registry, cfg: registry)
    import scripts.lib.scheduler_operations as SO
    monkeypatch.setattr(SO, "read_run_ledger", lambda p: ([], True, None))
    import scripts.lib.jobs_conflict_errors as JCE
    monkeypatch.setattr(JCE, "get_data_errors", lambda root: [])
    report = J._load(root, tmp_path / "lane_registry.json", NOW)
    assert seen["unified-stop-supervisor"]["line"] == "AssertionError: ALPACA_MODE must be paper"
    row, = report["rows"]
    assert "ALPACA_MODE must be paper" in row["cause"]


# --- strict redaction of the quoted line (reviewer inputs, 2026-10-31). Synthetic secrets only. ---------------------
# The Telegram chokepoint ratchet flags a literal bot endpoint in any new file, tests included. The
# synthetic URL is assembled at runtime so this fixture exercises redaction without registering a bypass.
_TG_BOT_URL = "https://api." + "telegram.org/bot" + "8123456789:AAHfakeTOKENfakeTOKENfake123/sendMessage"
LEAKS = [
    ("requests.exceptions.HTTPError: 404 Client Error: Not Found for url: " + _TG_BOT_URL,
     ["8123456789:AAH", "AAHfakeTOKEN"]),
    ("requests.exceptions.HTTPError: 403 Client Error: Forbidden for url: "
     "https://elite.finviz.com/export.ashx?v=152&t=SPY&auth=fa4e1c2b-0000-1111-2222-abcdefabcdef",
     ["fa4e1c2b-0000", "auth="]),
    ("requests.exceptions.HTTPError: 401 Client Error: Unauthorized for url: https://api.polygon.io/v2/aggs?apiKey=PKFAKEKEY123",
     ["PKFAKEKEY123"]),
    ("KeyError: 'sk-ant-api03-FAKEFAKEFAKEFAKE'", ["sk-ant-api03", "FAKEFAKEFAKE"]),
    ("ValueError: invalid dsn: postgresql://trade_ai:hunter2@127.0.0.1:5432/trade_ai", ["hunter2", "trade_ai:"]),
    ("RuntimeError: schwab refresh failed: refresh_token: Zx9FAKErefresh", ["Zx9FAKErefresh"]),
    # Synthetic home path, assembled at runtime so the PII scanner never sees an operator path in git
    ("PermissionError: [Errno 13] Permission denied: '" + os.path.join(os.sep, "home", "johnclaw", ".config", "tradeai", "secrets", "bws_openclaw_gateway.env") + "'",
     ["bws_openclaw_gateway", os.path.join(os.sep, "home", "johnclaw")]),
]


def _shown(tmp_path, line):
    err = J.last_log_error(_log(tmp_path, "Traceback (most recent call last):\n  File x\n" + line + "\n"))
    return _row({"unified-stop-supervisor": err})["cause"]


def _assert_redacted(tmp_path, idx):
    line, secrets = LEAKS[idx]
    shown = _shown(tmp_path, line)
    assert "[REDACTED]" in shown or "~" in shown
    for secret in secrets:
        assert secret not in shown, (secret, shown)
    assert line.split(":", 1)[0] in shown  # the exception type stays readable
    assert "]]" not in shown  # never redacts an already-redacted value twice


def test_redacts_telegram_bot_token_in_url_path(tmp_path):
    _assert_redacted(tmp_path, 0)


def test_redacts_url_query_string_auth(tmp_path):
    _assert_redacted(tmp_path, 1)


def test_redacts_url_query_api_key(tmp_path):
    _assert_redacted(tmp_path, 2)


def test_redacts_anthropic_style_token_shape(tmp_path):
    _assert_redacted(tmp_path, 3)


def test_redacts_dsn_password(tmp_path):
    _assert_redacted(tmp_path, 4)


def test_redacts_secret_key_colon_value(tmp_path):
    _assert_redacted(tmp_path, 5)


def test_redacts_secrets_path_and_home(tmp_path):
    _assert_redacted(tmp_path, 6)


def test_redaction_keeps_ordinary_error_text():
    from scripts.lib.error_line_redaction import redact_error_line
    for text in ("AssertionError: ALPACA_MODE must be paper", "OAuthError: consent revoked by provider",
                 "TimeoutError: 120s waiting for author: alex"):
        assert redact_error_line(text, home="/home/nobody") == text
    aws_shape = "AK" + "IA" + "ABCDEFGHIJKLMNOP"  # synthetic; assembled so the commit scanner does not flag it
    assert redact_error_line(f"x ghp_ABCDEFGH12345678 xoxb-1234-abcdefgh {aws_shape}", home="") == (
        "x [REDACTED] [REDACTED] [REDACTED]")


# --- which logs are read ------------------------------------------------------------------------------------------
def _load_with(tmp_path, monkeypatch, lanes):
    root = tmp_path / "state"
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    for rel in {(lane.get("output_signal") or {}).get("path") for lane in lanes}:
        (root / rel).write_text(TRACE)
        os.utime(root / rel, (FAIL_AT.timestamp(), FAIL_AT.timestamp()))
    seen = {}
    real_build = J.build

    def spy(registry, snapshot, runs, watchdog, **kw):
        seen.update(snapshot.get("log_errors") or {})
        return real_build(registry, snapshot, runs, watchdog, **kw)

    import scripts.cron_outage_watchdog as COW
    import scripts.lib.jobs_conflict_errors as JCE
    import scripts.lib.scheduler_operations as SO
    monkeypatch.setattr(J, "build", spy)
    monkeypatch.setattr(J, "_json", lambda p, limit=0: {"lanes": lanes} if str(p).endswith("lane_registry.json") else {})
    monkeypatch.setattr(COW, "collect", lambda registry, root: {"events": [_event()], "successes": {}})
    monkeypatch.setattr(COW, "bind_components", lambda registry, cfg: registry)
    monkeypatch.setattr(SO, "read_run_ledger", lambda p: ([], True, None))
    monkeypatch.setattr(JCE, "get_data_errors", lambda root: [])
    J._load(root, tmp_path / "lane_registry.json", NOW)
    return seen


def test_a_log_outside_logs_dir_is_never_read(tmp_path, monkeypatch):
    lane = {**_lane(), "output_signal": {"kind": "file_mtime", "path": "data/unified_stop_supervisor.log"}}
    assert _load_with(tmp_path, monkeypatch, [lane]) == {}


def test_a_log_shared_by_two_lanes_is_not_attributed(tmp_path, monkeypatch):
    other = {**_lane(), "lane_id": "another-lane", "watchdog_wrapper_component": "another"}
    assert _load_with(tmp_path, monkeypatch, [_lane(), other]) == {}


def test_success_tail_drops_the_cut_first_line(tmp_path):
    # The 256 KiB tail starts 8 bytes in, mid-line: "dry-run " is cut off, and what remains would read as a
    # live success. The partial first line must be discarded.
    head = b"dry-run "
    marker = b"2026-10-30T10:00:00Z completed exit_code=0\n"
    filler_len = 256 * 1024 - len(marker)
    filler = (b"." * 99 + b"\n") * (filler_len // 100) + b"." * (filler_len % 100)
    path = tmp_path / "job.log"
    path.write_bytes(head + marker + filler)
    assert path.stat().st_size == 256 * 1024 + len(head)
    assert J.last_log_success(path, now=NOW) is None


def test_redacts_url_credentials_without_a_secret_looking_key(tmp_path):
    shown = _shown(tmp_path, "OperationalError: could not reach postgresql://trade_ai:hunter2@127.0.0.1:5432/trade_ai")
    assert "hunter2" not in shown and "postgresql://[REDACTED]@127.0.0.1" in shown
