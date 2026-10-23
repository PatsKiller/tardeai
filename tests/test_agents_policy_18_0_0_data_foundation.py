"""AGENTS.md 18.0.0 (PROPOSED, MAJOR) — §26 the data foundation: one store, one writer, the CIO as integrator.

RED UNTIL THE OPERATOR APPLIES THE PATCH. Agents never edit AGENTS.md; the amendment ships as an operator-applied patch
(scratchpad `agents-18/agents-18.0.0-proposed.patch`) built on origin/main 82180caba (17.0.0 ACTIVE). This test is
committed on `agents/data-foundation-18-0-0-20261022` ahead of it, by design, as 17.0.0's was.

Operator direction 2026-10-22 (verbatim): "The CIO agent is supposed to tie all of this together, and it should all be
in persistent memory. One data store with everything; use the CIO agent and n8n to accomplish this. This was supposed
to be the baseline of the site." and "Make sure this is the foundation of the data in the site. Make sure that this is
hard-coded in agents.md and you set the architecture of how this should work. And we should also have a data
dictionary that shows one source of data."

What this pins:
  * one 18.0.0 history row, PROPOSED with PENDING and the §20 phrase until ratified; while PROPOSED the header block
    reads 18.0.0 PROPOSED, `Effective-Date` PENDING, `Supersedes` 17.0.0; the state checker passes;
  * the banner states the class and why, the scope, the byte-identical list and the phrase;
  * §26 states every rule of the brief, and every §26 bullet cites its cause;
  * §0, §2, §2A, §7A, §17, §22, §23.14, §24 and §25 are byte-identical to origin/main 82180caba, and so are the four
    adapters;
  * the NO SILOS section is byte-identical while PROPOSED; once ratified it differs by exactly the clause §26.7 quotes;
  * the code and registry §26 names exist and agree with it.

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
# AGENTS.md 19.0.0 (§27.5): once 19.0.0 is ACTIVE its four clause edits in §17, §23.14 and §25.4 are undone before
# the pins below are checked; tests/test_agents_policy_19_0_0_broker_read_controls.py pins those edits and the
# post-ratification digests. While 19.0.0 is PROPOSED the text is unchanged.
from tests.test_agents_policy_19_0_0_broker_read_controls import pre_19_0_0  # noqa: E402

AGENTS = pre_19_0_0(AGENTS)
TOKEN = "APPROVE_AGENTS_POLICY_18_0_0"
ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")


def h(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


# Measured on origin/main 82180caba (17.0.0 ACTIVE); identical with the 18.0.0 patch applied and after ratification.
RAILS = {
    "§0": ("# 0 · If you read nothing else", "# 1 · Identity and responsibilities",
           "d10461625959d3de2f520419dbb67c1763e46d6b5905784b6aa185795ac10549"),
    "§2": ("# 2 · Authority rails", "# 2A ·", "5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af"),
    "§2A": ("# 2A ·", "# 2B ·", "38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb"),
    "§7A": ("# 7A ·", "# 8 ·", "6d20888d1329397351c75a54a4c3e2e7978d5974cef6c3c306dc708580b5ca90"),
    "§17": ("# 17 · Operator-only decisions", "# 17A ·",
            "2d9adf898494ee81e620be49f89a8cfde717737f87069462eb41893229ee3473"),
    "§22": ("# 22 · ", "# 23 · ", "81f1646a64e38047882c7375ab18739111ba8349471fbaa0351fc1069f9717e9"),
    "§24": ("# 24 · ", "# 25 · ", "766e69e45faf210f1ca268616bd34fbcf3f8d69d4a156f6205c6de1280806745"),
}
SECTION_23_14_SHA256 = "891c55a5be08630952c61300f95bcb5442f1ef6b37fb5cb5018e72f843a9043f"
SECTION_25_SHA256 = "8a01162d312671a4ec52d133f8d9e8906eacddc9b0c8704bc0b48d731462977b"
NO_SILOS = ("## Shared security research — NO SILOS", "## Research lanes")
NO_SILOS_SHA256 = "76673de1a33f5f05075c001d7985fb5788b198c76220e4c340538bcd1360a749"
CLAUSE_OLD = ("1. **One security → one spine.** Key by `subject_guid` when known; always carry `symbol`.\n"
              "   Identity rules above still apply (`issuer_guid` / `subject_guid` — never invent a second map).\n")
CLAUSE_NEW = ("1. **One security → one spine → one prospect.** Key by `security_guid` (`subject_guid` is the same\n"
              "   value for a security and is mapped, never a second key); carry `issuer_guid` and `symbol`.\n"
              "   The spine feeds the CIO prospect record, the single per-security truth (§26).\n")


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
    m = re.search(r"^\| 18\.0\.0 \| 2026-10-22 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 18.0.0 | 2026-10-22 | PROPOSED|ACTIVE | MAJOR |` row: the 18.0.0 patch is not applied"
    return m


def _ratified() -> bool:
    return _row().group(1) == "ACTIVE"


def _s26() -> str:
    m = re.search(r"^# 26 · Data foundation.*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert m, "§26 missing: the 18.0.0 patch is not applied"
    return m.group(0)


# ------------------------------------------------------------------------------------- header, row, banner


def test_one_row_and_state_checker_passes():
    _row()
    assert len(re.findall(r"^\| 18\.0\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_row_waits_for_the_operator_or_records_the_token():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 18.0.0 must not ride a prior token"
        assert re.search(r"^Policy-Version:\s+18\.0\.0$", AGENTS, re.M), "the patch sets the header to 18.0.0"
        assert re.search(r"^Status:\s+PROPOSED$", AGENTS, re.M) and re.search(r"^Effective-Date:\s+PENDING$", AGENTS, re.M)
        assert re.search(r"^Supersedes:\s+17\.0\.0$", AGENTS, re.M)
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{40}}", rest), "ACTIVE 18.0.0 row must record token, PR and sha"


def test_banner_explains_class_number_scope_and_decisions():
    start = AGENTS.index("**18.0.0 is ")
    banner = _flat(AGENTS[start: AGENTS.index("\n\n**", start + 10)])
    for frag in ("Why MAJOR:", "role authority", "an ambiguous class takes the higher one", "17.1.0",
                 "single per-security truth", "one authoritative store and one writer", "§7A registry",
                 "docs/architecture/DATA_DICTIONARY.md", "registered projections", "§23.14 never-list",
                 "never silently resolved", "operator-only (§17)", "tripwire", "MBI_BEHAVIOR = 0",
                 "grants none of the proposed registry rows", "Byte-identical:", "§26.7",
                 f"{TOKEN} <pr_number> <head_sha>", "One data store with everything",
                 "a data dictionary that shows one source of data"):
        assert _flat(frag) in banner, frag


# --------------------------------------------------------------------------------------------------- §26


@pytest.mark.parametrize("sub,frags", [
    ("26.1", ("One row per `security_guid`, written only by the CIO agent", "`InstrumentRecord@v1` extended",
              "extend, never clone", "watching → setup forming → actionable → proposed → held → exit / re-entry",
              "conviction 0–100 with named components", "stance", "catalyst grade", "next trigger",
              "what is missing", "next action", "`evidence_at` / `expires_at`", "conflicts", "Postgres",
              "`InstrumentRecordStore`", "an export generated from the record", "`subject_guid` is an alias",
              "never stored as a second key", "identity unresolved", "`MBI_BEHAVIOR = 0`",
              "never sizes, orders, stops or weights", "`BEHAVIOR_FIELDS`", "registered capabilities")),
    ("26.2", ("not a second one", "positions, cash, marks, stops, basis", "one writer (or a declared `UNCONSOLIDATED`",
              "one refresh lane, one freshness SLA", "`proposed_domains[]`", "`status: \"proposed\"`",
              "operator's grant (§17)", "`DICTIONARY_SECOND_WRITER`", "`NON_AUTHORITATIVE_READ`",
              "`DICTIONARY_INVALID`", "a proposed row only warns")),
    ("26.3", ("Home, Watch, Trade AI, Options, Open Trades, Telegram, Proposals and Re-entry", "`cio_prospect`",
              "never a copy, never a store directly", "Changing what a surface ranks stays §17", "`top_ideas.v2`")),
    ("26.4", ("decides nothing and writes nothing", "shadow → canary → cutover (§23.21)",
              "stops, orders, paper execution, the options tick, senders and daemons stay on the host (§23.14)",
              "`broker-read` grant (§24.11)")),
    ("26.5", ("recorded conflict", "both values, both sources and both times", "every surface shows it",
              "never auto-merged", "(§0 rule 5)")),
    ("26.6", ("is §17, row by row", "grants none of the proposed rows, creates no table and moves no reader",
              "shadow → compare → switch readers", "generated export of `positions_current`",
              "archived with a tripwire", "never deleted")),
    ("26.7", ("One clause", "NO SILOS", "Methodology rule 1")),
])
def test_section_26_states_every_rule(sub, frags):
    text = _flat(_sub(_s26(), sub))
    for frag in frags:
        assert _flat(frag) in text, f"§{sub}: {frag!r}"


def test_every_section_26_bullet_cites_its_cause():
    bullets = re.split(r"\n(?=- \*\*)", _s26())[1:]
    assert len(bullets) >= 9, len(bullets)
    for b in bullets:
        assert "*Cause (§20):" in b, b[:120]


def test_section_26_quotes_both_forms_of_the_clause_verbatim():
    s267 = _sub(_s26(), "26.7")
    for clause in (CLAUSE_OLD, CLAUSE_NEW):
        quoted = "\n".join(("  " + line) if line else "" for line in clause.rstrip("\n").split("\n"))
        assert "  ```\n" + quoted + "\n  ```" in s267, clause[:60]


# ---------------------------------------------------------------------------------- byte-identical rails


@pytest.mark.parametrize("name", list(RAILS))
def test_rail_sections_are_byte_identical(name):
    start, end, digest = RAILS[name]
    assert h(_section(AGENTS, start, end)) == digest, f"{name} changed"


def test_23_14_and_25_are_byte_identical():
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", AGENTS, re.M | re.S)
    assert sec and h(_sub(sec.group(0), "23.14")) == SECTION_23_14_SHA256
    s25 = re.search(r"^# 25 · .*?(?=^# 26 · |^# Version history)", AGENTS, re.M | re.S)
    assert s25 and h(s25.group(0)) == SECTION_25_SHA256


def test_no_silos_changes_only_by_the_quoted_clause_and_only_at_ratification():
    block = _section(AGENTS, *NO_SILOS)
    if not _ratified():
        assert CLAUSE_NEW not in AGENTS, "the NO SILOS clause changed before ratification"
        assert block.count(CLAUSE_OLD) == 1 and h(block) == NO_SILOS_SHA256
    else:
        assert block.count(CLAUSE_NEW) == 1 and CLAUSE_OLD not in block
        assert h(block.replace(CLAUSE_NEW, CLAUSE_OLD, 1)) == NO_SILOS_SHA256, "more than the clause changed"


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_adapters_carry_nothing_from_18_0_0(adapter):
    text = (ROOT / adapter).read_text(encoding="utf-8")
    for frag in ("18.0.0", "cio_prospect", "Data foundation", "DATA_DICTIONARY"):
        assert frag not in text, f"{adapter} carries {frag!r}"


# ---------------------------------------------------------------------------------------- code agrees


def test_code_and_registry_named_in_section_26_exist_and_agree():
    s26 = _s26()
    for path in ("docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md", "docs/architecture/DATA_DICTIONARY.md",
                 "config/data_source_authority.json", "scripts/render_data_dictionary.py",
                 "scripts/check_data_source_authority.py", "scripts/lib/data_dictionary.py",
                 "scripts/lib/cio_instrument_record.py"):
        assert (ROOT / path).exists(), path
        assert path in s26, path
    from lib import data_dictionary as DD
    from lib.cio_instrument_record import BEHAVIOR_FIELDS
    auth = json.loads((ROOT / "config" / "data_source_authority.json").read_text(encoding="utf-8"))
    rows = {r["domain"]: r for r in auth.get("proposed_domains") or []}
    rows.update({d["domain"]: d for d in auth["domains"] if isinstance(d.get("dictionary"), dict)})
    prospect = rows["cio_prospect"]
    assert prospect["store"] == {"table": "cio_prospect"}
    assert prospect["writer"] == "scripts/lib/cio_instrument_record.py"
    assert auth["data_dictionary"]["canonical_key"]["per_security"] == "security_guid"
    for name in ("DICTIONARY_SECOND_WRITER", "NON_AUTHORITATIVE_READ", "DICTIONARY_INVALID"):
        assert name in (ROOT / "scripts" / "lib" / "data_dictionary.py").read_text(encoding="utf-8")
    fields = {f["field"] for f in auth["data_dictionary"]["records"]["CIOProspect"]["fields"]}
    assert not (fields & set(BEHAVIOR_FIELDS))
    assert DD.SCHEMA == auth["data_dictionary"]["schema"]
