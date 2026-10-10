"""AGENTS.md 4.3.0 — R1: `ingest`, `llm` and `learn` become dispatcher classes (§23.18); PROPOSED 2026-10-10, ACTIVE 2026-10-10
(ratified `APPROVE_AGENTS_POLICY_4_3_0 1642 64c9210e1`; merged #1642 as 203b46914).

Operator rulings for all waves, 2026-10-10 ~00:20 ET: (1) ingest writers, governed LLM jobs and learning/memory
writers are dispatcher-eligible, always shadow -> canary -> cutover; governed DeepSeek route approved for L401
(overnight trade reviewer); (2) whole-word / path-segment token matching (separate PR); (3) no broker credentials
in lanes, entry planner via the data broker (separate PR); (4) alert_events rows are not a send, backtest fields on
paper_trade_proposals are not paper execution, L504 symbol_profiles and L205 market_regime writers approved.

The failures this guards against:

* the amendment widening broker reach: §23.14 must stay byte-identical, and broker / order / stop / positions /
  secret / daemon lanes must still be refused even when they declare an admitted class with every other condition
  met;
* a class admission that skips the ladder: an R1 class is admitted only for a dispatcher row at stage
  shadow/canary/cutover, with a dry-run arg and a LaneRunReceipt@v1 output_signal matching the allowlist;
* the code admitting before the vote: `lane_dispatch.R1_STATUS` must equal the 4.3.0 row status;
* an LLM job choosing its own provider: `llm` needs llm_route via cio-governed-bridge with a registered process; L401
  only on its overnight (DeepSeek) tier, and only once its code actually uses the bridge;
* `send` sneaking in with the three classes (R2 is not ratified);
* §0, §2, §2A or §7A changing under cover of an n8n amendment (sha256 pinned, same digests as 4.1.0).

Works while 4.3.0 is PROPOSED and after the ratification edit (branches on the 4.3.0 row status).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_agents_policy_state as STATE  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
ALLOW_LANES = {e["lane_id"]: e for e in ALLOW["lanes"]}
REGISTRY_DOC = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
REGISTRY = {r["lane_id"]: r for r in REGISTRY_DOC["lanes"]}
THIS_FILE = "tests/test_agents_policy_4_3_0_r1_classes.py"
TOKEN = "APPROVE_AGENTS_POLICY_4_3_0"
HEADING = "## 23.18 R1 — ingest, governed-LLM and learning classes on the dispatcher (4.3.0)"
REVIEWER = ROOT / "scripts" / "multi_tier_trade_reviewer.py"

# §23.14 is the sentence set no amendment inside the program window may change (§23.14 last bullet). Hash of the
# subsection at origin/main 6b88751bd (AGENTS 4.1.0 ACTIVE), trailing newlines stripped.
SECTION_23_14_SHA256 = "bb8722f69b8e54a8582011bdbe266d55ea7c2c0c6b120d123a1d4e43394311e7"
# Same digests tests/test_agents_policy_4_1_0_amendment.py pins.
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


def _subsection(number: str) -> str:
    sec = re.search(r"^# 23 · .*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert sec, "§23 not found"
    m = re.search(rf"^## {re.escape(number)} .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    assert m, number
    return m.group(0)


def _row() -> re.Match:
    m = re.search(r"^\| 4\.3\.0 \| 2026-10-10 \| (PROPOSED|ACTIVE) \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 4.3.0 | 2026-10-10 | PROPOSED|ACTIVE | MAJOR |` version row"
    return m


def _proposed() -> bool:
    return _row().group(1) == "PROPOSED"


RECEIPT = "data/runtime/r1-lane_last.json"


def _row_and_entry(klass: str, command: list[str], *, lane: str = "r1-lane", stage: str = "canary",
                   dry=("--dry-run",), live=(), env=(), receipt: str = RECEIPT, **entry_extra):
    row = {
        "lane_id": lane,
        "scheduler": {"kind": "n8n", "expression": "dispatcher", "cadence": "30 2 * * *",
                      "match": f"flock -n /tmp/{lane}.lock $PY {' '.join(command[1:])}", "wave": "W2", "stage": stage},
        "output_signal": {"kind": "json_key", "path": receipt, "key": "ok_at"},
        "dispatch": {"mode": "dry_run", "cron": ["30 2 * * *"], "wave": "W2", "class": klass, "priority": 5,
                     "retry_policy": "transient-2"},
    }
    entry = {"lane_id": lane, "command": list(command), "lock": f"/tmp/{lane}.lock", "lock_kind": "flock",
             "timeout_s": 600, "dry_run_arg": list(dry) if dry is not None else None, "live_arg": list(live),
             "market_gate": False, "output_signal": receipt, "env_names": list(env), **entry_extra}
    argv = {lane: " ".join([*entry["command"], *(entry["dry_run_arg"] or []), *entry["live_arg"]])}
    return row, entry, argv


def _admit(row, entry, argv, *, status="ACTIVE", process_ids=None):
    return LD.r1_class_admission(row, entry, status=status, allowlist_argv=argv, exceptions={},
                                 process_ids=process_ids if process_ids is not None else {"multi_tier_trade_reviewer"})


BRIDGE = {"via": "cio-governed-bridge", "process_id": "multi_tier_trade_reviewer"}
L401_ARGV = ["$PY", "scripts/multi_tier_trade_reviewer.py", "--tier", "overnight"]


# ---------------------------------------------------------------------------------------- header + row


def test_header_is_4_3_0_proposed_or_later():
    assert _version() >= (4, 3, 0)
    if _version() == (4, 3, 0) and _control("Status") == "PROPOSED":
        assert _control("Effective-Date") == "PENDING"


def test_version_row_is_major_and_pending_while_proposed():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and TOKEN in rest
        assert "2026-10-10 ~00:20 ET" in rest
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 4.3.0 row must record the token, PR and sha"


def test_state_checker_passes_on_branch_and_on_main():
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_code_status_matches_the_policy_row():
    """The class gate cannot run ahead of the vote: R1_STATUS flips only with the ratifying edit."""
    assert LD.R1_POLICY_VERSION == "4.3.0"
    assert LD.R1_STATUS == _row().group(1)
    if _proposed():
        assert LD.permitted_classes_now() == LD.PERMITTED_CLASSES_PRE_R1
        assert "4.3.0 is PROPOSED" in AGENTS


def test_numbered_after_4_2_0_without_taking_its_subsections():
    """4.2.0 (PR #1634) is PROPOSED with §23.15–§23.17; this amendment must not claim those numbers."""
    for n in ("23.15", "23.16", "23.17"):
        for m in re.finditer(rf"^## {re.escape(n)} (.*)$", AGENTS, re.M):
            assert "4.3.0" not in m.group(1), m.group(0)
    assert re.search(rf"^{re.escape(HEADING)}$", AGENTS, re.M)
    assert "#1634" in _subsection("23.18")


# ------------------------------------------------------------------------------- §23.14 is untouched


def test_23_14_is_byte_identical_to_the_4_1_0_text():
    block = _subsection("23.14").rstrip("\n").rstrip("-").rstrip("\n")
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == SECTION_23_14_SHA256, "§23.14 changed"


@pytest.mark.parametrize("name", list(PINNED_SECTIONS))
def test_rail_sections_are_byte_identical_to_the_base(name):
    start, end, digest = PINNED_SECTIONS[name]
    block = _section(AGENTS, start, end)
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == digest, f"{name} changed"


# ------------------------------------------------------------------------------------------- §23.18 text


def test_23_18_states_the_rulings_and_names_its_mechanism():
    f = _flat(_subsection("23.18"))
    for frag in (
        "2026-10-10 ~00:20 ET",
        "adds classes. It does not widen broker reach.",
        "`ingest`",
        "`llm`",
        "`learn`",
        "shadow → canary → cutover",
        "r1_class_admission",
        "R1_STATUS",
        "dry_run_arg",
        "LaneRunReceipt@v1",
        "cio-governed-bridge",
        "L401",
        "--tier overnight",
        "L473/L474",
        "alert_events",
        "paper_trade_proposals",
        "L504",
        "L205",
        "whole-word / path-segment",
        THIS_FILE,
    ):
        assert frag in f, frag
    assert "`send` stays refused (R2)" in f


def test_23_18_records_the_measured_l401_gap():
    f = _flat(_subsection("23.18"))
    assert "llm_lane.generate" in f and "gate_and_generate" in f and "not the `cio-governed-bridge` process" in f


def test_every_new_bullet_cites_its_cause():
    bullets = re.split(r"^- ", _subsection("23.18"), flags=re.M)[1:]
    assert len(bullets) >= 6
    for b in bullets:
        assert "Cause (§" in _flat(b), f"§23.18 bullet without a Cause: {_flat(b)[:90]!r}"


def test_new_text_carries_no_absolute_home_path():
    home = "/home/" + "johnclaw"
    assert home not in _subsection("23.18")
    assert home not in _row().group(0)


def test_agents_md_keeps_lf_line_endings():
    assert b"\r\n" not in (ROOT / "AGENTS.md").read_bytes()


# ------------------------------------------------------------------------------------ allowlist `never`


def test_never_list_still_names_every_broker_sender_and_secret_entry():
    never = ALLOW["never"]
    for frag in ("broker/positions/stops/orders/paper lanes", "every sender", "sm-render", "guard", "release deploy",
                 "destructive retention", "CIO/persona/OpenClaw agent loops", "under any class",
                 "Sole exception: trade-ai-scalp-live"):
        assert frag in never, frag


def test_never_list_admits_the_three_classes_only_on_r1_terms():
    never = _flat(ALLOW["never"])
    for frag in ("4.3.0 §23.18", "`learn`, `ingest` and `llm`", "ACTIVE", "R1_STATUS", "shadow/canary/cutover",
                 "dry_run_arg", "LaneRunReceipt@v1", "cio-governed-bridge", "broker credential"):
        assert frag in never, frag
    assert "send" not in re.findall(r"`(\w+)`", never), "`send` is not an R1 class"


# ------------------------------------------------------- broker / order / stop / secret / daemon refused


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
@pytest.mark.parametrize(
    ("command", "live", "why"),
    [
        (["$PY", "scripts/schwab_place_order.py"], (), "forbidden_token"),
        (["$PY", "scripts/submit_orders.py"], (), "forbidden_token"),
        (["$PY", "scripts/unified_stop_supervisor.py"], (), "forbidden_token"),
        (["$PY", "scripts/schwab_position_sync.py"], (), "forbidden_token"),
        (["$PY", "scripts/alpaca_paper_executor.py"], (), "forbidden_token"),
        (["$PY", "scripts/render_env.py"], ("--write",), "forbidden_token"),
        (["bash", "scripts/sm-render.sh"], (), "forbidden_token"),
        (["$PY", "scripts/bin_guard_grant.py"], (), "forbidden_token"),
        (["$PY", "scripts/send_telegram_proposal_alert.py"], (), "forbidden_token"),
        (["$PY", "scripts/foo_ingest.py"], ("--daemon",), "daemon_flag"),
        (["$PY", "scripts/foo_ingest.py", "--loop"], (), "daemon_flag"),
        (["$PY", "scripts/foo_ingest.py"], ("--watch=30",), "daemon_flag"),
    ],
)
def test_broker_order_stop_secret_daemon_refused_under_every_r1_class(klass, command, live, why):
    """Even with R1 ACTIVE and every other condition met, an admitted class never reaches these lanes."""
    row, entry, argv = _row_and_entry(klass, command, live=live)
    if klass == "llm":
        entry["llm_route"] = dict(BRIDGE)
    ok, reason = _admit(row, entry, argv)
    assert not ok, (klass, command, reason)
    assert why in reason, reason


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
def test_a_systemd_service_lane_is_refused(klass):
    row, entry, argv = _row_and_entry(klass, ["$PY", "scripts/foo_ingest.py"])
    row["scheduler"]["match"] = "tradeai-foo.service"
    if klass == "llm":
        entry["llm_route"] = dict(BRIDGE)
    ok, reason = _admit(row, entry, argv)
    assert not ok and "systemd_service_lane" in reason, reason


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
def test_broker_credentials_in_the_lane_env_are_refused(klass):
    row, entry, argv = _row_and_entry(klass, ["$PY", "scripts/watchlist_entry_planner.py"],
                                      env=("DB_HOST", "SCHWAB_APP_KEY"))
    if klass == "llm":
        entry["llm_route"] = dict(BRIDGE)
    ok, reason = _admit(row, entry, argv)
    assert not ok and "broker_credential_env:SCHWAB_APP_KEY" in reason, reason


# ------------------------------------------------------ the three classes: only with dry-run + receipt


def _good(klass: str):
    cmd = {"ingest": ["$PY", "scripts/market_regime_classifier.py"],
           "learn": ["$PY", "scripts/agent_calibration_engine.py"],
           "llm": L401_ARGV}[klass]
    row, entry, argv = _row_and_entry(klass, cmd, live=("--apply",) if klass != "llm" else ())
    if klass == "llm":
        entry["llm_route"] = dict(BRIDGE)
    return row, entry, argv


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
@pytest.mark.parametrize("stage", sorted(LD.R1_STAGES))
def test_admitted_at_every_ladder_stage_when_active_and_complete(klass, stage):
    row, entry, argv = _good(klass)
    row["scheduler"]["stage"] = stage
    assert _admit(row, entry, argv) == (True, f"r1_admitted:{klass}")


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
def test_refused_while_r1_is_not_ratified(klass):
    row, entry, argv = _good(klass)
    ok, reason = _admit(row, entry, argv, status="PROPOSED")
    assert not ok and reason.startswith("r1_not_ratified"), reason


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
@pytest.mark.parametrize(
    ("mutate", "why"),
    [
        (lambda r, e: e.update(dry_run_arg=None), "no_dry_run_arg"),
        (lambda r, e: e.update(dry_run_arg=[]), "no_dry_run_arg"),
        (lambda r, e: r.update(output_signal={"kind": "file_mtime", "path": "logs/regime_classifier.log"}),
         "output_signal_not_a_lane_receipt"),
        (lambda r, e: r.update(output_signal={"kind": "json_key", "path": RECEIPT, "key": "as_of"}),
         "output_signal_not_a_lane_receipt"),
        (lambda r, e: e.update(output_signal="data/runtime/other_last.json"), "allowlist_output_signal_mismatch"),
        (lambda r, e: r["scheduler"].update(stage=None), "stage"),
        (lambda r, e: r["scheduler"].update(stage="proposed"), "stage"),
        (lambda r, e: r["scheduler"].update(expression="0 2 * * *"), "not_a_dispatcher_row"),
        (lambda r, e: r.update(stay_on_cron={"class": "operator", "reason": "x"}), "stay_on_cron"),
    ],
)
def test_refused_without_ladder_stage_dry_run_or_receipt(klass, mutate, why):
    row, entry, argv = _good(klass)
    mutate(row, entry)
    ok, reason = _admit(row, entry, argv)
    assert not ok and why in reason, reason


def test_refused_with_no_allowlist_entry():
    row, _entry, argv = _good("ingest")
    row["lane_id"] = "r1-unlisted-lane-xyz"
    ok, reason = LD.r1_class_admission(row, None, status="ACTIVE", allowlist_argv={}, exceptions={})
    assert not ok and reason == "not_allowlisted", reason


def test_send_stays_refused_even_when_r1_is_active():
    row, entry, argv = _row_and_entry("send", ["$PY", "scripts/report_digest.py"])
    ok, reason = _admit(row, entry, argv)
    assert not ok and reason == "class_gated:send", reason
    assert "send" not in LD.PERMITTED_CLASSES_R1
    assert LD.R1_ADMITTED_CLASSES == {"ingest", "llm", "learn"}


def test_pre_r1_classes_are_unchanged():
    assert LD.PERMITTED_CLASSES_PRE_R1 == {"monitor", "report", "hygiene", "pipeline", "heavy"}
    row, entry, argv = _row_and_entry("report", ["$PY", "scripts/storage_watch.py"])
    assert _admit(row, entry, argv, status="PROPOSED") == (True, "pre_r1_class")


def test_validate_dispatch_block_never_waives_r1_for_a_wider_class_set():
    row, _entry, _argv = _good("ingest")
    issues = LD.validate_dispatch_block(row, permitted_classes=LD.DISPATCH_CLASSES)
    if LD.R1_STATUS != "ACTIVE":
        assert [i.code for i in issues] == ["class_not_permitted"] and "r1_not_ratified" in issues[0].detail


# --------------------------------------------------------------- llm: the governed bridge, nothing else


@pytest.mark.parametrize(
    ("route", "why"),
    [
        (None, "llm_route_not_governed_bridge"),
        ({"via": "llm_lane", "process_id": "multi_tier_trade_reviewer"}, "llm_route_not_governed_bridge"),
        ({"via": "deepseek", "process_id": "multi_tier_trade_reviewer"}, "llm_route_not_governed_bridge"),
        ({"via": "cio-governed-bridge", "process_id": "not_a_registered_process"}, "llm_process_unregistered"),
        ({"via": "cio-governed-bridge"}, "llm_process_unregistered"),
    ],
)
def test_llm_needs_the_governed_bridge_and_a_registered_process(route, why):
    row, entry, argv = _good("llm")
    if route is None:
        entry.pop("llm_route")
    else:
        entry["llm_route"] = route
    ok, reason = _admit(row, entry, argv)
    assert not ok and why in reason, reason


@pytest.mark.parametrize("extra", [["--model", "deepseek-v4-pro"], ["--provider", "anthropic"], ["--lane", "openai"]])
def test_llm_argv_may_not_pick_a_provider_or_model(extra):
    row, entry, argv = _good("llm")
    entry["command"] = [*L401_ARGV, *extra]
    ok, reason = _admit(row, entry, argv)
    assert not ok and "llm_argv_selects_provider" in reason, reason


def test_l401_overnight_is_admitted_through_the_bridge_and_its_process_is_registered():
    row, entry, argv = _good("llm")
    assert _admit(row, entry, argv, process_ids=LD.load_llm_process_ids()) == (True, "r1_admitted:llm")


def _tier_providers() -> dict[str, str]:
    src = REVIEWER.read_text(encoding="utf-8")
    body = src[src.index("TIER_CONFIG = {") : src.index("\n}\n", src.index("TIER_CONFIG = {"))]
    return dict(re.findall(r'^    "(\w+)": \{.*?"provider": "([\w-]+)"', body, re.M | re.S))


def test_l401_only_the_overnight_deepseek_tier_is_the_approved_route():
    tiers = _tier_providers()
    assert tiers.get("overnight") == "deepseek-flash", tiers
    assert {tiers.get("weekly"), tiers.get("monthly")} <= {"openai", "anthropic"}, tiers


def test_measured_l401_gap_matches_the_code():
    """§23.18 says the overnight tier calls llm_lane in-process, not the bridge. If the code changes, this fails so
    §23.18 is updated in the same PR (and only then may L401 declare llm_route via the bridge)."""
    src = REVIEWER.read_text(encoding="utf-8")
    fn = src[src.index("def _generate_deepseek") : src.index("def _generate_openai")]
    assert "from llm_lane import generate" in fn and 'process_id="multi_tier_trade_reviewer"' in fn


def test_real_allowlist_l401_entry_if_any_is_overnight_bridge_only():
    for lane, entry in ALLOW_LANES.items():
        argv = [*entry.get("command", []), *(entry.get("dry_run_arg") or []), *(entry.get("live_arg") or [])]
        if not any("multi_tier_trade_reviewer" in str(t) for t in argv):
            continue
        assert entry.get("llm_route") == BRIDGE, lane
        assert entry["command"][-2:] == ["--tier", "overnight"], lane
        src = REVIEWER.read_text(encoding="utf-8")
        assert "from llm_lane import generate" not in src[src.index("def _generate_deepseek") :
                                                           src.index("def _generate_openai")], (
            f"{lane}: allowlisted as bridge-routed while the reviewer still calls llm_lane in-process")


# ------------------------------------------------------------------------------ the real registry state


def test_real_registry_has_no_dispatch_issue():
    assert LD.registry_dispatch_errors(REGISTRY_DOC) == []


def test_while_proposed_no_registry_row_carries_an_r1_class():
    if not _proposed():
        pytest.skip("4.3.0 ACTIVE: r1_class_admission governs real rows (checked below)")
    for lane, row in REGISTRY.items():
        klass = (row.get("dispatch") or {}).get("class")
        assert klass not in LD.R1_ADMITTED_CLASSES, f"{lane}: class {klass} before APPROVE_AGENTS_POLICY_4_3_0"


def test_every_real_r1_row_passes_the_gate():
    for lane, row in REGISTRY.items():
        if (row.get("dispatch") or {}).get("class") in LD.R1_ADMITTED_CLASSES:
            ok, reason = LD.r1_class_admission(copy.deepcopy(row))
            assert ok, f"{lane}: {reason}"


def test_when_active_the_ratification_is_recorded():
    """Ratified 2026-10-10 with APPROVE_AGENTS_POLICY_4_3_0 1642 64c9210e1, re-approved ("approved") for head
    c3d5e895d after the #1643 conflict merge: an ACTIVE 4.3.0 carries a real date, both operator words, the merge
    sha, and the code gate is open on R1 terms."""
    if _version() == (4, 3, 0) and _control("Status") == "ACTIVE":
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _control("Effective-Date"))
        assert not _proposed()
        rest = _row().group(2)
        assert f"{TOKEN} 1642 64c9210e1" in rest
        assert '"approved"' in rest and "c3d5e895d4de5eb16f43f90ce8f43dc61a0cadfc" in rest
        assert "203b469146154c6729620a2428fcb76740a4d0a8" in rest
        assert "4.3.0 is PROPOSED" not in AGENTS
        assert "4.3.0 PROPOSED" not in AGENTS
        assert "4.3.0 (PROPOSED" not in AGENTS
        assert LD.R1_STATUS == "ACTIVE"
        assert LD.permitted_classes_now() == LD.PERMITTED_CLASSES_R1
