"""AGENTS.md 4.1.0 — registry-driven n8n dispatch, wave ladder, program window (§23.11–§23.14); PROPOSED 2026-10-09, ACTIVE 2026-10-09
(ratified `APPROVE_AGENTS_POLICY_4_1_0 1592 2f824b4f789110d6ccc5f3c7d5783aa9e995a079`).

The failures this guards against:

* an authority-widening amendment that reads as a grant before it is ratified (header, version row,
  `Expires-At: PENDING` while PROPOSED; a ratified expiry never later than 2026-10-12T23:59:59-04:00);
* one question with three answers — §17 said `cron`, §23.2 said `cron`/`config-write`, and
  scripts/check_n8n_activation_grants.py also accepted `service` (due-diligence audit E D5);
* a §23.5 that states a precondition as true while it is measured false (audit E C1/D7: the relay
  credential was created while the `n8n` role was a superuser; weekly rotation is not scheduled);
* a dispatcher that can reach a broker, order, secret-render or daemon lane (§23.14). The predicate
  `dispatcher_eligible` below is the mechanism §23.14 names; it is exercised on every allowlist entry
  and on synthetic negatives so it is not vacuous while no registry row uses the dispatcher yet;
* §0, §2, §2A or §7A changing under cover of an n8n amendment (sha256 pinned at the base commit).

Works while 4.1.0 is PROPOSED and after the ratification edit (branches on the 4.1.0 row status).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_n8n_activation_grants as GRANTS  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.pipelines import pipeline_manifest as PM  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
ALLOW_LANES = {e["lane_id"]: e for e in ALLOW["lanes"]}
REGISTRY = {
    r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]
}
THIS_FILE = "tests/test_agents_policy_4_1_0_amendment.py"

TOKEN = "APPROVE_AGENTS_POLICY_4_1_0"
WINDOW_END = "2026-10-12T23:59:59-04:00"
HEADINGS = {
    "23.11": "## 23.11 Registry-driven dispatch (4.1.0)",
    "23.12": "## 23.12 Wave ladder (4.1.0)",
    "23.13": "## 23.13 Program window — push budget and standing merge approval (4.1.0)",
    "23.14": "## 23.14 Never dispatcher-eligible — broker, order, secret and daemon lanes (4.1.0)",
}

# §0, §2, §2A and §7A are byte-identical to the base this amendment was written on (origin/main 079e8ff42,
# AGENTS.md 4.0.0 ACTIVE; the same four hashes held at 306f583f0, 3.0.0 ACTIVE). An amendment that changes
# one of them is not this amendment: it needs its own version and its own operator token (§17, §20).
BASE_COMMIT = "079e8ff42"
# Operator-requested amendment 5.0.0 (asked for as "4.7.0", 2026-10-10 ~21:50 ET; PROPOSED, pending
# APPROVE_AGENTS_POLICY_5_0_0): §0 rule 2 gains exactly this one sentence, pointing to §24.10. It is removed before
# hashing, so the digest below still proves every other byte of §0 is unchanged; the sentence itself is pinned by
# tests/test_agents_policy_5_0_0_execution_ops.py. Nothing else in §0 or §2 may move.
RULE_2_EXCEPTION_5_0_0 = (
    "\n   One operational exception, binding only once AGENTS.md 5.0.0 is ACTIVE: with an operator"
    "\n   `execution-ops` grant naming the unit, an agent may inspect, re-point, reload and restart that"
    "\n   broker-execution unit while markets are closed, and never touch its code, credentials, flags or"
    "\n   orders (AGENTS.md §24.10)."
)
PINNED_SECTIONS = {
    "§0": (
        "# 0 · If you read nothing else",
        "# 1 · Identity and responsibilities",
        "61fe9dfbeaa3c61cf354e42ed1cdc6f7006a105b46d538cd79a74407f349af32",
    ),
    "§2": ("# 2 · Authority rails", "# 2A ·", "5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af"),
    "§2A": ("# 2A ·", "# 2B ·", "38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb"),
    "§7A": ("# 7A ·", "# 8 ·", "6d20888d1329397351c75a54a4c3e2e7978d5974cef6c3c306dc708580b5ca90"),
}


# ---------------------------------------------------------------------------------------------- helpers


def _flat(text: str) -> str:
    """Prose is wrapped at ~100 columns; compare with whitespace collapsed."""
    return re.sub(r"\s+", " ", text)


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _version() -> tuple[int, ...]:
    return tuple(int(x) for x in _control("Policy-Version").split("."))


def _section(text: str, start: str, end: str) -> str:
    s = re.search(rf"^{re.escape(start)}", text, re.M)
    assert s, start
    e = re.search(rf"^{re.escape(end)}", text[s.start() + 1 :], re.M)
    assert e, end
    block = text[s.start() : s.start() + 1 + e.start()]
    block = block.replace(RULE_2_EXCEPTION_5_0_0, "")  # operator-requested amendment 5.0.0; see the constant
    # §7A embeds a GENERATED table (render_source_of_truth.py); mask it so only rule text is pinned.
    # Operator 2026-10-10 ~18:40 ET ("Yes, from one to six", item 5); §20 PATCH.
    return re.sub(r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)", r"\1\n<generated>\n\2", block, flags=re.S)


def _section_23() -> str:
    m = re.search(r"^# 23 · .*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert m, "§23 not found"
    return m.group(0)


def _section_17() -> str:
    return _section(AGENTS, "# 17 · Operator-only decisions", "# 17A ·")


def _subsection(number: str) -> str:
    m = re.search(rf"^## {re.escape(number)} .*?(?=^## |^---$|^# |\Z)", _section_23(), re.M | re.S)
    assert m, number
    return m.group(0)


def _row() -> re.Match:
    m = re.search(r"^\| 4\.1\.0 \| 2026-10-09 \| (PROPOSED|ACTIVE) \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 4.1.0 | 2026-10-09 | PROPOSED|ACTIVE | MAJOR |` version row"
    return m


def _proposed() -> bool:
    return _row().group(1) == "PROPOSED"


# ---------------------------------------------------------------------------------------- header + row


def test_header_is_4_1_0_proposed_or_later():
    assert _version() >= (4, 1, 0)
    if _version() == (4, 1, 0) and _control("Status") == "PROPOSED":
        assert _control("Effective-Date") == "PENDING"
        assert _control("Supersedes") == "4.0.0"


def test_version_row_is_major_and_pending_while_proposed():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and TOKEN in rest
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 4.1.0 row must record the token, PR and sha"


def test_section_23_headings_present_and_exact():
    s = _section_23()
    for n in ("23.1", "23.2", "23.3", "23.4", "23.5", "23.6", "23.7", "23.8", "23.9", "23.10"):
        assert re.search(rf"^## {re.escape(n)} ", s, re.M), n
    for n, heading in HEADINGS.items():
        assert re.search(rf"^{re.escape(heading)}$", s, re.M), f"§{n} heading not exactly {heading!r}"


# --------------------------------------------------------------------------------------- §23.11–§23.14


def test_23_11_registry_driven_dispatch():
    s = _subsection("23.11")
    f = _flat(s)
    low = f.lower()
    for name in (
        "dispatcher",
        "event router",
        "heartbeat watcher",
        "incident router",
        "digest scheduler",
        "approval router",
    ):
        assert name in low, name
    assert '"dispatcher"' in s  # scheduler.expression = "dispatcher" (no new scheduler kind)
    assert "coordination/due" in f
    assert "scheduler.cadence" in f and "cron_schedule.py" in f
    assert "no per-lane" in low and "import" in low and "grant" in low
    assert "server-side" in low


def test_23_12_wave_ladder():
    f = _flat(_subsection("23.12"))
    for frag in ("`dry_run`", "`live`", "natural-equivalent", "per line"):
        assert frag in f, frag
    for word in ("shadow", "canary", "cutover"):
        assert word in f.lower(), word
    assert "scheduler.stage" in f
    assert re.search(r"`cron` grant[^.]*\bnam(?:e|es|ing)\b[^.]*\blanes?\b", f), (
        "a `cron` grant naming the wave's lanes"
    )


def _expires_at() -> str:
    m = re.search(r"Expires-At:\s*`?([^\s`]+)", _subsection("23.13"))
    assert m, "§23.13 carries no `Expires-At:` line"
    return m.group(1).rstrip(".,;)")


def test_23_13_program_window_push_budget_and_standing_merge_approval():
    f = _flat(_subsection("23.13"))
    assert "n8nmat/" in f
    assert re.search(r"\b(?:4|four)\b[^.]*\bpush", f, re.I), "push budget of 4 for n8nmat/*"
    assert WINDOW_END in f
    for frag in (
        "agent-governance",
        "cio-hardening",
        "release-readiness",
        "exact head",
        "review verdict",
        "program board",
        "self-approval",
        "main CI is green on the exact merged SHA",
    ):
        assert frag in f, frag
    # the merge queue is not available on a user-owned repository; no condition may depend on it
    assert "goes through the merge queue" not in f
    assert "operator enables the GitHub merge queue" not in _flat(AGENTS)
    assert "tradeai_push_budget.py" in f and ".githooks/pre-push" in f
    # the standing approval never covers the policy, the hooks, the guard or the broker file set
    for frag in ("AGENTS.md", ".githooks/", "bin/guard"):
        assert frag in f, frag


def test_23_13_expiry_is_pending_while_proposed_and_never_past_the_window():
    value = _expires_at()
    if _proposed():
        assert value == "PENDING", value
        return
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)", value), value
    expires = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert expires <= datetime.fromisoformat(WINDOW_END), f"standing approval {value} outlives the program window"


def test_23_14_states_the_rule_and_names_its_mechanism():
    f = _flat(_subsection("23.14"))
    assert "Broker, order, secret and daemon lanes are never dispatcher-eligible." in f
    for frag in (THIS_FILE, "FORBIDDEN_COMMAND_TOKENS", "FORBIDDEN_ROUTE_TOKENS", "trade-ai-scalp-live"):
        assert frag in f, frag


def test_every_new_bullet_cites_its_cause():
    for n in HEADINGS:
        bullets = re.split(r"^- ", _subsection(n), flags=re.M)[1:]
        assert bullets, f"§{n} has no bullets"
        for b in bullets:
            assert "Cause (§" in _flat(b), f"§{n} bullet without a Cause: {_flat(b)[:90]!r}"


def test_new_text_carries_no_absolute_home_path():
    home = "/home/" + "johnclaw"
    for n in HEADINGS:
        assert home not in _subsection(n), n
    assert home not in _row().group(0)


# ------------------------------------------------------------------------------------ one grant tier


def test_one_activation_tier_cron_in_17_23_2_and_the_checker():
    assert "`cron`" in _section_17()
    assert "`cron` grant" in _flat(_subsection("23.2"))
    old = "a `cron` grant for the crontab/timer side, a `config-write` grant for units"
    # §23.7 quotes the replaced sentence by design (§20: replaced, not accumulated); nowhere else may.
    live_text = AGENTS.replace(_subsection("23.7"), "")
    assert old not in _flat(live_text)
    assert old in _flat(_subsection("23.7"))
    assert GRANTS.DEFAULT_TIERS == ("cron",)


# --------------------------------------------------------------------------------- truth fixes kept


def test_3_0_0_row_records_both_merges():
    m = re.search(r"^\| 3\.0\.0 \| 2026-10-09 \| ACTIVE \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m
    assert "#1552" in m.group(1) and "377e9b536" in m.group(1)


def test_23_5_states_the_superuser_breach_and_unscheduled_rotation():
    f = _flat(_subsection("23.5"))
    assert "the n8n database role is not a superuser before the credential exists" not in f
    assert "rolsuper" in f or "superuser" in f
    assert "2026-10-08T16:45:48Z" in f and "P13" in f
    assert "not scheduled" in f or "no rotation scheduler" in f


# ------------------------------------------------------------------------------- §0/§2/§2A/§7A pinned


@pytest.mark.parametrize("name", list(PINNED_SECTIONS))
def test_rail_sections_are_byte_identical_to_the_base(name):
    start, end, digest = PINNED_SECTIONS[name]
    block = _section(AGENTS, start, end)
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == digest, f"{name} changed"


def _base_agents() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:AGENTS.md"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8") if out.returncode == 0 else None


@pytest.mark.parametrize("name", list(PINNED_SECTIONS))
def test_rail_sections_match_git_base_when_available(name):
    base = _base_agents()
    if base is None:
        pytest.skip(f"git or base commit {BASE_COMMIT} unavailable (shallow clone); the pinned hash still applies")
    start, end, digest = PINNED_SECTIONS[name]
    assert hashlib.sha256(_section(base, start, end).encode("utf-8")).hexdigest() == digest, "pin is wrong"
    assert _section(AGENTS, start, end) == _section(base, start, end), f"{name} differs from {BASE_COMMIT}"


# --------------------------------------------------------------------- §23.14 dispatcher eligibility

DAEMON_TOKENS = ("--daemon", "--loop", "--forever", "--watch", "--serve")
SECRET_TOKENS = ("render_env", "sm-render", "sm_render", "secrets/", "rotation_daemon", "bws ", "bitwarden")
# The 4.0.0 named exception: an ingest writer and send_telegram caller that may run live from n8n. It is a
# name, not a class (tests/test_agents_policy_4_0_0_scalp_lane.py): any other sender or ingest writer is refused.
SCALP_EXCEPTION = "trade-ai-scalp-live"
SCALP_CONDITIONS = {
    "command": ["$PY", "scripts/run_trade_ai_scalp_live.py"],
    "lock": "/tmp/tradeai_scalp_live.lock",
    "lock_kind": "flock",
    "timeout_s": 295,
    "market_gate": True,
}
SENDER_OR_INGEST_TOKENS = (
    "run_trade_ai_scalp_live",
    "continuous_runner",
    "finviz_ingestion",
    "send_telegram",
    "telegram",
    "notify",
    "_ingest",
    "ingestion",
)


def _forbidden_words(text: str) -> list[str]:
    """FORBIDDEN_COMMAND_TOKENS + FORBIDDEN_ROUTE_TOKENS (+ SECRET_KEYS and the dispatcher extras) under the
    whole-word / path-segment matcher of scripts/lib/lane_dispatch.forbidden_text_hits — operator ruling
    2026-10-10 ~00:20 ET (n8n-maturity REMEDIATION_PLAN §7 ruling 2). Words, path segments, flags and env
    assignments are compared, not substrings: `topic` no longer trips `stop`. The safety matrix proving every
    real broker/order/stop/secret lane still blocks is tests/test_lane_dispatch_word_boundary_20261010.py."""
    return LD.forbidden_text_hits(text)


def _is_service_daemon(scheduler: dict | None) -> bool:
    """A systemd service with no timer (or Restart=always) is a daemon, not a scheduled run."""
    for text in ((scheduler or {}).get("expression") or "", (scheduler or {}).get("match") or ""):
        if "Restart=always" in text or (".service" in text and ".timer" not in text):
            return True
    return False


def dispatcher_eligible(entry: dict, registry_row: dict | None = None) -> tuple[bool, str]:
    """AGENTS.md 4.1.0 §23.14: may the generic dispatcher relay this allowlist entry? Returns (ok, reason)."""
    argv = [*entry.get("command", []), *(entry.get("dry_run_arg") or []), *(entry.get("live_arg") or [])]
    if not argv:
        return False, "no command"
    for tok in argv:
        if tok in DAEMON_TOKENS or any(tok.startswith(d + "=") for d in DAEMON_TOKENS):
            return False, f"daemon flag {tok}"
    if _is_service_daemon((registry_row or {}).get("scheduler")) or "Restart=always" in str(entry.get("source", "")):
        return False, "systemd service lane (daemon)"
    for tok in [*argv, " ".join(argv)]:
        hits = _forbidden_words(tok)
        command_hits = [h for h in hits if h in PM.FORBIDDEN_COMMAND_TOKENS]
        if command_hits:
            return False, f"broker/order token {command_hits} (FORBIDDEN_COMMAND_TOKENS)"
        if hits:
            return False, f"forbidden token {hits} (FORBIDDEN_ROUTE_TOKENS / SECRET_KEYS / dispatcher extras)"
        low = tok.lower()
        for secret in SECRET_TOKENS:
            if secret.strip() in low:
                return False, f"secret token {secret.strip()}"
    joined = " ".join(argv).lower()
    sender = next((t for t in SENDER_OR_INGEST_TOKENS if t in joined), None)
    if entry.get("lane_id") == SCALP_EXCEPTION:
        drift = {k: entry.get(k) for k, v in SCALP_CONDITIONS.items() if entry.get(k) != v}
        if drift:
            return False, f"{SCALP_EXCEPTION} no longer meets the 4.0.0 conditions: {drift}"
        return True, "4.0.0 named exception"
    if sender:
        return False, f"sender or ingest writer {sender} (only {SCALP_EXCEPTION} is excepted, by name)"
    return True, "ok"


def _dispatcher_rows() -> list[dict]:
    return [
        r
        for r in REGISTRY.values()
        if (r.get("scheduler") or {}).get("kind") == "n8n"
        and (r.get("scheduler") or {}).get("expression") == "dispatcher"
    ]


def test_every_dispatcher_row_is_allowlisted_eligible_and_staged():
    from scripts.lib import cron_schedule

    for row in _dispatcher_rows():
        lane = row["lane_id"]
        sched = row["scheduler"]
        assert lane in ALLOW_LANES, f"{lane}: dispatcher row without a config/n8n_run_allowlist.json entry"
        ok, reason = dispatcher_eligible(ALLOW_LANES[lane], row)
        assert ok, f"{lane}: {reason}"
        assert sched.get("match"), f"{lane}: scheduler.match names the cron line it retires"
        assert sched.get("cadence") and cron_schedule.parse(sched["cadence"]), lane
        assert sched.get("wave") and sched.get("stage") in {"shadow", "canary", "cutover"}, lane


# Allowlist lanes the dispatcher must not relay, with the reason the predicate gives. Empty today: every
# allowlisted lane is eligible. A lane added here is reported, not silently skipped.
EXPECTED_INELIGIBLE: dict[str, str] = {}


def test_every_allowlist_lane_is_eligible_or_explicitly_reported():
    verdicts = {lane: dispatcher_eligible(e, REGISTRY.get(lane)) for lane, e in ALLOW_LANES.items()}
    ineligible = {lane: reason for lane, (ok, reason) in verdicts.items() if not ok}
    assert set(ineligible) == set(EXPECTED_INELIGIBLE), ineligible
    for lane, frag in EXPECTED_INELIGIBLE.items():
        assert frag in ineligible[lane], (lane, ineligible[lane])


def _entry(lane_id: str, command: list[str], dry=("--dry-run",), live=(), **kw) -> dict:
    return {
        "lane_id": lane_id,
        "command": command,
        "lock": f"/tmp/{lane_id}.lock",
        "lock_kind": "flock",
        "timeout_s": 60,
        "dry_run_arg": list(dry),
        "live_arg": list(live),
        **kw,
    }


@pytest.mark.parametrize(
    ("entry", "row", "why"),
    [
        (_entry("broker-place", ["$PY", "scripts/schwab_place_order.py"]), None, "place_order"),
        (_entry("order-route", ["$PY", "scripts/submit_orders.py"]), None, "order"),
        (_entry("position-sync", ["$PY", "scripts/schwab_position_sync.py"]), None, "schwab_position_sync.py"),
        (_entry("stop-sup", ["$PY", "scripts/unified_stop_supervisor.py"]), None, "unified_stop_supervisor"),
        (_entry("secret-render", ["$PY", "scripts/render_env.py"], live=("--write",)), None, "render_env"),
        (_entry("sm-render", ["bash", "scripts/sm-render.sh"]), None, "sm-render"),
        (_entry("daemon-flag", ["$PY", "scripts/n8n_pilot_dispatch.py"], live=("--daemon",)), None, "--daemon"),
        (_entry("daemon-loop", ["$PY", "scripts/foo.py", "--loop"]), None, "--loop"),
        (
            _entry("svc", ["$PY", "scripts/foo.py"]),
            {"scheduler": {"kind": "systemd", "expression": "tradeai-foo.service (Restart=always)"}},
            "daemon",
        ),
        (
            _entry("svc2", ["$PY", "scripts/foo.py"]),
            {"scheduler": {"kind": "n8n", "expression": "dispatcher", "match": "tradeai-foo.service"}},
            "daemon",
        ),
        (_entry("sender", ["$PY", "scripts/send_no_leads_diagnostic_alert.py"]), None, "send"),
        (_entry("ingest", ["$PY", "scripts/finviz_ingestion.py"]), None, "ingest"),
        (_entry("by-analogy", ["$PY", "scripts/run_trade_ai_scalp_live.py"]), None, SCALP_EXCEPTION),
        (_entry("grant-maker", ["$PY", "scripts/issue_grant.py"]), None, "grant"),
        (
            _entry("env-submit", ["env", "MOMENTUM_SCALP_VALIDATION_SUBMIT=1", "$PY", "scripts/auto_proposal_generator.py"]),
            None,
            "submit",
        ),
        (_entry("flag-submit", ["$PY", "scripts/report.py", "--submit-validation"]), None, "submit"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_broker_order_secret_daemon_and_by_analogy_entries_are_refused(entry, row, why):
    ok, reason = dispatcher_eligible(entry, row)
    assert not ok, entry
    assert why in reason, reason


def test_the_scalp_exception_is_accepted_only_while_it_meets_the_4_0_0_conditions():
    good = {"lane_id": SCALP_EXCEPTION, "dry_run_arg": ["--dry-run"], "live_arg": [], **SCALP_CONDITIONS}
    assert dispatcher_eligible(good) == (True, "4.0.0 named exception")
    for key, bad in (("timeout_s", 600), ("market_gate", False), ("lock", "/tmp/other.lock"), ("lock_kind", "none")):
        ok, reason = dispatcher_eligible({**good, key: bad})
        assert not ok and key in reason, (key, reason)
    ok, reason = dispatcher_eligible({**good, "live_arg": ["--loop"]})
    assert not ok and "--loop" in reason
    if SCALP_EXCEPTION in ALLOW_LANES:
        assert dispatcher_eligible(ALLOW_LANES[SCALP_EXCEPTION], REGISTRY.get(SCALP_EXCEPTION))[0]


def test_a_plain_report_lane_is_eligible():
    assert dispatcher_eligible(_entry("ok", ["$PY", "scripts/storage_watch.py"], live=("--write",))) == (True, "ok")


@pytest.mark.parametrize(
    "script",
    ["scripts/topic_curator.py", "scripts/hermes_top20_external_intel.py", "scripts/hermes_synthesizer.py",
     "scripts/cash_redeploy_planner.py", "scripts/defense_inverse_stoplights.py"],
)
def test_word_boundary_ruling_false_positives_pass_the_token_test(script):
    """Operator ruling 2026-10-10 (REMEDIATION_PLAN §7 ruling 2): whole words, not substrings."""
    assert dispatcher_eligible(_entry("fp", ["$PY", script], live=("--apply",))) == (True, "ok")


# ---------------------------------------------------------------- read-only guard carve-out (4.1.0)

PROJECTION = ROOT / "scripts" / "lib" / "approval_board_projection.py"
GUARD_READ_SUBCOMMANDS = frozenset({"list", "state", "read", "audit"})
GUARD_WRITE_SUBCOMMANDS = frozenset(
    {"grant", "consume", "revoke", "revoke-all", "init", "recover", "doctor", "request", "approve", "settle"}
)


def test_23_14_states_the_read_only_guard_carve_out():
    f = _flat(_subsection("23.14"))
    assert "Read-only guard carve-out" in f
    assert "approval_board_projection.py" in f
    for verb in ("request", "grant", "revoke", "consume"):
        assert verb in f, verb
    assert "never" in f.lower()


def test_allowlist_never_list_still_blocks_guard():
    assert "guard" in ALLOW["never"]
    for lane_id, entry in ALLOW_LANES.items():
        argv = [*entry.get("command", []), *(entry.get("dry_run_arg") or []), *(entry.get("live_arg") or [])]
        for tok in argv:
            low = tok.lower()
            assert "bin/guard" not in low and "guard_ledger" not in low, (lane_id, tok)
            assert "guard_request_approval" not in low and "guard_remote_approval" not in low, (lane_id, tok)


def test_guard_projection_is_read_only():
    """The approval router may read guard state only: every subprocess call in the projection passes
    only read subcommands of the guard CLI, never a write subcommand, and it imports no guard writer."""
    import ast

    tree = ast.parse(PROJECTION.read_text(encoding="utf-8"))
    # "grant" is also a row kind on the board, so write subcommands are checked where they would act:
    # in the argv of every subprocess call (below), never as free strings.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
            for name in names:
                assert "guard_request_approval" not in name and "guard_remote_approval" not in name, name
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "subprocess":
                args = node.args[0] if node.args else None
                assert isinstance(args, ast.List), "subprocess argv must be a literal list"
                subs = [e.value for e in args.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                assert subs and set(subs) <= GUARD_READ_SUBCOMMANDS, subs
                assert not (set(subs) & GUARD_WRITE_SUBCOMMANDS), subs


def test_when_active_the_ratification_is_recorded():
    """Ratified 2026-10-09 with APPROVE_AGENTS_POLICY_4_1_0 1592 <sha>: an ACTIVE 4.1.0 carries a real date,
    the token and a concrete §23.13 expiry no later than the program window."""
    if _version() == (4, 1, 0) and _control("Status") == "ACTIVE":
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _control("Effective-Date"))
        assert not _proposed()
        status, rest = _row().group(1), _row().group(2)
        assert status == "ACTIVE"
        assert f"{TOKEN} 1592 2f824b4f789110d6ccc5f3c7d5783aa9e995a079" in rest
        assert "4.1.0 is PROPOSED" not in AGENTS
        assert "4.1.0 PROPOSED" not in AGENTS
        assert "PROPOSED in 4.1.0" not in AGENTS
        value = _expires_at()
        assert value != "PENDING"
        assert datetime.fromisoformat(value) <= datetime.fromisoformat(WINDOW_END)
