"""AGENTS.md 19.0.0 (PROPOSED, MAJOR) — §27 n8n broker reads and the operator controls surface.

Shipped as an OPERATOR-COMMITTED package (operator, 2026-10-22: "yes" — the rule changes are a diff the operator
applies and commits; agents do not edit AGENTS.md, the pinning tests, guard surfaces or broker-access code). Built on
the 18.0.0-ACTIVE AGENTS.md (`2d8fc9574`, PR #1931).

Operator decisions 2026-10-22 (verbatim): "N8N can read the broker because right now we're only doing reading of the
broker. We're not doing any trading. So I want to amendment." and "yes on passkey".

What this pins:
  * one 19.0.0 history row, PROPOSED with PENDING and the §20 phrase until ratified; while PROPOSED the header block
    reads 19.0.0 PROPOSED, `Effective-Date` PENDING, `Supersedes` 18.0.0; the state checker passes;
  * the banner states the class and why, the scope, the byte-identical list and the phrase;
  * §27 states every rule of the operator's decisions, and every §27 bullet cites its cause;
  * §0, §2, §2A, §7A, §22, §24 and §26 are byte-identical to 18.0.0 (`2d8fc9574`), and so are the four adapters;
  * §17, §23.14 and §25 are byte-identical while PROPOSED; once ratified they differ by exactly the four clause edits
    §27.5 quotes, whose sha256 are pinned here;
  * `CARVEOUT_STATUS` in scripts/lib/n8n_broker_read_carveout.py is ACTIVE exactly when the 19.0.0 row is ACTIVE;
  * the code and the registry row §27 names exist.

Read-only: reads repository files. TRADE_AI_CI=1.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_agents_policy_state as STATE  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_19_0_0"
ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")


def h(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


# Measured on 2d8fc9574 (18.0.0 ACTIVE); identical with the 19.0.0 patch applied and after ratification.
RAILS = {
    "§0": ("# 0 · If you read nothing else", "# 1 · Identity and responsibilities",
           "d10461625959d3de2f520419dbb67c1763e46d6b5905784b6aa185795ac10549"),
    "§2": ("# 2 · Authority rails", "# 2A ·", "5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af"),
    "§2A": ("# 2A ·", "# 2B ·", "38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb"),
    "§7A": ("# 7A ·", "# 8 ·", "6d20888d1329397351c75a54a4c3e2e7978d5974cef6c3c306dc708580b5ca90"),
    "§22": ("# 22 · ", "# 23 · ", "81f1646a64e38047882c7375ab18739111ba8349471fbaa0351fc1069f9717e9"),
    "§24": ("# 24 · ", "# 25 · ", "766e69e45faf210f1ca268616bd34fbcf3f8d69d4a156f6205c6de1280806745"),
}
SECTION_26_SHA256 = "80b1d81d7198c5cca2c78a3beb86e22516ca1252bfc9c56e6013063d4eccf511"
# Measured on 2d8fc9574; unchanged while PROPOSED; after ratification equal once the clause edits are undone.
SECTION_17_SHA256 = "2d9adf898494ee81e620be49f89a8cfde717737f87069462eb41893229ee3473"
SECTION_23_14_SHA256 = "891c55a5be08630952c61300f95bcb5442f1ef6b37fb5cb5018e72f843a9043f"
SECTION_25_SHA256 = "8a01162d312671a4ec52d133f8d9e8906eacddc9b0c8704bc0b48d731462977b"
# Post-ratification digests, pinned in advance (the clause edits carry no PR, SHA or date, so they are fixed now).
SECTION_17_RATIFIED_SHA256 = "59985a21b19925f864133f3e709271f450ebac79884b1f835108a93d89c82df8"
SECTION_23_14_RATIFIED_SHA256 = "34dffc36508f81b726245d2a6fee991db6ec04fc7c18be687d4c2c91559e2eea"
SECTION_25_RATIFIED_SHA256 = "d8122a733dfd6ab45398b8e57d9c871b083ffc8a369d3b01da3aa5ac996f7844"

# The four clause edits of the ratifying edit, byte for byte as build_ratify19.py makes them and §27.5 quotes them.
C1_ANCHOR = (
    '  a secret or start a second copy of a long-running process.*\n'
)
C1_INS = (
    '- **One exception (19.0.0, §27.1): the audited read-only broker lanes.** n8n may schedule and trigger the closed\n'
    '  set of read lanes in `scripts/lib/n8n_broker_read_carveout.py` `READ_LANES` — the §24.11 steps, and market-data\n'
    '  reads that pass the same audit — each run on the host through the allowlisted executor, only while every broker\n'
    '  trading lock is LOCKED and the Schwab access mode is `read_only`; n8n holds no credential. Orders, stop writes,\n'
    '  cancel, replace, preflight, 2FA, `place_order`, live and paper flags, paper execution and senders stay on this\n'
    '  never-list, and changing any read lane into one that writes is §17. *Cause (§20): operator 2026-10-22,\n'
    '  verbatim: "N8N can read the broker because right now we\'re only doing reading of the broker. We\'re not doing\n'
    '  any trading. So I want to amendment."*\n'
)
C2_OLD = (
    '- **Who may do what.** The Command Center and agents may only request STOP or pause (typed command, server-derived\n'
    '  actor, CSRF and origin checks, idempotency key, expected control version, durable audit). Resume, arming,\n'
    '  re-arming, scope changes and revoke are operator acts at the host CLI or by a Telegram button confirmation (D3);\n'
    '  never through report-only middleware or an unimplemented step-up. The host CLI works when the Command Center and\n'
    '  n8n are down. *Cause (§20): decision D3 2026-10-21 (TOTP declined); enhanced design §7.*\n'
)
C2_NEW = (
    '- **Who may do what.** Agents may only request STOP or pause (typed command, server-derived actor, CSRF and origin\n'
    '  checks, idempotency key, expected control version, durable audit). On Ops → Controls, STOP and pause are one\n'
    '  click; resume, arming, re-arming, scope changes and revoke are operator acts made with a WebAuthn passkey and a\n'
    '  typed confirmation phrase (§27.3), or at the host CLI, which works when the Command Center and n8n are down. A\n'
    '  Telegram button confirms nothing; never through report-only middleware or an unimplemented step-up.\n'
    '  *Cause (§20): operator decisions 2026-10-22 (§27.3), superseding decision D3 2026-10-21; enhanced design §7.*\n'
)
C3_OLD = (
    'Each is done\n'
    'by the operator at the host CLI (`scripts/release_control_cli.py`) or by a Telegram button confirmation\n'
    '(decision D3, 2026-10-21); an agent or the Command Center may only request STOP or pause.\n'
)
C3_NEW = (
    'Each is done\n'
    'by the operator on Ops → Controls with a WebAuthn passkey and a typed confirmation phrase (§27.3), or at\n'
    'the host CLI (`scripts/release_control_cli.py`), the fallback; an agent may only request STOP or pause.\n'
)
C4_INS = (
    '\n'
    '**Operator controls (19.0.0, §27):** clearing the trading kill switch · resuming broker jobs · changing the n8n\n'
    'relay live list · issuing a grant from Ops → Controls · registering or revoking a passkey · changing an n8n\n'
    "broker read lane into one that writes, or widening any read lane's reach (§27.1). A risky act is made by the\n"
    'operator on Ops → Controls with a passkey and a typed phrase, or at the host terminal; no agent ever calls a\n'
    'Controls endpoint or the host applier.\n'
)
CLAUSE_SHA256 = {
    "C1_INS": "8bca904a54a00133b7d2f0118ad3bdd6b9cf00e18a2597cc758c067fee5e6c8f",
    "C2_OLD": "e3d5a0533020c634178013df63ef72db71fab94c5797199e904f66bd2b0ca044",
    "C2_NEW": "713ec6210101f71c91c855f2aa34a006258577f55bd220225e4fc5e690656080",
    "C3_OLD": "28e5147533b35e9a28504cedc705110a43ae331c57c03bbfb91f2506f316c3a7",
    "C3_NEW": "561b803458bebb5e992ffa149c702b2f8b54ff34cf4af6de63fee20f0d8be83b",
    "C4_INS": "f152a0cd707d78388d4744b271bdf0181ec35061d2b0a5ee0f5cbbbb5b3c3bb9",
}
CLAUSES = {"C1_INS": C1_INS, "C2_OLD": C2_OLD, "C2_NEW": C2_NEW, "C3_OLD": C3_OLD, "C3_NEW": C3_NEW,
           "C4_INS": C4_INS}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _section(text: str, start: str, end: str) -> str:
    s = re.search(rf"^{re.escape(start)}", text, re.M)
    assert s, start
    e = re.search(rf"^{re.escape(end)}", text[s.start() + 1:], re.M)
    assert e, end
    block = text[s.start(): s.start() + 1 + e.start()]
    return re.sub(r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)",
                  r"\1\n<generated>\n\2", block, flags=re.S)


def _sub(text: str, num: str) -> str:
    m = re.search(rf"^## {re.escape(num)} .*?(?=^## |^---$|^# |\Z)", text, re.M | re.S)
    assert m, f"§{num} missing"
    return m.group(0).rstrip("\n").rstrip("-").rstrip("\n")


def _row() -> re.Match:
    m = re.search(r"^\| 19\.0\.0 \| 2026-10-22 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 19.0.0 | 2026-10-22 | PROPOSED|ACTIVE | MAJOR |` row: the 19.0.0 patch is not applied"
    return m


def _ratified() -> bool:
    return _row().group(1) == "ACTIVE"


def _s27() -> str:
    m = re.search(r"^# 27 · n8n broker reads.*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert m, "§27 missing: the 19.0.0 patch is not applied"
    return m.group(0)


def _s17(text: str) -> str:
    return _section(text, "# 17 · Operator-only decisions", "# 17A ·")


def _s23_14(text: str) -> str:
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", text, re.M | re.S)
    assert sec
    return _sub(sec.group(0), "23.14")


def _s25(text: str) -> str:
    return _section(text, "# 25 · ", "# 26 · ")


def undo_19_0_0(text: str) -> str:
    """The text with the four 19.0.0 ratifying clause edits reversed (each must be present exactly once)."""
    for new, old in ((C1_ANCHOR + C1_INS, C1_ANCHOR), (C2_NEW, C2_OLD), (C3_NEW + C4_INS, C3_OLD)):
        assert text.count(new) == 1, new[:80]
        text = text.replace(new, old, 1)
    return text


def pre_19_0_0(text: str) -> str:
    """For the older policy tests' §17 / §23.14 / §25 pins: the AGENTS.md text as it was before the 19.0.0 ratifying
    edit. Unchanged while 19.0.0 is PROPOSED (the clauses must then be absent, which this module pins); once the
    19.0.0 row is ACTIVE, the four clause edits are undone, and each must be present exactly once."""
    if re.search(r"^\| 19\.0\.0 \| 2026-10-22 \| ACTIVE", text, re.M):
        return undo_19_0_0(text)
    return text


# ------------------------------------------------------------------------------------- header, row, banner


def test_one_row_and_state_checker_passes():
    _row()
    assert len(re.findall(r"^\| 19\.0\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_row_waits_for_the_operator_or_records_the_token():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 19.0.0 must not ride a prior token"
        assert re.search(r"^Policy-Version:\s+19\.0\.0$", AGENTS, re.M), "the patch sets the header to 19.0.0"
        assert re.search(r"^Status:\s+PROPOSED$", AGENTS, re.M) and re.search(r"^Effective-Date:\s+PENDING$", AGENTS, re.M)
        assert re.search(r"^Supersedes:\s+18\.0\.0$", AGENTS, re.M)
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{40}}", rest), "ACTIVE 19.0.0 row must record token, PR and sha"


def test_banner_explains_class_number_scope_and_decisions():
    start = AGENTS.index("**19.0.0 is ")
    banner = _flat(AGENTS[start: AGENTS.index("\n\n**", start + 10)])
    for frag in ("Why MAJOR:", "broker reach §23.14 forbade", "operator-only (§17)", "It cannot be MINOR",
                 "weakest guarantee", "Ratification arms nothing", "N8N can read the broker",
                 "We're not doing any trading", "yes on passkey", "applies and commits",
                 "`scripts/lib/n8n_broker_read_carveout.py`", "every broker trading lock is LOCKED", "`read_only`",
                 "no credential in n8n", "§23.14 never-list", "`operator_settings`", "backup, audit and undo",
                 "one click", "WebAuthn passkey", "typed phrase", "TOTP is recovery only",
                 "Telegram notification only", "supersedes decision D3", "terminal-only clear",
                 "agents never call the Controls endpoints", "Byte-identical:", "§27.5", "Supersedes` 18.0.0",
                 f"{TOKEN} <pr_number> <head_sha>"):
        assert _flat(frag) in banner, frag


# --------------------------------------------------------------------------------------------------- §27


@pytest.mark.parametrize("sub,frags", [
    ("27.1", ("closed set of read lanes, nothing by analogy", "`n8n_broker_read_carveout.READ_LANES`",
              "eight §24.11 steps", "`broker_read_sync_policy.STEPS`", "`options_chain_snapshot.py`",
              "`sweep_schwab_instruments.py`", "`broker_read_sync_policy.audit()`", "`excluded_family`",
              "`runtime_denied`", "no wrapper, extra argument, pipe or second command",
              "`CARVEOUT_STATUS` is `ACTIVE`", "`broker_read_sync.lock_states()`",
              "`broker_read_sync.resolved_child_mode()`", "not merely forced so for the step",
              "`carveout_not_active`", "`trading_lock_not_locked:<broker>`", "`schwab_access_mode_not_read_only`",
              "an unreadable state refuses too", "allowlisted executor", "n8n never receives, stores or forwards",
              "Orders, stop writes, cancel, replace, order preflight, 2FA, `place_order`", "`NEVER_TOKENS`",
              "even when `ACTIVE`", "is §17", "An agent never fires, forces or re-stages a carve-out lane")),
    ("27.2", ("`operator_settings`", "with history", "overrides the repository default", "§26 registry row",
              "§17 grants", "One governed host applier", "backup", "audit row", "undo",
              "the crontab, the n8n relay live list, settings and guard grants", "No agent calls a Controls endpoint",
              "release-train request path")),
    ("27.3", ("Safe direction: one click", "STOP or pause and engaging the trading kill switch",
              "Risky direction: two factors", "clearing the trading kill switch", "resuming broker jobs",
              "changing the n8n live list", "issuing grants", "WebAuthn passkey assertion",
              "typed confirmation phrase", "supersedes decision D3", "terminal-only clear",
              "host terminal stays the fallback", "Several named passkeys", "each revoked alone",
              "needs an existing passkey", "TOTP is recovery only", "Telegram is notification only",
              "no Telegram button confirms anything", "yes on passkey")),
    ("27.4", ("Nothing is built; ratification arms nothing", "`scripts/lib/lane_dispatch.py`",
              "`FORBIDDEN_COMMAND_TOKENS`", "host CLI only", "`execution-engineering` grant")),
    ("27.5", ("Four clause edits", "`CARVEOUT_STATUS = \"ACTIVE\"`", "(1) In §23.14", "(2) In §25.4",
              "(3) In §17", "(4) In §17")),
])
def test_section_27_states_every_rule(sub, frags):
    text = _flat(_sub(_s27(), sub))
    for frag in frags:
        assert _flat(frag) in text, f"§{sub}: {frag!r}"


def test_every_section_27_bullet_cites_its_cause():
    bullets = re.split(r"\n(?=- \*\*)", _s27())[1:]
    assert len(bullets) >= 11, len(bullets)
    for b in bullets:
        assert "*Cause (§20):" in b, b[:120]


def test_section_27_5_quotes_every_clause_verbatim():
    s275 = _sub(_s27(), "27.5")
    for key, clause in CLAUSES.items():
        assert h(clause) == CLAUSE_SHA256[key], f"{key} digest"
        body = clause.lstrip("\n") if key == "C4_INS" else clause
        quoted = "\n".join(("  " + line) if line else "" for line in body.rstrip("\n").split("\n"))
        assert "  ```\n" + quoted + "\n  ```" in s275, f"{key} is not quoted verbatim in §27.5"


# ---------------------------------------------------------------------------------- byte-identical rails


@pytest.mark.parametrize("name", list(RAILS))
def test_rail_sections_are_byte_identical(name):
    start, end, digest = RAILS[name]
    assert h(_section(AGENTS, start, end)) == digest, f"{name} changed"


def test_section_26_is_byte_identical():
    m = re.search(r"^# 26 · .*?(?=^# 27 · |^# Version history)", AGENTS, re.M | re.S)
    assert m and h(m.group(0)) == SECTION_26_SHA256


def test_17_23_14_and_25_change_only_by_the_quoted_clauses_and_only_at_ratification():
    if not _ratified():
        for key in ("C1_INS", "C2_NEW", "C3_NEW", "C4_INS"):
            assert CLAUSES[key].strip("\n") not in AGENTS.replace(_s27(), ""), f"{key} in force before ratification"
        text = AGENTS
    else:
        assert (C1_ANCHOR + C1_INS) in _s23_14(AGENTS) + "\n"
        assert C2_NEW in _s25(AGENTS) and C2_OLD not in _s25(AGENTS)
        assert (C3_NEW + C4_INS) in _s17(AGENTS) and C3_OLD not in _s17(AGENTS)
        text = undo_19_0_0(AGENTS)
    assert h(_s17(text)) == SECTION_17_SHA256, "§17 changed beyond the quoted clauses"
    assert h(_s23_14(text)) == SECTION_23_14_SHA256, "§23.14 changed beyond the quoted clause"
    assert h(_s25(text)) == SECTION_25_SHA256, "§25 changed beyond the quoted clause"


def redo_19_0_0(text: str) -> str:
    """The text with the four 19.0.0 ratifying clause edits applied (the inverse of undo_19_0_0)."""
    for old, new in ((C1_ANCHOR, C1_ANCHOR + C1_INS), (C2_OLD, C2_NEW), (C3_OLD + "\n---\n\n# 17A ·",
                                                                      C3_NEW + C4_INS + "\n---\n\n# 17A ·")):
        assert text.count(old) == 1, old[:80]
        text = text.replace(old, new, 1)
    return text


def test_post_ratification_digests_are_pinned_in_advance():
    ratified = AGENTS if _ratified() else redo_19_0_0(AGENTS)
    assert h(_s17(ratified)) == SECTION_17_RATIFIED_SHA256
    assert h(_s23_14(ratified)) == SECTION_23_14_RATIFIED_SHA256
    assert h(_s25(ratified)) == SECTION_25_RATIFIED_SHA256
    assert undo_19_0_0(ratified) == pre_19_0_0(AGENTS)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_adapters_carry_nothing_from_19_0_0(adapter):
    text = (ROOT / adapter).read_text(encoding="utf-8")
    for frag in ("19.0.0", "n8n_broker_read_carveout", "Ops → Controls", "passkey", "operator_settings"):
        assert frag not in text, f"{adapter} carries {frag!r}"


# ---------------------------------------------------------------------------------------- code agrees


def test_carveout_status_follows_the_row():
    from lib import n8n_broker_read_carveout as C

    assert C.CARVEOUT_STATUS == ("ACTIVE" if _ratified() else "PROPOSED")
    assert C.POLICY_VERSION == "19.0.0" and C.POLICY_TOKEN == TOKEN
    src = (ROOT / "scripts" / "lib" / "n8n_broker_read_carveout.py").read_text(encoding="utf-8")
    assert len(re.findall(r"^CARVEOUT_STATUS = \"(?:PROPOSED|ACTIVE)\"$", src, re.M)) == 1


def test_code_and_registry_named_in_section_27_exist_and_agree():
    s27 = _s27()
    for path in ("scripts/lib/n8n_broker_read_carveout.py", "scripts/pipelines/pipeline_manifest.py",
                 "tests/test_n8n_broker_read_carveout_20261022.py",
                 "tests/test_agents_policy_19_0_0_broker_read_controls.py"):
        assert (ROOT / path).exists(), path
        assert path in s27, path
    from lib import broker_read_sync_policy as P
    from lib import n8n_broker_read_carveout as C
    from scripts.pipelines import pipeline_manifest as PM

    assert C.READ_LANES[: len(P.STEPS)] == P.STEPS
    assert {s.script for s in C.MARKET_DATA_READS} == {"scripts/options_chain_snapshot.py",
                                                          "scripts/sweep_schwab_instruments.py"}
    assert callable(PM.forbidden_command_tokens)
    auth = json.loads((ROOT / "config" / "data_source_authority.json").read_text(encoding="utf-8"))
    row = {r["domain"]: r for r in auth["proposed_domains"]}["operator_settings"]
    assert row["status"] == "proposed" and row["approval"] is None
    assert row["store"] == {"table": "operator_settings"}
    assert row["refresh_lane"]["runner"] == "host" and row["refresh_lane"]["never_list"] is True
    assert "operator_settings" not in {d["domain"] for d in auth["domains"]}, "ratification grants no registry row"
