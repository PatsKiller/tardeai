"""AGENTS.md 20.0.0 (PROPOSED, MAJOR) — §28 agent operations and the read-only broker baseline.

Shipped as an OPERATOR-COMMITTED package (operator, 2026-10-22: "yes i approve “approve all” (A–L)"; the rule
changes are a diff the operator applies and commits; agents do not edit AGENTS.md or its pinning tests). Built on the
19.0.0-ACTIVE AGENTS.md (PR #1962). Approved as "19.1.0"; the version policy numbers it 20.0.0 (§0 rule 10).

What this pins:
  * one 20.0.0 history row, PROPOSED with PENDING and the §20 phrase until ratified; while PROPOSED the header block
    reads 20.0.0 PROPOSED, `Effective-Date` PENDING, `Supersedes` 19.0.0; the state checker passes;
  * the banner states the class and why, the scope, the byte-identical list and the phrase;
  * §28 states every approved rule, and every §28 bullet cites its cause;
  * §2A, §7A, §22, §23 and §26 are byte-identical to 19.0.0;
  * §0, §2, §7, §13, §17, §24, §25, §27 and the four adapters are byte-identical while PROPOSED; once ratified they
    differ by exactly the nine clause edits §28.7 quotes, whose sha256 and post-ratification digests are pinned here;
  * `pre_20_0_0()` gives the older policy tests the text as it was before the 20.0.0 ratifying edit.

Read-only: reads repository files. TRADE_AI_CI=1.
"""

from __future__ import annotations

import hashlib
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
TOKEN = "APPROVE_AGENTS_POLICY_20_0_0"
ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")


def h(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


# The nine clause edits of the ratifying edit, byte for byte as build_ratify20.py makes them and §28.7 quotes them.
R0_ANCHOR = (
    '   config/disk_hygiene_rules.json), and nothing else (AGENTS.md §24.12).\n'
)
R0_INS = (
    '   A second exception, binding only once AGENTS.md 20.0.0 is ACTIVE: the host /tmp hygiene lanes\n'
    '   may remove the /tmp items their reviewed tmp.* rules select (scripts/tmp_hygiene_auto.py),\n'
    '   and nothing else (AGENTS.md §24.12).\n'
)
R1_ANCHOR = (
    '  a refusal elsewhere is never routed through it.*\n'
)
R1_INS = (
    '- **Named addition (20.0.0): the host `/tmp` hygiene lanes.** Besides `scripts/disk_hygiene.py`, exactly these may\n'
    '  remove items under this exception: `scripts/tmp_hygiene_auto.py`, run on the host by the systemd user timers\n'
    '  `tradeai-tmp-hygiene-apply` (hourly) and `tradeai-tmp-hygiene-pressure` (every 5 minutes; it acts only at 85% or\n'
    '  more `/tmp` inode use, and at most once per 15 minutes). They remove only items the reviewed `tmp.*` rules in\n'
    '  `config/disk_hygiene_rules.json` select, and only under `/tmp`; they never run under the n8n executor. The\n'
    '  standing approval is `tmp.auto_apply.standing_approval` and the kill switch is `tmp.auto_apply.enabled`; a manual\n'
    '  `scripts/tmp_hygiene.py --apply` still needs the grant. They never touch a dirty, unpushed or unregistered\n'
    '  worktree, never run `git worktree remove --force`, and never touch a `tmp.never_touch_globs` path (including\n'
    '  `tradeai-*`); every run writes a deletions ledger and a `LaneRunReceipt`. These lanes are named here; nothing\n'
    '  broader is added, and no other deletion code is covered by analogy. *Cause (§20): operator 2026-10-22,\n'
    '  verbatim: "It needs to be able to delete it. Just looking at it won\'t do anything." (`/tmp`, a tmpfs, at 99%\n'
    '  inodes while the tmp lane ran plan-only), and "approve all" for the 20.0.0 package; PR #1954.*\n'
)
R2_ANCHOR = (
    '  `feat/release-train-authority-20261021`, on origin/main `4104effb9` (release 2) and on `065f1083c` (16.0.0\n'
    '  ACTIVE), 2026-10-21.*\n'
)
R2_INS = (
    '- **The release-train claimer is installed and refuses live work.** `tradeai-release-train-claim.service`, with its\n'
    '  `.timer` (every minute) and `.path` units, is installed on the host and answers n8n `TrainWindowRequest` files.\n'
    '  While `TRAIN_CONTROLLER_STATUS` is `BUILD_ONLY` it refuses every live request with `CONTROLLER_BUILD_ONLY` and\n'
    '  never pushes, merges or promotes. It must be declared in the lane registry, and its unit header must say it is\n'
    '  installed; both are code follow-ups. *Cause (§20): measured on the host 2026-10-22 (`systemctl --user\n'
    '  list-timers`; the unit header still reads "PROPOSED, NOT INSTALLED", and `scripts/ai_local_acceptance.sh`\n'
    '  stops on the undeclared timer).*\n'
)
R3_ANCHOR = (
    '\n'
    '## Caches and derived stores — fail closed, never open\n'
)
R3_INS = (
    '## Timeouts, reaper caps and kill windows — measured, never guessed `[VERIFIED]` 2026-10-22\n'
    '\n'
    'Single reference: `docs/ops/PIPELINE_TIME_SETTINGS.md`. Pinned by\n'
    '`tests/test_pipeline_time_settings_20261022.py` (CI gate `pipeline_time_settings_20261022`).\n'
    '\n'
    '- **Never lower a timeout, reaper cap, orphan wait or tick deadline without measured runtime\n'
    '  evidence in the PR**: the query, the window, the output. The test, the doc table and the setting\n'
    '  change together. *Cause: two caps nobody had measured killed two `pipeline_critical` pipelines on\n'
    '  every run.*\n'
    '  - `trade_ai_orchestrator` at the 20 m reaper cap: every market-hours run on 2026-10-21/22 was SIGTERMed\n'
    '    at 1216–1377 s (20 + 22 failed).\n'
    "  - `symbol_enrichment` under the health tick's `orphan_wait_s: 30`: 224 failed / 1 success in 36 h.\n"
    '- **A runtime measured under a kill is censored, not a distribution.** If runs die at the cap, the longest\n'
    '  "observed" runtime is the cap. Read the pre-cap era or the uncensored completions.\n'
    '  - *Cause:* "enrichment takes 25–50 s" was the survivors of a 30 s kill.\n'
    '  - The uncensored distribution, 2026-09-20..10-07 (n=3,178), is p50 136 s / p95 241 s / max 419 s.\n'
    "  - The orchestrator's 1377 s is a floor.\n"
    '- **Current values; do not lower them:**\n'
    '  - **orchestrator reaper cap.** `max_runtime_min` is **30** in `config/process_reaper_policy.json` and\n'
    '    `scripts/process_reaper.py` `DEFAULT_RULES`, and the two must be equal. 30 m ≥ 1377 s + 300 s, and it stays\n'
    "    under `continuous_runner.py`'s 2700 s.\n"
    '  - **health tick.** `tick_deadline_s` is **300**; 300 + 10 s kill grace + receipt < unit `TimeoutStartSec=330`.\n'
    '  - **watchdog enrichment.** The batch wait is **min(240 s, `HEALTH_TICK_STEP_TIMEOUT_S` − 15 s)**, and\n'
    '    `pipeline-watchdog` runs **last** in the tick.\n'
    '  - **`orphan_wait_s`.** It stays **30**, as a legacy safety net only.\n'
    '- **A step that needs its children to finish supervises them; it does not get a longer orphan wait.**\n'
    '  `orphan_wait_s` is paid once per step against the shared 300 s tick.\n'
    '  - A step that waits for children must run where waiting cannot defer the steps after it.\n'
    '  - At 4th place, a 240 s wait would have deferred seven monitors on every even-hour tick.\n'
    '\n'
)
R5_ANCHOR = (
    '  stays the fallback. *Cause (§20): operator decisions 2026-10-22, "yes on passkey".*\n'
)
R5_INS = (
    '- **Sudo window (20.0.0, §28.5).** One passkey assertion may open a window, bound to that browser session and\n'
    '  that passkey, during which a risky act needs only its typed phrase. The window lasts the operator setting\n'
    '  `ops_controls.sudo_window_minutes` (default 60, at most 120) and ends on 15 minutes idle, on logout or on "End\n'
    '  window now"; the page shows the time left. Issuing a grant, clearing the kill switch, adding or revoking a\n'
    '  passkey and changing the window settings always need a fresh assertion. Every act inside a window is audited\n'
    '  with the assertion that opened it, and agents still never call a Controls endpoint. *Cause (§20): operator\n'
    '  2026-10-22, verbatim: "we need a time to live for this. Maybe 1 hour or 2 hours. So it caches." and "approve\n'
    '  sudo window".*\n'
)
R6_OLD = (
    '- **Nothing is built; ratification arms nothing.** There is no carve-out executor wrapper, no allowlist entry or\n'
    '  dispatcher row for a carve-out lane, and `scripts/lib/lane_dispatch.py` still refuses every\n'
    '  `FORBIDDEN_COMMAND_TOKENS` hit; the Controls surface, the applier, the `operator_settings` table and the passkey\n'
    '  store do not exist. Each comes in its own reviewed PR, and activating a workflow or adding a dispatcher row stays §17\n'
    '  (§23.11). Until the passkey step-up is built and verified, a risky act is made at the host CLI only (§25.4). The\n'
    '  kill-switch code is in the broker execution set: changing its clear path needs an `execution-engineering` grant (§0\n'
    '  rule 2). *Cause (§20): measured 2026-10-22 on `2d8fc9574`.*\n'
)
R6_NEW = (
    '- **Ops → Controls is built and served; the carve-out lanes are not.** The page, its API, the host applier\n'
    '  (`tradeai-ops-applier.service`), the `operator_settings` tables and the passkey store exist (PR #1941, served\n'
    '  from release 6), and the operator enrolled the first passkey on 2026-10-22. There is no carve-out executor\n'
    '  wrapper, no allowlist entry or dispatcher row for a carve-out lane, and `scripts/lib/lane_dispatch.py` still\n'
    '  refuses every `FORBIDDEN_COMMAND_TOKENS` hit; each comes in its own reviewed PR, and activating a workflow or\n'
    '  adding a dispatcher row stays §17 (§23.11). Release-train resume and arm stay at the host CLI until a passkey\n'
    '  proof kind for `release_control` ships in its own reviewed PR. The kill-switch code is in the broker execution\n'
    '  set: changing its clear path needs an `execution-engineering` grant (§0 rule 2). *Cause (§20): measured\n'
    '  2026-10-22 on `2d8fc9574`; corrected by 20.0.0 after PR #1941 shipped and was served (§0 rule 10).*\n'
)
R7_ANCHOR = (
    '\n'
    'Controls endpoint or the host applier.\n'
    '\n'
    '---\n'
    '\n'
    '# 17A ·'
)
R7_INS = (
    '\n'
    '**Schwab stays read-only (20.0.0, §28.6):** changing the Schwab access mode away from `read_only` · unlocking a\n'
    "broker trading lock · clearing a `live_submit` or `broker` kill switch. Each is the operator's alone, made with a\n"
    'passkey on Ops → Controls or at the host terminal; never by an agent, a release, the release train or n8n.\n'
)
R8_INTRO_OLD = (
    'These ten prevent irreversible harm. They are repeated verbatim in every tool adapter, because an\n'
    'agent that reads fifteen lines and stops must still know them.\n'
)
R8_INTRO_NEW = (
    'These ten prevent irreversible harm, and rule 11 keeps work recoverable. They are repeated verbatim\n'
    'in every tool adapter, because an agent that reads fifteen lines and stops must still know them.\n'
)
R8_ANCHOR = (
    '10. **When a finding contradicts this file, the finding wins.** Report it once, continue, and open\n'
    '    an amendment PR (§20).\n'
)
R8_INS = (
    '11. **Claim, log, hand off.** Before editing, read the claim board and the active worklogs\n'
    '    (`scripts/agent_claim.py status`); claim your files; keep your worklog current (plan, changes,\n'
    '    decisions, blockers, handoff); when you stop for any reason, leave the exact next step. Work in\n'
    '    progress must be recoverable by any agent of any vendor: commit locally at least every hour,\n'
    '    record branch, worktree path and head SHA in the worklog, and push a draft PR, within the push\n'
    '    budget, for anything a cloud agent may need. Taking over a stale or abandoned claim is done with\n'
    '    `agent_claim.py takeover`, never by starting over. How to pick up work: AGENTS.md §28.3a.\n'
)
C8_PAIRS = (
    ('> **The rail is the unconditional raise at `scripts/lib/cio_instrument_record.py:390`.** It\n',
     '> **The rail is the unconditional `BehaviorWriteRefused` raise in `apply_cognition()`\n> (`scripts/lib/cio_instrument_record.py`).** It\n'),
    ('All 51 occurrences are prose. The rail is an unconditional raise at `cio_instrument_record.py:390`. |\n',
     'All 51 occurrences are prose. The rail is the unconditional `BehaviorWriteRefused` raise in `cio_instrument_record.apply_cognition()`. |\n'),
    ('                     Not an env var: an unconditional raise at cio_instrument_record.py:390.\n',
     '                     Not an env var: the unconditional raise in cio_instrument_record.apply_cognition().\n'),
    ('`BEHAVIOR_FIELDS`, altering or conditionalising the unconditional raise at\n`scripts/lib/cio_instrument_record.py:390`, or routing a cognition write around it; there is no\n',
     '`BEHAVIOR_FIELDS`, altering or conditionalising the unconditional raise in\n`apply_cognition()` (`scripts/lib/cio_instrument_record.py`), or routing a cognition write around it; there is no\n'),
)

CLAUSE_SHA256 = {
    'R0_ANCHOR': '76c5b18e4be34c14d0a5afd61455f9b52d821066ffaa7362f076f9d722b82aca',
    'R0_INS': 'b62d0f157e9089ba793f89a337b5ca829b0e00777e90475db9d5d81b82d6f363',
    'R1_ANCHOR': '66379cb4181ed51147186d4fdc97b30851ae831364b608caa4cf28e4a2a9c872',
    'R1_INS': '3e0821c36d5c150c8a8c1360feee13e96447fdab7f5b9601ff7ed54a9c432af6',
    'R2_ANCHOR': '4803429b86cda31b8d229274bb3c43e7e6c00e8650472b0b12e1028eacad2204',
    'R2_INS': '25befb5092b1d2ba265d03442d8fde2f5e6a06b063c037bf90e55f658025589b',
    'R3_ANCHOR': '5fe262229415e4b2b660eff380c307b6917458676d415f91219136268015e136',
    'R3_INS': 'c39bccf4b1f129bcb235f0b3b0e3c6307e2aecbe5df291e2dbba6740c308a774',
    'R5_ANCHOR': '9195950c6439646c86b52fe3ae3e5b18b4912758c229be073ad075f07a67eb76',
    'R5_INS': 'd61f11f5638e6fa142cce792bfbed9ed51d9afac0bf5254b8012b137f8cd22e7',
    'R6_OLD': '7ae7a4f2c3ad82fb28f645f13f00aab1662a7e0785f8d26d4fd578346c1bfe08',
    'R6_NEW': 'c953cdf3be279d6f7f61b8c2124b69ab69e20d752faef52c9eefcfd20eaeb5fd',
    'R7_ANCHOR': 'efd28c20cbe6e103d8f8df3bdd6176c952df2d029d5a8a43970b8d8d1e2fa528',
    'R7_INS': 'da888f937d0022c5afae2ed353e6b0a724ca079838af0469dcb4c4ed9f687197',
    'R8_INTRO_OLD': '34531791713dbfaa414c9599eeb2aedafe7528e6dcf735f87434d727d7657d8c',
    'R8_INTRO_NEW': 'e48e84e3400a00771604a4053c776498048c93a4f62066abe82e2285da83e82c',
    'R8_ANCHOR': '919de72c5643a9a1b8396eb62bd54585e874b35d246ac722b128eb42307d1d2e',
    'R8_INS': '08ffc2cf6a4351b5cdb63be6d20810f99e6bbab51c270778ad6ccbe48af7afbb',
    'C8_PAIRS': '0dccb586a8e24994c583c4e583dcb157bc6e2bccdde5b75afff2ea8f52b6d230',
}

# Section digests on the 19.0.0-ACTIVE base; while PROPOSED, and after the clause edits are undone, they are equal.
SECTION_SHA256 = {
    '§0': 'd10461625959d3de2f520419dbb67c1763e46d6b5905784b6aa185795ac10549',
    '§2': '5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af',
    '§7': '7c49a19f866d5f93604bd19c850e3128297a61a3d250446f3a1f68a2c45b5e80',
    '§13': 'e0cecf38b365c77bd09561a619381ed8ca7b1cd59afe802da24ac1cfb56bef0c',
    '§17': '59985a21b19925f864133f3e709271f450ebac79884b1f835108a93d89c82df8',
    '§24': '766e69e45faf210f1ca268616bd34fbcf3f8d69d4a156f6205c6de1280806745',
    '§25': 'd8122a733dfd6ab45398b8e57d9c871b083ffc8a369d3b01da3aa5ac996f7844',
    '§27': '8f77a468c73b640a5235225817f11c3339452805d04d62c95dbb86be44e8eb1c',
    '§2A': '38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb',
    '§7A': '6d20888d1329397351c75a54a4c3e2e7978d5974cef6c3c306dc708580b5ca90',
    '§22': '81f1646a64e38047882c7375ab18739111ba8349471fbaa0351fc1069f9717e9',
    '§23': '7dbf3e88196ee4e7fa3fee186da00886ecf61bd6bf673a5e4ab1279e71b8dd76',
    '§26': '80b1d81d7198c5cca2c78a3beb86e22516ca1252bfc9c56e6013063d4eccf511',
}
# Post-ratification digests, pinned in advance (the clause edits carry no PR, SHA or date).
SECTION_RATIFIED_SHA256 = {
    '§0': '58d094fbc2a30dbfb5b1f53db75c9c31e1c5b6e87c22265085a43ec71edd8980',
    '§2': 'dc64e8149afc60a8bbd4c33194e112c2147a1503c53bf19ab731e5524ae7d4db',
    '§7': 'f2e1b15d8ce064893858ec5e47f9f303f29a50a7903ded6ea06d23d51168e706',
    '§13': '7eefee9e485e12daa33c60f6fc1ec2facd47d67e2b73d3f775dfee26ef21f37e',
    '§17': '8bbcf7890b4557ae3089fb0194637a3a768b1f637833d74e5b446e1bfcca7eb8',
    '§24': '0f6a01f549bf36e489231183244bf001a4c370f04c714bb73cc863533fcf505f',
    '§25': '0382aa9aa758e220cfdcc882e687194c02f37e322412bf6bcbe979bb6a26b22d',
    '§27': 'f6934ac1d4fd824563f3f1a1cb1f8daca8eb2b182f313f2e412cdd7e489680fa',
}
ADAPTER_SHA256 = {
    'CLAUDE.md': '149cc7d69c8f574ccd03b3f5febc9af16289eca239b839c3a1fb394634945bbf',
    '.cursor/rules/00-tradeai-work-policy.mdc': 'c78f412f203a4394c845a55e6593486097552b41da33c8e8dfae6dc072d22534',
    '.github/copilot-instructions.md': '34bcb29c05e2ff84c3b4d2674f4593e70f2284990086386d50daf51cdf3a32d0',
    '.goosehints': '4ef4146ea7f316a77c8114ff048e1715a29791eaba0c5aa86e450ea00c7c452a',
}
ADAPTER_RATIFIED_SHA256 = {
    'CLAUDE.md': '04df92d64e45d372d31963aa006c97d6b03770f1b081c60c69a211fdbaaa8880',
    '.cursor/rules/00-tradeai-work-policy.mdc': 'b7308162f626bdb78212c18112a94061cfc1a9afa25f675cc0413edba8214f7c',
    '.github/copilot-instructions.md': '1cfaa8fba009e5a142328ecdd9d30fe3bf0cc2d4861b6c35271e4d084b902a48',
    '.goosehints': 'ad79ef5fa172d34eaafad36392734aac0d4d37d7513529bef335b7de0dbec8df',
}

BOUNDS = {
    "§0": ("# 0 · If you read nothing else", "# 1 · Identity and responsibilities"),
    "§2": ("# 2 · Authority rails", "# 2A ·"), "§2A": ("# 2A ·", "# 2B ·"),
    "§7": ("# 7 · ", "# 7A ·"), "§7A": ("# 7A ·", "# 8 ·"), "§13": ("# 13 · ", "# 14 · "),
    "§17": ("# 17 · Operator-only decisions", "# 17A ·"), "§22": ("# 22 · ", "# 23 · "),
    "§23": ("# 23 · ", "# 24 · "), "§24": ("# 24 · ", "# 25 · "), "§25": ("# 25 · ", "# 26 · "),
    "§26": ("# 26 · ", "# 27 · "),
}
CHANGING = ("§0", "§2", "§7", "§13", "§17", "§24", "§25", "§27")
FIXED = ("§2A", "§7A", "§22", "§23", "§26")
S27_HEAD = "\n# 27 · n8n broker reads and the operator controls surface"


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _section(text: str, name: str) -> str:
    if name == "§27":
        m = re.search(r"^# 27 · .*?(?=^# 28 · |^# Version history)", text, re.M | re.S)
        assert m, "§27 missing"
        return m.group(0)
    start, end = BOUNDS[name]
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
    m = re.search(r"^\| 20\.0\.0 \| 2026-10-22 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 20.0.0 | 2026-10-22 | PROPOSED|ACTIVE | MAJOR |` row: the 20.0.0 patch is not applied"
    return m


def _ratified() -> bool:
    return _row().group(1) == "ACTIVE"


def _s28() -> str:
    m = re.search(r"^# 28 · Agent operations.*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert m, "§28 missing: the 20.0.0 patch is not applied"
    return m.group(0)


# Each edit as (text before the ratifying edit, text after it), in the order the ratifying edit applies them.
EDITS = (
    (R0_ANCHOR + "7. **Dry-run", R0_ANCHOR + R0_INS + "7. **Dry-run"),
    (R1_ANCHOR, R1_ANCHOR + R1_INS),
    (R2_ANCHOR, R2_ANCHOR + R2_INS),
    (R3_ANCHOR, "\n" + R3_INS + R3_ANCHOR.lstrip("\n")),
    (R5_ANCHOR, R5_ANCHOR + R5_INS),
    (R6_OLD, R6_NEW),
    (R7_ANCHOR, "\nControls endpoint or the host applier.\n" + R7_INS + "\n---\n\n# 17A ·"),
    (R8_INTRO_OLD, R8_INTRO_NEW),
    (R8_ANCHOR + "\n---\n", R8_ANCHOR + R8_INS + "\n---\n"),
)


def _c8(text: str, forward: bool) -> str:
    cut = text.index(S27_HEAD)
    head, tail = text[:cut], text[cut:]
    for old, new in C8_PAIRS:
        a, b = (old, new) if forward else (new, old)
        assert head.count(a) == 1, a[:80]
        head = head.replace(a, b)
    return head + tail


def redo_20_0_0(text: str) -> str:
    """The nine clause edits applied (what the ratifying edit does to the body)."""
    for i, (old, new) in enumerate(EDITS):
        assert text.count(old) == 1, old[:80]
        text = text.replace(old, new, 1)
        if i == 3:
            text = _c8(text, True)
    return text


def undo_20_0_0(text: str) -> str:
    """The text with the eight 20.0.0 ratifying clause edits reversed (each must be present exactly once)."""
    for i, (old, new) in reversed(list(enumerate(EDITS))):
        if i == 3:
            text = _c8(text, False)
        assert text.count(new) == 1, new[:80]
        text = text.replace(new, old, 1)
    return text


def pre_20_0_0(text: str) -> str:
    """For the older policy tests' pins: the AGENTS.md text as it was before the 20.0.0 ratifying edit. Unchanged
    while 20.0.0 is PROPOSED; once the 20.0.0 row is ACTIVE, the nine clause edits are undone."""
    if re.search(r"^\| 20\.0\.0 \| 2026-10-22 \| ACTIVE", text, re.M):
        return undo_20_0_0(text)
    return text


def pre_20_0_0_adapter(text: str) -> str:
    """An adapter as it was before the 20.0.0 ratifying edit: the §0 rule 6 sentence, the intro sentence and
    rule 11 undone when present (an adapter is a verbatim copy of §0)."""
    text = text.replace(R0_ANCHOR + R0_INS, R0_ANCHOR, 1).replace(R8_INTRO_NEW, R8_INTRO_OLD, 1)
    if text.endswith(R8_ANCHOR + R8_INS):
        text = text[: -len(R8_INS)]
    return text


# ------------------------------------------------------------------------------------- header, row, banner


def test_one_row_and_state_checker_passes():
    _row()
    assert len(re.findall(r"^\| 20\.0\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_row_waits_for_the_operator_or_records_the_token():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert re.search(r"^Policy-Version:\s+20\.0\.0$", AGENTS, re.M)
        assert re.search(r"^Status:\s+PROPOSED$", AGENTS, re.M) and re.search(r"^Effective-Date:\s+PENDING$", AGENTS, re.M)
        assert re.search(r"^Supersedes:\s+19\.0\.0$", AGENTS, re.M)
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{40}}", rest), "ACTIVE 20.0.0 row must record token, PR and sha"


def test_banner_explains_class_number_scope_and_decisions():
    start = AGENTS.index("**20.0.0 is ")
    banner = _flat(AGENTS[start: AGENTS.index("\n\n**", start + 10)])
    for frag in ("Why MAJOR:", "narrows §0 rule 6", "sudo window", "weakest guarantee", "It cannot be MINOR",
                 "approve sudo window", "So can we do A through E?", "“approve all” (A–L)", "\"19.1.0\"",
                 "numbers them 20.0.0 (§0 rule 10)", "no agent outranks another", "Ratification arms nothing",
                 "`ops_controls.sudo_window_enabled`", "`scripts/agent_claim.py`", "Byte-identical:", "§28.7",
                 "`Supersedes` 19.0.0", "§0 rule 11", "Claim, log, hand off", "(§28.3a)", "(§28.3b)",
                 "We shouldn't lose anything just because different developers or agents working on it",
                 f"{TOKEN} <pr_number> <head_sha>"):
        assert _flat(frag) in banner, frag


# --------------------------------------------------------------------------------------------------- §28


@pytest.mark.parametrize("sub,frags", [
    ("28.1", ("Four named automations, and only these", "`scripts/process_reaper.py`", "`scripts/health_tick.py`",
              "`scripts/remediate_pipeline_failures.py`", "`scripts/pipeline_watchdog.py`",
              "never covered by analogy", "measured, never guessed", "censored floor",
              "`docs/ops/PIPELINE_TIME_SETTINGS.md`", "reviewed config PR", "reason is non-empty",
              "within its own clamped timeout")),
    ("28.2", ("No new temp data under `/tmp`", "`TMPDIR=~/.cache/rtc`", "worktrees under `$HOME`",
              "the scratch copies it made itself", "safety net, not the plan")),
    ("28.3", ("Look before building", "Claude, Codex/OpenAI, Cursor", "the claim board", "`scripts/agent_claim.py`",
              "`heartbeat`", "2 hours is stale", "draft PR", "first claim or PR owns the fix",
              "No agent, model or vendor outranks another", "`claimed` → `building` → `pr_open` → `ci_green` →",
              "`merged` → `released`", "`abandoned`", "recorded with its time", "advance automatically from GitHub",
              "may set `building` and `pr_open` itself", "Goal", "Plan (checkbox steps)", "Changes made", "Decisions",
              "Blockers", "Status and Handoff", "`agent_claim.py plan`, `done`, `note` and `blocker`",
              "annotated done when it is complete", "release requires a final summary", "archived, never deleted",
              "`~/trade-ai-releases/persistent-state/data/coordination/worklogs/`", "coordinator worklog",
              "pre-commit gate refuses a commit with no claim", "held by another session's active claim",
              "no plan or no recent worklog entry", "`TRADEAI_CLAIM_OVERRIDE=<reason>`", "is logged",
              "Before the tool and gate exist, a missing claim or worklog is a warning",
              "put their complete changes and what are they planning to do into a file",
              "`claims_history.jsonl`", "handoff emailed to the operator",
              "Any session resumes from the board", "`agent_claim.py status`", "another Claude Code session, Codex,"
              " Cursor or a cloud agent", "Handoff line of each worklog", "branch, worktree path and head SHA",
              "stale or abandoned and may be taken over", "`agent_claim.py takeover`",
              "taken over by <agent> at <time>", "never starts over", "Then Codex and Cursor actually did it")),
    ("28.3a", ("for every agent of every vendor", "Rule 11 points here", "`scripts/agent_claim.py status`",
               "`scripts/agent_claim.py next [--kind design|build|fix|review]`", "dependencies are done",
               "registers the claim and opens the worklog", "`scripts/agent_claim.py take <task-id>`", "`plan`, `done`,"
               " `note` and `blocker`", "`claim --add`", "a refusal means stop and pick another task", "`task done`",
               "`task release --handoff \"<next step>\"`", "`task add`", "depends_on", "acceptance", "`task split`",
               "look to see if there's any open design work out there")),
    ("28.3b", ("`DSN-<YYYYMMDD>-<slug>`", "`DSN-20261021-release-train`", "`DSN-…-P<n>`", "entry criteria",
               "durable artifact, §0 rule 8", "`PROPOSED` → `APPROVED` → `IN_PROGRESS` → `DONE`/`LIVE`, or `HELD`",
               "`DSN-…-P<n>-T<m>`", "the branch name, the PR title and the commit trailer `Design-Task: <id>`",
               "`docs/designs/<id>.md`", "YAML front matter", "Ops Work board", "Designs awaiting approval",
               "release train (phases 0–7)", "Gates 1–4", "Ask the CIO phases 8–11", "CIO integrator and prospect store",
               "§26 data domains", "operator's (§17); agents propose and stop", "No work without a task id",
               "as a warning; blocking it is left to a later version", "unique IDs that are actually tracked")),
    ("28.4", ("only when the operator gives it", "own session or tool", "relayed between agents", "never counts",
              "exact command", "never gives a placeholder", "`!` prefix")),
    ("28.5", ("One assertion, a bounded window", "default 60", "at most 120", "15 minutes idle",
              "End window now", "fresh assertion", "audited with the assertion that opened it",
              "`ops_controls.sudo_window_enabled`")),
    ("28.6", ("Three barriers", "`read_only`", "LOCKED", "`scripts/lib/trading_lock.py`",
              "`scripts/brokers/kill_switches.py`", "`live_submit`", "never re-opens order submission",
              "§17 acts", "passkey", "host terminal", "no agent, release, release train or n8n workflow",
              "a release that would change them is refused", "Reads continue")),
    ("28.7", ("These clause edits", "(1) In §0 rule 6", "(2) In §24.12", "(3) In §25.8", "(4) In §7",
              "(5) Stale references", "(6) In §27.3", "(7) In §27.4", "(8) In §17",
              "(9) In §0", "rule 11 directly after rule 10")),
])
def test_section_28_states_every_rule(sub, frags):
    text = _flat(_sub(_s28(), sub))
    for frag in frags:
        assert _flat(frag) in text, f"§{sub}: {frag!r}"


def test_every_section_28_bullet_cites_its_cause():
    bullets = re.split(r"\n(?=- \*\*)", _s28())[1:]
    assert len(bullets) >= 21, len(bullets)
    for b in bullets:
        assert "*Cause (§20):" in b, b[:120]


def _quoted(body: str) -> str:
    return "  ```\n" + "\n".join(("  " + line) if line else "" for line in body.rstrip("\n").split("\n")) + "\n  ```"


def test_section_28_7_quotes_every_clause_verbatim():
    s287 = _sub(_s28(), "28.7")
    for key, digest in CLAUSE_SHA256.items():
        if key == "C8_PAIRS":
            assert h("".join(o + n for o, n in C8_PAIRS)) == digest
            for o, n in C8_PAIRS:
                assert _quoted(o) in s287 and _quoted(n) in s287, "C8 pair not quoted verbatim"
            continue
        clause = globals()[key]
        assert h(clause) == digest, f"{key} digest"
        if key.endswith("_ANCHOR"):
            continue
        if key == "R8_ANCHOR":
            continue
        body = clause.lstrip("\n") if key == "R7_INS" else clause
        assert _quoted(body) in s287, f"{key} is not quoted verbatim in §28.7"


# ---------------------------------------------------------------------------------- byte-identical rails


@pytest.mark.parametrize("name", FIXED)
def test_fixed_sections_are_byte_identical(name):
    assert h(_section(AGENTS, name)) == SECTION_SHA256[name], f"{name} changed"


def test_changing_sections_differ_only_by_the_quoted_clauses_and_only_at_ratification():
    if not _ratified():
        for key in ("R0_INS", "R1_INS", "R2_INS", "R5_INS", "R6_NEW", "R7_INS", "R8_INS", "R8_INTRO_NEW"):
            assert globals()[key].strip("\n") not in AGENTS.replace(_s28(), ""), f"{key} in force before ratification"
        text = AGENTS
    else:
        text = undo_20_0_0(AGENTS)
    for name in CHANGING:
        assert h(_section(text, name)) == SECTION_SHA256[name], f"{name} changed beyond the quoted clauses"


def test_post_ratification_digests_are_pinned_in_advance():
    ratified = AGENTS if _ratified() else redo_20_0_0(AGENTS)
    for name in CHANGING:
        assert h(_section(ratified, name)) == SECTION_RATIFIED_SHA256[name], name
    assert undo_20_0_0(ratified) == pre_20_0_0(AGENTS)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_adapters_gain_the_rule_6_sentence_only_at_ratification(adapter):
    text = (ROOT / adapter).read_text(encoding="utf-8")
    assert text.count(R0_ANCHOR) == 1, f"{adapter} lost the 15.0.0 sentence"
    if not _ratified():
        assert R0_INS not in text and R8_INS not in text and h(text) == ADAPTER_SHA256[adapter], (
            f"{adapter} ahead of ratification")
    else:
        assert text.count(R0_ANCHOR + R0_INS) == 1, f"{adapter} paraphrases the 20.0.0 sentence"
        assert text.endswith(R8_ANCHOR + R8_INS) and R8_INTRO_NEW in text, f"{adapter} lacks rule 11 verbatim"
        assert h(text) == ADAPTER_RATIFIED_SHA256[adapter]
        assert h(pre_20_0_0_adapter(text)) == ADAPTER_SHA256[adapter]


# ---------------------------------------------------------------------------------------- code agrees


def test_code_named_in_section_28_exists():
    s28 = _s28()
    for path in ("scripts/process_reaper.py", "scripts/health_tick.py", "scripts/remediate_pipeline_failures.py",
                 "scripts/pipeline_watchdog.py", "scripts/lib/trading_lock.py", "scripts/brokers/kill_switches.py",
                 "tests/test_agents_policy_20_0_0_agent_operations.py"):
        assert (ROOT / path).exists(), path
        assert path in s28, path
