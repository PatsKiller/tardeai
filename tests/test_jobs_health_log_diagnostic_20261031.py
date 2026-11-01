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
# Host-neutral and generic-user paths: the redaction rules match the URL path (/bot<digits>:<token>) and
# /home/<user>, not the host or a real operator account, so the fixtures exercise the same regexes without
# tripping the Telegram chokepoint ratchet or the PII scan.
LEAKS = [
    ("requests.exceptions.HTTPError: 404 Client Error: Not Found for url: "
     "https://example.invalid/bot8123456789:AAHfakeTOKENfakeTOKENfake123/sendMessage",
     ["8123456789:AAH", "AAHfakeTOKEN"]),
    ("requests.exceptions.HTTPError: 403 Client Error: Forbidden for url: "
     "https://elite.finviz.com/export.ashx?v=152&t=SPY&auth=fa4e1c2b-0000-1111-2222-abcdefabcdef",
     ["fa4e1c2b-0000", "auth="]),
    ("requests.exceptions.HTTPError: 401 Client Error: Unauthorized for url: https://api.polygon.io/v2/aggs?apiKey=PKFAKEKEY123",
     ["PKFAKEKEY123"]),
    ("KeyError: 'sk-ant-api03-FAKEFAKEFAKEFAKE'", ["sk-ant-api03", "FAKEFAKEFAKE"]),
    ("ValueError: invalid dsn: postgresql://trade_ai:hunter2@127.0.0.1:5432/trade_ai", ["hunter2", "trade_ai:"]),
    ("RuntimeError: schwab refresh failed: refresh_token: Zx9FAKErefresh", ["Zx9FAKErefresh"]),
    ("PermissionError: [Errno 13] Permission denied: '/home/example/.config/tradeai/secrets/bws_openclaw_gateway.env'",
     ["bws_openclaw_gateway", "/home/example"]),
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


# ── Review round 2 (2026-11-01): shapes that still reached the page ─────────────────────────────────────
# Every value below is synthetic. Key-shaped strings are assembled at runtime so the commit scanner does not flag them.
_ASIA = "AS" + "IA" + "QWERTYUIOPASDFGH"
_AWS_SECRET = "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "SYNTHKEY"
_B64 = "c2stYW50LWFwaTAz" + "LXNlY3JldHZhbHVlMTIzNDU2"
ROUND2 = [
    ("RuntimeError: Authorization: Token 9f8e7d6c5b4a39281706", ["9f8e7d6c5b4a39281706"]),
    (f"botocore.exceptions.ClientError: temp key {_ASIA} rejected", [_ASIA]),
    (f"botocore.exceptions.ClientError: SignatureDoesNotMatch for secret {_AWS_SECRET}", [_AWS_SECRET, "K7MDENG"]),
    (f"ValueError: bad padding in '{_B64}'", [_B64]),
    ("RuntimeError: POST body grant_type%3Drefresh_token%26refresh_token%3DZx9FAKErefresh failed", ["Zx9FAKErefresh"]),
    ("RuntimeError: body %7B%22access_token%22%3A%22Zx9FAKEaccess%22%7D", ["Zx9FAKEaccess"]),
    ("RuntimeError: SCHWAB_APP_KEY=AbCdEfGh12345678 rejected", ["AbCdEfGh12345678"]),
    ("RuntimeError: schwab client_id=AbCdEfGh1234 rejected", ["AbCdEfGh1234"]),
    ("RuntimeError: missing ALPACA_KEY_ID=PKABCDEFGH12345678", ["PKABCDEFGH12345678"]),
    ('RuntimeError: login failed password: "correct horse battery staple"', ["correct", "horse", "battery", "staple"]),
    ("requests.exceptions.HTTPError: 401 for url: wss://stream.example.com/ws/AbCdSecretPathToken123",
     ["AbCdSecretPathToken123"]),
]


def _round2(idx):
    from scripts.lib.error_line_redaction import redact_error_line

    line, secrets = ROUND2[idx]
    shown = redact_error_line(line, home="/home/nobody")
    assert "[REDACTED]" in shown, shown
    for secret in secrets:
        assert secret not in shown, (secret, shown)
    assert line.split(":", 1)[0] in shown
    return shown


def test_round2_authorization_token_scheme_value_redacted():
    assert _round2(0) == "RuntimeError: Authorization: [REDACTED]"


def test_round2_asia_temporary_aws_key_redacted():
    _round2(1)


def test_round2_bare_aws_secret_redacted():
    _round2(2)


def test_round2_bare_base64_blob_redacted():
    _round2(3)


def test_round2_url_encoded_refresh_token_redacted():
    assert "grant_type=refresh_token" in _round2(4)  # decoded, and only the value goes


def test_round2_url_encoded_access_token_redacted():
    _round2(5)


def test_round2_app_key_pair_redacted():
    _round2(6)


def test_round2_client_id_pair_redacted():
    _round2(7)


def test_round2_key_id_pair_redacted():
    _round2(8)


def test_round2_quoted_value_with_spaces_redacted_to_closing_quote():
    assert _round2(9) == 'RuntimeError: login failed password: "[REDACTED]"'


def test_round2_wss_path_token_redacted_and_host_kept():
    assert "wss://stream.example.com/ws/[REDACTED]" in _round2(10)


def test_round2_whole_authorization_header_in_a_dict_is_redacted():
    from scripts.lib.error_line_redaction import redact_error_line

    shown = redact_error_line("RuntimeError: headers={'Authorization': 'Bearer abc.def-ghi'}", home="")
    assert shown == "RuntimeError: headers={'Authorization': '[REDACTED]'}"


def test_round2_bearer_without_an_authorization_header_is_redacted():
    from scripts.lib.error_line_redaction import redact_error_line

    shown = redact_error_line("RuntimeError: upstream rejected Bearer abcdef.ghijkl-mnop", home="")
    assert shown == "RuntimeError: upstream rejected Bearer [REDACTED]"


def test_round2_other_users_home_path_is_shortened():
    from scripts.lib.error_line_redaction import redact_error_line

    shown = redact_error_line("FileNotFoundError: /home/alice/app/state.json", home="/home/nobody")
    assert shown == "FileNotFoundError: ~/app/state.json"


def test_round2_stderr_path_is_strictly_redacted():
    stderr = "Traceback\n  File x\nRuntimeError: Authorization: Token 9f8e7d6c5b4a39281706\n"
    shown = DD.cause({"stderr_tail": stderr})
    assert "9f8e7d6c5b4a39281706" not in shown and "Authorization: [REDACTED]" in shown


def test_round2_a_400_char_cut_never_leaves_a_token_fragment(tmp_path):
    line = "RuntimeError: " + "y" * 380 + " sk-ant-api03-ABCDEFGHIJKLMNOP"
    err = J.last_log_error(_log(tmp_path, line + "\n"))
    assert "sk-" not in err["line"] and err["line"].endswith(" …") and len(err["line"]) <= 402


def test_round2_ordinary_error_text_stays_readable():
    from scripts.lib.error_line_redaction import redact_error_line

    for text in (
        "AssertionError: ALPACA_MODE must be paper",
        "ModuleNotFoundError: No module named 'scripts.lib.jobs_health_log_diagnostic_20261031'",
        'psycopg2.OperationalError: connection to server at "localhost" (127.0.0.1), port 5432 failed',
        "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='api.example.com', port=443): Max retries",
        "OAuthError: invalid_grant (refresh expired 2026-10-30T16:57:02Z)",
        "FileNotFoundError: /usr/lib/python3.14/site-packages/requests/adapters.py",
        "ValueError: expected 50% of 2026-10-30 orders",
    ):
        assert redact_error_line(text, home="/home/nobody") == text


def test_round2_telegram_path_token_of_any_shape_is_redacted():
    from scripts.lib.error_line_redaction import redact_error_line

    shown = redact_error_line("HTTPError: 404 for url: https://example.invalid/bot123456:abcdefghij/sendMessage", home="")
    assert shown == "HTTPError: 404 for url: https://example.invalid/bot[REDACTED]/sendMessage"


def test_round2_bare_lowercase_hex_secret_is_redacted():
    from scripts.lib.error_line_redaction import redact_error_line

    shown = redact_error_line("ValueError: bad signature 9f8e7d6c5b4a39281706abcd", home="")
    assert shown == "ValueError: bad signature [REDACTED]"


# ── Review round 3 (2026-11-01, probe_redact3.py): shapes that still leaked, and a linear pass ─────────────

def _r3(line):
    from scripts.lib.error_line_redaction import redact_error_line

    return redact_error_line(line, home="/home/nobody")


def _secret(*parts):
    return "".join(parts)  # assembled at runtime so no literal token shape sits in the source


ROUND3 = [
    ("space-separated key", "RuntimeError: finnhub rejected key " + _secret("c1a2b3c4d5", "e6f7g8h9i0j1k2"),
     "c1a2b3c4d5e6f7g8h9i0j1k2"),
    ("single-case upper run", "APIError: forbidden for key " + _secret("PKA1B2C3D4", "E5F6G7H8I9"), "PKA1B2C3D4E5F6G7H8I9"),
    ("single-case lower run", "RuntimeError: secret is all-lowercase " + _secret("k3j4h5g6f7d8s9a0", "q1w2e3r4t5y6u7i8"),
     "k3j4h5g6f7d8s9a0q1w2e3r4t5y6u7i8"),
    ("bare uuid", "RuntimeError: invalid auth " + _secret("fa4e1c2b-0000-1111", "-2222-abcdefabcdef"),
     "fa4e1c2b-0000-1111-2222-abcdefabcdef"),
    ("google ya29", "RuntimeError: google oauth " + _secret("ya29.a0AfB_byC1xYz", "-AbcDef12_GhIjKl34"), "a0AfB_byC1xYz"),
    ("discord webhook tail",
     "HTTPError: 401 for url: https://discord.com/api/webhooks/1234567890/" + _secret("abcDEF-ghi_JKL", "-mno_PQR"),
     "abcDEF-ghi_JKL-mno_PQR"),
    ("dotted token", "RuntimeError: refresh rejected: " + _secret("I0.b2F1dGgy.YmMuY", "-2Fwa_S1zY2h3YWI.AvBGW"),
     "b2F1dGgy"),
    ("mysql -p", "RuntimeError: mysql -u root -p " + _secret("hunter2", "hunter2") + " failed", "hunter2hunter2"),
    ("mysql -pPW", "RuntimeError: mysqldump -uroot -p" + _secret("hunter2", "hunter2") + " db", "hunter2hunter2"),
    ("pw quoted with space", 'RuntimeError: pw="' + _secret("a ", "b") + '" done', '"a b"'),
    ("triple percent", "RuntimeError: triple %252570assword%25253D" + _secret("hunter", "2"), "hunter2"),
]


def test_round3_every_leaking_shape_is_redacted():
    for name, line, secret in ROUND3:
        shown = _r3(line)
        assert secret not in shown and "[REDACTED]" in shown, (name, shown)
        assert shown.split(":", 1)[0] == line.split(":", 1)[0], name


def test_round3_discord_keeps_the_webhook_id():
    assert _r3(ROUND3[5][1]).endswith("discord.com/api/webhooks/1234567890/[REDACTED]")


def test_round3_quoted_value_keeps_both_quotes_and_the_rest():
    assert _r3("RuntimeError: x pw=\"a b\" token='c d' done") == "RuntimeError: x pw=\"[REDACTED]\" token='[REDACTED]' done"


def test_round3_stderr_path_redacts_the_new_shapes():
    stderr = "Traceback\nRuntimeError: finnhub rejected key " + _secret("c1a2b3c4d5", "e6f7g8h9i0j1k2") + "\n"
    shown = DD.cause({"stderr_tail": stderr})
    assert "c1a2b3c4d5e6f7g8h9i0j1k2" not in shown and "[REDACTED]" in shown


def test_round3_redaction_is_linear():
    import time

    from scripts.lib.error_line_redaction import redact_error_line

    for big in ("RuntimeError: " + ("a:" * 30000),
                "RuntimeError: " + ("aB3/" * 16000) + ("x=" * 4000) + ('"' + "a" * 10000),
                "RuntimeError: " + ("password=" * 6000)):
        t0 = time.perf_counter()
        redact_error_line(big, home="")
        assert time.perf_counter() - t0 < 0.5, len(big)


def test_round3_ordinary_error_text_stays_readable():
    for text in (
        "AssertionError: ALPACA_MODE must be paper",
        'File "/usr/lib/python3.14/json/decoder.py", line 363, in raw_decode',
        "scripts.lib.n8n_dlq_disposition.cause failed at 2026-10-31T13:50:05.906418+00:00",
        "ModuleNotFoundError: No module named 'scripts.lib.test_market_context_afterhours_close_20261031'",
        "deploy refused: commit 9ac8a87 is not on main",
        "the key is missing",
        "password authentication failed for user trade_ai",
        "KeyError: 'AAPL'",
        'psycopg2.OperationalError: connection to server at "localhost" (127.0.0.1), port 5432 failed',
        "urllib3.exceptions.MaxRetryError: HTTPSConnectionPool(host='api.example.com', port=443)",
        "botocore.exceptions.NoCredentialsError: Unable to locate credentials",
    ):
        assert _r3(text) == text, text


def test_round3_documented_choice_long_hex_shas_and_uuid_run_ids_are_redacted():
    # Deliberate (module docstring): a 40-hex SHA looks exactly like a hex API key, and a UUID run id like a Finviz
    # token, so both go; a short SHA stays.
    assert _r3("ValueError: build 9ac8a87305156bbfcac6784a3f57b66436752b48 mismatch") == \
        "ValueError: build [REDACTED] mismatch"
    assert _r3("run_id=8f3c2a10-1b2c-4d5e-8f90-123456789abc") == "run_id=[REDACTED]"


def test_round3_percent_decoding_is_capped():
    from scripts.lib import error_line_redaction as E

    deep = "x" + "%25" * 0 + "%" + "25" * 20 + "41"
    assert E.MAX_PERCENT_DECODES <= 10
    assert "%" in E._percent_decode(deep)  # stops after the cap instead of looping forever


def test_round3_base64_with_plus_and_slash_is_redacted_whole():
    # Every '+'/'/'-separated piece is short, so only the base64-run rule (not the alphanumeric one) sees it.
    blob = _secret("aB3+dE5/gH7+", "jK9/mN1+pQ3x")
    shown = _r3("RuntimeError: signature " + blob + " rejected")
    assert shown == "RuntimeError: signature [REDACTED] rejected"


def test_round3_short_space_separated_key_value_is_redacted():
    # Under 20 characters, so only the "key <value>" rule sees it.
    shown = _r3("RuntimeError: provider rejected key " + _secret("Abc123", "xyz9") + " today")
    assert shown == "RuntimeError: provider rejected key [REDACTED] today"


def test_round3_lowercase_ya29_token_is_redacted():
    # No upper case, so the joined-token rule would not see it: only the ya29 shape does.
    shown = _r3("RuntimeError: oauth " + _secret("ya29.a0afb_byc1", "xyz-abcdef12") + " expired")
    assert shown == "RuntimeError: oauth [REDACTED] expired"


def test_round3_short_joined_version_strings_stay_readable():
    for text in ("release v2.3a-Beta1 failed", "pip install Django4.2b1 failed"):
        assert _r3(text) == text, text


def test_round3_quoted_value_runs_to_its_own_closing_quote():
    assert _r3("RuntimeError: pw=\"it's x9 y\" end") == "RuntimeError: pw=\"[REDACTED]\" end"


# ── Review round 4 (2026-11-01, probe_redact4.py) ────────────────────────────────────────────────────────────

def test_round4_escaped_json_key_value_is_redacted():
    shown = _r3('RuntimeError: body {\\"password\\": \\"' + _secret("hunter", "2xyz") + '\\"}')
    assert "hunter2xyz" not in shown
    assert shown == 'RuntimeError: body {\\"password\\": \\"[REDACTED]\\"}'


def test_round4_escaped_json_quote_inside_value_is_not_an_early_stop():
    shown = _r3('RuntimeError: {\\"token\\": \\"ab\\\\cd' + _secret("ef", "99") + '\\"}')
    assert "ef99" not in shown and "[REDACTED]" in shown


def test_round4_userinfo_is_split_at_the_last_at_sign():
    shown = _r3("RuntimeError: https://user:p@" + _secret("ssw0", "rd") + "@db.example.com/x")
    assert "ssw0rd" not in shown
    assert shown == "RuntimeError: https://[REDACTED]@db.example.com/x"


def test_round4_passphrase_is_a_secret_key_word():
    assert _r3("RuntimeError: passphrase " + _secret("hunter2", "hunter2")) == "RuntimeError: passphrase [REDACTED]"
    assert _r3("RuntimeError: ssh_passphrase=" + _secret("opensesame", "now")) == "RuntimeError: ssh_passphrase=[REDACTED]"


def test_round4_letters_only_token_after_a_key_word_is_redacted():
    assert _r3("RuntimeError: key " + _secret("aBcDeFgHiJkLm", "NoPqRsTuVwXyZ")) == "RuntimeError: key [REDACTED]"


def test_round4_authorization_token_scheme_is_still_redacted():
    assert _r3("RuntimeError: Authorization: Token " + _secret("9f8e7d6c5b", "4a39281706")) == \
        "RuntimeError: Authorization: [REDACTED]"


def test_round4_over_redaction_cases_stay_readable():
    for text in (
        'psycopg2.errors.ForeignKeyViolation: insert or update on table "orders" violates foreign key constraint '
        '"fk_orders_account"',
        'psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "uq_x_symbol_date"',
        "ValueError: max_tokens: 4096 exceeds limit 2048",
        "ValueError: input_tokens=5000 output_tokens=1200",
        "RuntimeError: token expired; re-auth required",
        "RuntimeError: schwab token refresh failed: invalid_grant",
        "RuntimeError: token refresh required",
        "RuntimeError: key rotation required",
        "RuntimeError: password authentication failed",
    ):
        assert _r3(text) == text, text


def test_round4_undotted_violation_class_is_not_a_key():
    text = 'ForeignKeyViolation: insert or update on table "orders" violates foreign key constraint'
    assert _r3(text) == text


def test_round4_escaped_json_count_key_stays_readable():
    text = 'ValueError: request {\\"max_tokens\\": 4096} too large'
    assert _r3(text) == text


# ── Review round 5 (2026-11-01, probe_redact6.py): the round-4 exclusions must not leak ────────────────────────

def test_round5_token_plural_key_with_a_string_value_is_redacted():
    shown = _r3("RuntimeError: {'access_tokens': '" + _secret("Zx9FAKE", "access123") + "'}")
    assert shown == "RuntimeError: {'access_tokens': '[REDACTED]'}"


def test_round5_dotted_camelcase_setting_is_still_a_key():
    assert _r3("RuntimeError: settings.ApiKey=" + _secret("Zx9FAKE", "key123")) == "RuntimeError: settings.ApiKey=[REDACTED]"


def test_round5_dotted_password_attribute_is_still_a_key():
    assert _r3("RuntimeError: cfg.Password: " + _secret("hunter", "2xyz")) == "RuntimeError: cfg.Password: [REDACTED]"


def test_round5_token_count_exclusion_needs_an_integer():
    assert _r3("ValueError: max_tokens=-1 invalid") == "ValueError: max_tokens=-1 invalid"
    assert _r3("ValueError: token_count: " + _secret("abc", "def99")) == "ValueError: token_count: [REDACTED]"


def test_round5_dotted_exception_class_still_not_a_key():
    text = "psycopg2.errors.UndefinedTableWarning: relation missing"
    assert _r3(text) == text


def test_round5_account_number_in_prose_is_redacted():
    # Synthetic numbers, assembled at runtime so the PII scan sees no literal account number in git.
    acct_a = "1234" + "5678"
    acct_b = "8765" + "4321"
    acct_c = "1122" + "3344"
    assert _r3(f"RuntimeError: Schwab 401 for account {acct_a}") == "RuntimeError: Schwab 401 for account [REDACTED]"
    assert _r3(f"RuntimeError: acct #{acct_b} not found") == "RuntimeError: acct #[REDACTED] not found"
    assert _r3(f"RuntimeError: account number: {acct_c} locked") == "RuntimeError: account number: [REDACTED] locked"
    text = "RuntimeError: account 12 of 3 failed"
    assert _r3(text) == text
