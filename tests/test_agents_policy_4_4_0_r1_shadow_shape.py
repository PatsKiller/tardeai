"""AGENTS.md 4.4.0 — the R1 shadow and canary rows may be cron rows (§23.11, §23.18 (c)); PROPOSED 2026-10-10, ACTIVE 2026-10-10
(ratified `APPROVE_AGENTS_POLICY_4_4_0 1660 463535dfe`; merged #1660 as 40e445d79).

The failure this guards against (Agent A, 2026-10-10): a §23.11 dispatcher row (`kind: n8n`, `expression:
"dispatcher"`) fails CRON_PRESENT_WHILE_SCHEDULER_N8N and the inactive-n8n-row check while its cron line is live, so
the shadow wave was built as cron rows, and 4.3.0 §23.18 (c) refused every ingest / llm / learn lane in that shape.

What this amendment may and may not do, pinned here:

* the code cannot run ahead of the vote: `lane_dispatch.R1_SHADOW_SHAPE_STATUS` equals the 4.4.0 row status;
* §0, §2, §2A, §7A, §17 and §23.14 are byte-identical to the 4.3.0 base (`af292381c`);
* the allowlist `never` list's never-under-any-class sentence is word for word, and the scalp sentence stays;
* §23.11 and §23.18 (c) say exactly what the code admits: the cron row at `shadow` (`dispatch.mode` dry_run, a
  null `live_arg`) and at `canary` (operator ruling 2026-10-10 ~14:00 ET: mode live, `live_arg` set, the allowlist
  flock lock equal to the cron line's lock); cutover keeps the dispatcher row; `tradeai-dispatcher` is refused as
  an expression;
* every new bullet cites its cause, and §23.7 records the replaced sentences.

Works while 4.4.0 is PROPOSED and after the ratification edit (branches on the 4.4.0 row status).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_agents_policy_state as STATE  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
TOKEN = "APPROVE_AGENTS_POLICY_4_4_0"
THIS_FILE = "tests/test_agents_policy_4_4_0_r1_shadow_shape.py"

# Hashes at origin/main af292381c (AGENTS 4.3.0 ACTIVE). §0/§2/§2A/§7A and §23.14 are the digests the 4.1.0 and
# 4.3.0 tests pin; §17 and the never-under-any-class sentence are pinned here.
SECTION_23_14_SHA256 = "bb8722f69b8e54a8582011bdbe266d55ea7c2c0c6b120d123a1d4e43394311e7"
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
    "§17": (
        "# 17 · Operator-only decisions",
        "# 17A ·",
        "f61b30d248331b2ee11e950cc8f455a273608d52d1eba3de6fca191b98e5f2f5",
    ),
}
NEVER_UNDER_ANY_CLASS_SHA256 = "19b3e33c1d6a5945cd6e8d89f29be30eed34dfc7c16eb185d8a1014fd40d1e46"


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
    block = text[s.start() : s.start() + 1 + e.start()]
    block = block.replace(RULE_2_EXCEPTION_5_0_0, "")  # operator-requested amendment 5.0.0; see the constant
    # §7A embeds a GENERATED table (render_source_of_truth.py); mask it so only rule text is pinned.
    # Operator 2026-10-10 ~18:40 ET ("Yes, from one to six", item 5); §20 PATCH.
    return re.sub(r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)", r"\1\n<generated>\n\2", block, flags=re.S)


def _subsection(number: str) -> str:
    sec = re.search(r"^# 23 · .*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert sec, "§23 not found"
    m = re.search(rf"^## {re.escape(number)} .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    assert m, number
    return m.group(0)


def _row() -> re.Match:
    m = re.search(r"^\| 4\.4\.0 \| 2026-10-10 \| (PROPOSED|ACTIVE) \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 4.4.0 | 2026-10-10 | PROPOSED|ACTIVE | MAJOR |` version row"
    return m


# ---------------------------------------------------------------------------------------- header + row


def test_header_is_4_4_0_proposed_or_later():
    assert _version() >= (4, 4, 0)
    if _version() == (4, 4, 0):
        assert _control("Supersedes") == "4.3.0"
        if _control("Status") == "PROPOSED":
            assert _control("Effective-Date") == "PENDING"


def test_version_row_is_major_and_pending_while_proposed():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and TOKEN in rest
        assert 'R1_SHADOW_SHAPE_STATUS = "ACTIVE"' in rest
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 4.4.0 row must record the token, PR and sha"


def test_state_checker_passes_on_branch_and_on_main():
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_code_status_matches_the_policy_row():
    assert LD.R1_SHADOW_SHAPE_POLICY_VERSION == "4.4.0"
    assert LD.R1_SHADOW_SHAPE_STATUS == _row().group(1)
    assert LD.R1_STATUS == "ACTIVE"  # 4.3.0 stays ratified; this amendment does not reopen it


def test_banner_names_the_proposal_and_what_governs_meanwhile():
    if _row().group(1) == "PROPOSED":
        f = _flat(AGENTS[: AGENTS.index("**4.0.0 is ACTIVE")])
        assert "4.4.0 is PROPOSED (MAJOR)" in f and "the 4.3.0 text governs" in f and TOKEN in f


# ------------------------------------------------------------------------- what must not move


def test_23_14_is_byte_identical():
    block = _subsection("23.14").rstrip("\n").rstrip("-").rstrip("\n")
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == SECTION_23_14_SHA256, "§23.14 changed"


def test_rail_and_operator_only_sections_are_byte_identical():
    for name, (start, end, digest) in PINNED_SECTIONS.items():
        block = _section(AGENTS, start, end)
        assert hashlib.sha256(block.encode("utf-8")).hexdigest() == digest, f"{name} changed"


def test_never_list_never_under_any_class_sentence_is_word_for_word():
    never = ALLOW["never"]
    head = never.split(" Memory/learning writers")[0]
    assert hashlib.sha256(head.encode("utf-8")).hexdigest() == NEVER_UNDER_ANY_CLASS_SHA256
    assert "Sole exception: trade-ai-scalp-live" in never
    f = _flat(never)
    for frag in (
        "4.4.0",
        "shadow/canary/cutover",
        "dispatch.mode dry_run",
        "null live_arg",
        "at stage canary with dispatch.mode live",
        "flock lock equal to the cron line's lock",
        "R1_SHADOW_SHAPE_STATUS",
    ):
        assert frag in f, frag


# ------------------------------------------------------------------------------ the new text


def test_23_11_names_the_cron_shadow_row_and_the_dispatcher_name():
    f = _flat(_subsection("23.11"))
    for frag in (
        "While its cron line is live, a lane in `shadow` or `canary` may stay a cron row (4.4.0).",
        '`scheduler.kind = "cron"`',
        '`scheduler.stage = "shadow"`',
        "mode `dry_run`",
        "it is a dispatcher row",
        "Cutover keeps the dispatcher row above.",
        "a `dispatch` block in mode `live`",
        "which must be the allowlist entry's lock",
        '`scheduler.expression = "dispatcher"` names that row',
        "`tradeai-dispatcher` is the dispatcher's n8n workflow id",
        "`_cutover.py --workflow-id`",
        "CRON_PRESENT_WHILE_SCHEDULER_N8N",
    ):
        assert frag in f, frag


def test_23_18_c_admits_the_cron_row_at_shadow_and_canary_only():
    f = _flat(_subsection("23.18"))
    assert "At `shadow` or `canary` only, it may instead be the §23.11 cron row" in f
    assert 'At `shadow` it has `dispatch.mode = "dry_run"` and an allowlist `live_arg` of null' in f
    assert "an allowlist lock equal to every `flock` lock in `scheduler.command_text`" in f
    assert "`R1_SHADOW_SHAPE_STATUS` is `ACTIVE`" in f
    assert "never the workflow id `tradeai-dispatcher`" in f
    assert "adds classes. It does not widen broker reach." in f  # 4.3.0 framing kept


def test_every_bullet_in_the_touched_subsections_cites_its_cause():
    for number in ("23.11", "23.18"):
        for b in re.split(r"^- ", _subsection(number), flags=re.M)[1:]:
            assert "Cause (§" in _flat(b), f"§{number} bullet without a Cause: {_flat(b)[:90]!r}"


def test_23_7_records_the_replaced_sentences():
    f = _flat(_subsection("23.7"))
    assert "4.4.0 (PROPOSED; the 4.3.0 text stays readable at `origin/main` `af292381c`)" in f or ("4.4.0 (ACTIVE" in f)
    assert '§23.18 (c) read: "`scheduler.expression = "dispatcher"` and `scheduler.stage` is `shadow`,' in f


def test_new_text_carries_no_absolute_home_path():
    home = "/home/" + "johnclaw"
    for number in ("23.11", "23.18", "23.7"):
        assert home not in _subsection(number)
    assert home not in _row().group(0)
    assert THIS_FILE in _row().group(0)


def test_agents_md_keeps_lf_line_endings():
    assert b"\r\n" not in (ROOT / "AGENTS.md").read_bytes()


def test_when_active_the_ratification_is_recorded():
    """Ratified 2026-10-10 by PR #1660 comment (PatsKiller, 2026-10-10T20:04:37Z) "APPROVE_AGENTS_POLICY_4_4_0 1660
    463535dfe"; merged as 40e445d79. An ACTIVE 4.4.0 carries a real date, the operator line, the merge sha, the §23
    heading and status line, and the code gate open on 4.4.0 terms."""
    if _version() == (4, 4, 0) and _control("Status") == "ACTIVE":
        assert _control("Effective-Date") == "2026-10-10"
        rest = _row().group(2)
        assert f"{TOKEN} 1660 463535dfe" in rest and "40e445d790c4b8294c3f2e3fb64cbb9f1658e9d9" in rest
        assert "2026-10-10T20:04:37Z" in rest
        assert LD.R1_SHADOW_SHAPE_STATUS == "ACTIVE"
        banner = _flat(AGENTS[: AGENTS.index("**4.0.0 is ACTIVE")])
        assert "4.4.0 is ACTIVE (MAJOR)" in banner and f"{TOKEN} 1660 463535dfe" in banner
        assert "4.4.0 is PROPOSED" not in AGENTS
        assert re.search(r"^# 23 · .*— ACTIVE 4\.4\.0$", AGENTS, re.M)
        assert f"**4.4.0 ACTIVE (ratified 2026-10-10,** `{TOKEN} 1660 463535dfe`**)**" in _flat(AGENTS)
        assert "4.4.0 (ACTIVE 2026-10-10; the 4.3.0 text stays readable" in _flat(_subsection("23.7"))
