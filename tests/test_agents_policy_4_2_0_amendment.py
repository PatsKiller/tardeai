"""AGENTS.md 4.2.0 — n8n first for timed work, three named system lanes, independent dead-man switch, n8n
error-handling baseline (§23.3, §23.15–§23.17); PROPOSED 2026-10-09.

Operator direction 2026-10-09 ~21:00 ET, verbatim (typos are the operator's and are kept):
"why whould we use a cron in n8n , for notifications, n8n is there to relplace cron jobs" and
"we go n8n first for everything with timing cron only by my approval of your reccomendation".

The failures this guards against:

* an authority-widening amendment that reads as a grant before it is ratified (header, version row);
* the operator's words paraphrased away (both quotes are pinned verbatim at the top, in §23.15 and in the row);
* "a `cron` grant is enough" surviving in §17 or §9.3 after the operator required a recommendation plus his
  approval of it;
* the named system-lane exception quietly becoming a class: any other sender, or a sender that is not the
  host SYSTEM chokepoint, or a Telegram credential in n8n; and the one scalp exception bullet multiplying;
* a dead-man switch that depends on the thing it watches, or that is claimed as a control before its code
  exists (today the watchdog reads none of n8n, relay, gateway, notifier);
* the 4.2.0 lanes entering the allowlist before ratification (the implementation follows the vote);
* §0, §2, §2A or §7A changing under cover of an n8n amendment (sha256 pinned, same digests as 4.1.0).

Works while 4.2.0 is PROPOSED and after the ratification edit (branches on the 4.2.0 row status).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_agents_policy_state as STATE  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
ALLOW_LANES = {e["lane_id"]: e for e in ALLOW["lanes"]}
REGISTRY = {
    r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]
}
THIS_FILE = "tests/test_agents_policy_4_2_0_amendment.py"

TOKEN = "APPROVE_AGENTS_POLICY_4_2_0"
QUOTE_1 = "why whould we use a cron in n8n , for notifications, n8n is there to relplace cron jobs"
QUOTE_2 = "we go n8n first for everything with timing cron only by my approval of your reccomendation"
NAMED_LANES = ("incident-notifier", "n8n-activation-grants", "n8n-workflow-drift-check")
SENDER_LANE = "incident-notifier"
SYSTEM_CHOKEPOINT = "scripts/lib/autonomy_watchdog/telegram_system.py"
ERROR_STANDARD = "docs/implementation/n8n-maturity/03-error-handling-standard.md"
WATCHDOG_SERVICE = "tradeai-autonomy-watchdog.service"
WATCHDOG_TIMER = "tradeai-autonomy-watchdog.timer"
HEADINGS = {
    "23.15": "## 23.15 n8n first for timed work (4.2.0)",
    "23.16": "## 23.16 Independent dead-man switch (4.2.0)",
    "23.17": "## 23.17 n8n error-handling baseline (4.2.0)",
}

# §0, §2, §2A and §7A are byte-identical to the base this amendment was written on (origin/main b7dbe6e60,
# AGENTS.md 4.1.0 ACTIVE; the same four digests 4.1.0 pinned at 079e8ff42).
BASE_COMMIT = "b7dbe6e60"
PINNED_SECTIONS = {
    "§0": (
        "# 0 · If you read nothing else",
        "# 1 · Identity and responsibilities",
        "61fe9dfbeaa3c61cf354e42ed1cdc6f7006a105b46d538cd79a74407f349af32",
    ),
    "§2": ("# 2 · Authority rails", "# 2A ·", "5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af"),
    "§2A": ("# 2A ·", "# 2B ·", "38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb"),
    "§7A": ("# 7A ·", "# 8 ·", "c808d0216d13435c22320b86601885ac535213bf1c69006f6c0452955c3818be"),
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
    return text[s.start() : s.start() + 1 + e.start()]


def _section_23() -> str:
    m = re.search(r"^# 23 · .*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert m, "§23 not found"
    return m.group(0)


def _subsection(number: str) -> str:
    m = re.search(rf"^## {re.escape(number)} .*?(?=^## |^---$|^# |\Z)", _section_23(), re.M | re.S)
    assert m, number
    return m.group(0)


def _bullet(section_text: str, opener: str) -> str:
    for b in re.split(r"^- ", section_text, flags=re.M)[1:]:
        if b.startswith(opener):
            return _flat(b)
    raise AssertionError(f"no bullet opening {opener!r}")


def _row() -> re.Match:
    m = re.search(r"^\| 4\.2\.0 \| 2026-10-09 \| (PROPOSED|ACTIVE) \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 4.2.0 | 2026-10-09 | PROPOSED|ACTIVE | MAJOR |` version row"
    return m


def _proposed() -> bool:
    return _row().group(1) == "PROPOSED"


NAMED_EXCEPTION_OPENER = "**Named exception (4.2.0) — three system lanes"


# ---------------------------------------------------------------------------------------- header + row


def test_header_is_4_2_0_proposed_or_later():
    assert _version() >= (4, 2, 0)
    if _version() == (4, 2, 0) and _control("Status") == "PROPOSED":
        assert _control("Effective-Date") == "PENDING"
        assert _control("Supersedes") == "4.1.0"


def test_version_row_is_major_and_pending_while_proposed():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"`{TOKEN} <pr> <sha>`" in rest
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{40}}", rest), (
            "ACTIVE 4.2.0 row must record the token, PR and full sha"
        )
    for frag in (*NAMED_LANES, "send_system", "dead-man", ERROR_STANDARD, THIS_FILE):
        assert frag in rest, frag


def test_state_checker_passes_on_branch_and_on_main():
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_operator_words_are_verbatim_in_top_block_23_15_and_row():
    top = _flat(AGENTS.split("```", 2)[2][:6000])
    for q in (QUOTE_1, QUOTE_2):
        assert q in top, q
        assert q in _flat(_subsection("23.15")), q
        assert q in _row().group(2), q


def test_while_proposed_the_4_1_0_text_governs():
    if not _proposed():
        return
    top = _flat(AGENTS.split("```", 2)[2][:6000])
    assert "**4.2.0 is PROPOSED (MAJOR)" in top
    assert "The 4.1.0 text governs until the operator sends" in top
    assert "nothing 4.2.0 adds grants anything before then" in top
    s = _flat(_section_23()[:3000])
    assert "**4.2.0 PROPOSED**" in s and f"until `{TOKEN} <pr> <sha>` the 4.1.0 text governs" in s
    # 4.1.0 pattern: the §23 heading keeps naming the governing version until ratification
    assert re.search(r"^# 23 · .*— ACTIVE 4\.1\.0$", _section_23(), re.M)


def test_section_23_headings_present_and_exact():
    s = _section_23()
    for n in ("23.1", "23.2", "23.3", "23.7", "23.11", "23.12", "23.13", "23.14"):
        assert re.search(rf"^## {re.escape(n)} ", s, re.M), n
    for n, heading in HEADINGS.items():
        assert re.search(rf"^{re.escape(heading)}$", s, re.M), f"§{n} heading not exactly {heading!r}"
    order = [s.index(h) for h in HEADINGS.values()]
    assert order == sorted(order) and s.index("## 23.14 ") < order[0]


# --------------------------------------------------------------------------------- §23.15 n8n first


def test_23_15_n8n_first_and_recommendation_plus_approval():
    f = _flat(_subsection("23.15"))
    assert "Every new or moved timed job is scheduled by n8n by default" in f
    assert "registry-driven dispatch" in f and "(§23.11)" in f and "(§23.12)" in f
    for frag in (
        "new host cron line",
        "new systemd timer",
        "change to an existing cron line's schedule",
        "Agent A's written recommendation on the program board",
        "the reason",
        "the operator's explicit approval of that recommendation",
        "A `cron` grant alone is not enough",
    ):
        assert frag in f, frag
    assert "Existing cron and systemd lines stay until migrated by wave" in f
    assert "Broker, order, stop, secret and daemon lanes stay on host schedulers" in f
    assert 'not "moved"' in f and "(§23.14)" in f
    assert "The one sanctioned host-timer exception is the dead-man switch (§23.16)" in f


def test_17_and_9_3_carry_the_rule_in_place():
    s17 = _flat(_section(AGENTS, "# 17 · Operator-only decisions", "# 17A ·"))
    assert "any new production cron or systemd entry, **and any change to an existing cron line's schedule" in s17
    assert "Agent A's written recommendation on the program board and the operator's explicit approval" in s17
    assert "a `cron` grant alone is not enough" in s17 and "(§23.15" in s17
    # the 3.0.0-pinned line wrap of the Agent-node fragment is untouched
    assert "**activating an n8n Agent node, or creating the n8n bridge\ntoken**" in AGENTS
    s93 = _flat(_section(AGENTS, "## 9.3 Scheduled jobs", "## 9.4 "))
    b = _bullet(_section(AGENTS, "## 9.3 Scheduled jobs", "## 9.4 "), "**n8n first (4.2.0, §23.15).**")
    assert "a `cron` grant alone is not enough" in b and "explicit approval of that recommendation" in b
    assert QUOTE_2 in s93


# ------------------------------------------------------------------------- §23.3 named system lanes


def test_23_3_named_exception_names_exactly_three_lanes_and_its_conditions():
    s = _subsection("23.3")
    f = _flat(s)
    assert f.count(NAMED_EXCEPTION_OPENER) == 1
    assert f.count("**Exception (") == 1, "the 4.0.0 scalp exception stays the only `**Exception (` bullet"
    b = _bullet(s, NAMED_EXCEPTION_OPENER)
    for lane in NAMED_LANES:
        assert f"`{lane}`" in b, lane
    assert "(P16)" in b and "(P18)" in b
    for frag in (
        "n8n triggers, the host executes",
        "through the relay to `coordination/run`",
        "exact argv under its existing lock and timeout",
        "n8n holds no Telegram or broker credential",
        f"`{SYSTEM_CHOKEPOINT}` `send_system`",
        "produced on the host",
        "de-duplication, quiet hours and the daily cap stay host-side",
        "The two checkers are read-only and send nothing",
        "`FORBIDDEN_ROUTE_TOKENS` itself is unchanged",
        "All other senders remain forbidden",
        "no sender enters the allowlist by analogy",
        QUOTE_1,
    ):
        assert frag in b, frag
    # every other §23.3 sentence the 4.0.0/3.0.0 tests pin is still there
    assert "No other ingest writer or sender enters the allowlist by analogy" in f
    assert "**No sends from n8n.**" in f


def test_23_14_records_the_three_lanes_without_making_a_class():
    f = _flat(_subsection("23.14"))
    assert "Broker, order, secret and daemon lanes are never dispatcher-eligible." in f
    assert "**4.2.0 adds three system lanes by name, on their §23.3 4.2.0 terms**" in f
    assert "naming them makes no class" in f
    assert "the approval router's own escalation sender is not admitted by it" in f


def test_23_7_records_every_in_place_amendment():
    f = _flat(_subsection("23.7"))
    assert "4.2.0 (PROPOSED;" in f or "4.2.0 (ACTIVE" in f
    for frag in (
        '§17 "any new production cron or systemd entry"',
        '§9.3 gains the "n8n first" bullet',
        "§23.3 gains the named exception",
        '§23.14 "No other ingest writer or sender',
    ):
        assert frag in f, frag


# ---------------------------------------------- named-lane predicate (mechanism the exception describes)


SENDER_TOKENS = ("send_telegram", "telegram_alert", "sendMessage", "api.telegram.org", "smtp", "send_email")


def named_system_lane_ok(entry: dict, row: dict | None) -> tuple[bool, str]:
    """AGENTS.md 4.2.0 §23.3: may n8n dispatch this entry under the named system-lane exception?

    Only the three named lane ids; the argv must be the registry row's own command (the host executes what
    cron would); the two checkers must be read-only (no sender token); the notifier must be the SYSTEM
    chokepoint caller `scripts/incident_notifier.py`, never a direct sender."""
    lane = entry.get("lane_id")
    if lane not in NAMED_LANES:
        return False, f"{lane} is not a named 4.2.0 system lane"
    if row is None:
        return False, "no registry row"
    argv = " ".join([*entry.get("command", []), *(entry.get("live_arg") or [])])
    match = row["scheduler"].get("match", "")
    script = next((tok for tok in entry.get("command", []) if tok.endswith(".py")), "")
    if not script or script not in match:
        return False, f"argv {argv!r} is not the registry row's command {match!r}"
    sender = next((t for t in SENDER_TOKENS if t.lower() in argv.lower()), None)
    if sender:
        return False, f"direct sender token {sender}"
    if lane == SENDER_LANE and script != "scripts/incident_notifier.py":
        return False, "the notifier lane must run scripts/incident_notifier.py (send_system caller)"
    if lane != SENDER_LANE and "notifier" in script:
        return False, "a checker lane may not run a notifier"
    return True, "ok"


def _entry(lane: str, command: list[str], live: list[str] | None = None) -> dict:
    return {"lane_id": lane, "command": command, "live_arg": live or [], "dry_run_arg": ["--dry-run"]}


def test_named_registry_rows_exist_and_point_at_the_host_scripts():
    expect = {
        "incident-notifier": "scripts/incident_notifier.py",
        "n8n-activation-grants": "scripts/check_n8n_activation_grants.py",
        "n8n-workflow-drift-check": "scripts/check_n8n_workflow_drift.py",
    }
    for lane, script in expect.items():
        assert lane in REGISTRY, lane
        assert script in REGISTRY[lane]["scheduler"]["match"], lane
        assert (ROOT / script).is_file(), script


def test_the_notifier_sends_only_through_the_system_chokepoint():
    src = (ROOT / "scripts" / "incident_notifier.py").read_text(encoding="utf-8")
    assert "from scripts.lib.autonomy_watchdog.telegram_system import send_system" in src
    for bad in ("send_telegram(", "api.telegram.org", "TELEGRAM_BOT_TOKEN"):
        assert bad not in src, bad
    chk = (ROOT / SYSTEM_CHOKEPOINT).read_text(encoding="utf-8")
    assert re.search(r"^def send_system\(", chk, re.M)


@pytest.mark.parametrize(
    "entry,why",
    [
        (_entry("incident-notifier", ["$PY", "scripts/incident_notifier.py"], ["--live"]), "ok"),
        (_entry("n8n-activation-grants", ["$PY", "scripts/check_n8n_activation_grants.py"], ["--write"]), "ok"),
        (_entry("n8n-workflow-drift-check", ["$PY", "scripts/check_n8n_workflow_drift.py"], ["--write"]), "ok"),
    ],
)
def test_named_lanes_on_their_registry_argv_are_accepted(entry, why):
    ok, reason = named_system_lane_ok(entry, REGISTRY.get(entry["lane_id"]))
    assert ok, reason


@pytest.mark.parametrize(
    "entry,why",
    [
        (_entry("approval-escalate", ["$PY", "scripts/incident_notifier.py"], ["--live"]), "not a named"),
        (_entry("no-leads-alert", ["$PY", "scripts/send_no_leads_diagnostic_alert.py"]), "not a named"),
        (_entry("incident-notifier", ["$PY", "scripts/telegram_alert.py"]), "registry row's command"),
        (_entry("incident-notifier", ["$PY", "scripts/incident_notifier.py"], ["--live", "--send_telegram"]), "sender"),
        (_entry("n8n-workflow-drift-check", ["$PY", "scripts/incident_notifier.py"]), "registry row's command"),
    ],
)
def test_other_senders_and_drifted_argv_are_refused(entry, why):
    ok, reason = named_system_lane_ok(entry, REGISTRY.get(entry["lane_id"]))
    assert not ok and why in reason, reason


def test_while_proposed_the_sender_lanes_are_not_in_the_allowlist():
    """The implementation follows the vote: no allowlist entry for the notifier or P16 before ratification,
    and the allowlist's never-list still names only the scalp exception."""
    if not _proposed():
        return
    assert SENDER_LANE not in ALLOW_LANES
    assert "n8n-activation-grants" not in ALLOW_LANES
    assert "Sole exception: trade-ai-scalp-live" in ALLOW["never"]
    assert "every sender" in ALLOW["never"]


# -------------------------------------------------------------------------- §23.16 dead-man switch


def test_23_16_dead_man_switch_is_host_side_and_honest():
    f = _flat(_subsection("23.16"))
    for frag in (
        "does not depend on n8n",
        f"`{WATCHDOG_SERVICE}`",
        f"`{WATCHDOG_TIMER}`",
        "`send_system`",
        "n8n, the relay, the gateway or the incident notifier",
        "configured window",
        "The window is configuration, not a literal in code",
        "the one sanctioned host-timer exception",
        "recommended by Agent A and approved by the operator's ratification of this version",
        "never an n8n execution row",
        "open finding, not a control",
        "`dry_run` only, never `live`",
        "never schedules, restarts or fails over",
    ):
        assert frag in f, frag


def test_the_watchdog_units_exist_and_do_not_depend_on_n8n():
    unit = (ROOT / "config" / "systemd" / "user" / WATCHDOG_SERVICE).read_text(encoding="utf-8")
    assert "scripts/autonomy_watchdog.py" in unit
    assert "n8n" not in unit.lower() and "18091" not in unit and "18092" not in unit


def test_23_16_measurement_matches_the_code():
    """§23.16 says the watchdog reads none of the four today. When a collector starts reading them, this
    test fails and the sentence must be updated in the same PR (§20: a finding that contradicts this file)."""
    collectors = (ROOT / "scripts" / "lib" / "autonomy_watchdog" / "collectors.py").read_text(encoding="utf-8")
    reads_any = any(t in collectors for t in ("n8n", "incident_notifier", "18091", "18092"))
    stated_absent = "Today the watchdog does not read any of the four" in _flat(_subsection("23.16"))
    assert reads_any != stated_absent, "§23.16's measurement no longer matches collectors.py; update the text"


# ------------------------------------------------------------------- §23.17 error-handling baseline


def test_23_17_error_handling_baseline():
    f = _flat(_subsection("23.17"))
    assert "Every n8n workflow sets an error workflow." in f
    assert f"`{ERROR_STANDARD}`" in f
    assert "n8n → relay → host fan-in → incident notifier → Telegram" in f
    assert "**No Telegram in n8n.**" in f
    assert "de-duplication, quiet hours and cap host-side" in f


# --------------------------------------------------------------------------------- shared hygiene


def test_every_new_bullet_cites_its_cause():
    sections = [_subsection(n) for n in HEADINGS]
    for text in sections:
        bullets = re.split(r"^- ", text, flags=re.M)[1:]
        assert bullets, text[:60]
        for b in bullets:
            assert "Cause (§" in _flat(b), f"bullet without a Cause: {_flat(b)[:90]!r}"
    assert "Cause (§20)" in _bullet(_subsection("23.3"), NAMED_EXCEPTION_OPENER)


def test_new_text_carries_no_absolute_home_path():
    home = "/home/" + "johnclaw"
    for n in HEADINGS:
        assert home not in _subsection(n), n
    assert home not in _bullet(_subsection("23.3"), NAMED_EXCEPTION_OPENER)
    assert home not in _row().group(0)


def test_agents_md_keeps_lf_line_endings():
    assert b"\r" not in (ROOT / "AGENTS.md").read_bytes()


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


def test_when_active_the_ratification_is_recorded():
    if _version() == (4, 2, 0) and _control("Status") == "ACTIVE":
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _control("Effective-Date"))
        assert not _proposed()
        assert "4.2.0 is PROPOSED" not in AGENTS
        assert "**4.2.0 PROPOSED**" not in AGENTS
        assert "PROPOSED in 4.2.0" not in AGENTS
