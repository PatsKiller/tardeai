"""AGENTS.md 7.0.0 (PROPOSED, MAJOR) — §23.20 advisory market-data lanes on the n8n dispatcher.

Operator 2026-10-14: "move to n8n i approve if i need to make amendment propose its just looking at level 2 on moomoo
no trading". Pins, all hermetic (source parsing and pure functions; nothing imports or runs a lane):

* the policy record: header 7.0.0 PROPOSED / PENDING, one version row awaiting APPROVE_AGENTS_POLICY_7_0_0, the
  banner, §23.20 and the §23.3 exception bullet; §0, §2, §2A, §7A, §17 and §23.14 byte-identical to the digests the
  4.6.0 … 5.2.0 pins hold; lane_dispatch.ADVISORY_MD_STATUS agrees with the row;
* condition (a) — scripts/lib/advisory_lane_guard.py finds trade contexts, order verbs, account reads and broker client
  modules in a lane's reach, follows imports at definition granularity and spawned child scripts, and lets a quote
  context through; condition (c) — direct sends and bypass_router sites; condition (b) — submit switches;
* the real lanes: active-trader-premarket-watch passes (a)/(c); finviz-momentum-scalp-early-lane and
  momentum-scalp-advisory-alerts fail (a) (account reads through auto_proposal_generator → account_policy);
* advisory_md_admission refuses while PROPOSED, outside the ceiling, on a wrong class, a submit switch, a broker env
  name or a lock that is not the cron lock; admits the premarket shape once ACTIVE;
* the dispatcher sender gate: every dispatched allowlist lane whose reach sends or touches a broker client module is
  trade-ai-scalp-live, a §23.20 lane, or in the shrink-only BASELINE below.
"""
from __future__ import annotations

import functools
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
from scripts.lib import advisory_lane_guard as G  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from tests.test_agents_policy_5_2_0_validation import (  # noqa: E402
    CLAUSE_23_14_16_0_0,
    CLAUSE_23_14_PRE_16_0_0,
    PINNED_SECTIONS,
    SECTION_23_14_SHA256,
    _section,
)

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_7_0_0"
REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
PREMARKET = "scripts/active_trader/premarket_watch.py"

#: Dispatched allowlist lanes whose static reach sends or touches a broker client module, measured 2026-10-14 on
#: origin/main 8ae8a5b91. SHRINK-ONLY: each is a finding (fix the reach or drop the lane from its wave); a lane not
#: listed here, not trade-ai-scalp-live and not a §23.20 lane fails.
BASELINE = {
    "finviz-health-check": "sends (finviz_health_check.py send_telegram)",
    "crawl-v3-dashboard": "sends (crawl_v3_dashboard.py send_telegram)",
    "audit-enrichment-coverage": "sends (--alert path, send_telegram)",
    "watchlist-enrichment-sweep": "broker module schwab_transport in reach",
    "journal-tilt-morning-hook": "sends (momentum_alerts) + schwab_transport in reach",
    "catalyst-momentum-engine-overnight": "advisory send + account_policy account reads in reach",
    "aegis-evening-packet": "sends + api_v2 order verbs in reach",
    # n8nmat/scalp-premarket-onboard-20261014 (W5 shadow): the --hot-list-only path returns before any handoff, but
    # the entry script it shares with the */5 early lane statically reaches auto_proposal_generator (advisory send,
    # account_policy reads). Fix: give the hot-list owner its own entry script (cron + allowlist change, cron grant).
    "scalp-hot-list": "shared entry script reaches the early-lane proposal handoff (path-insensitive scan)",
}
NAMED_SENDER_EXCEPTIONS = frozenset({"trade-ai-scalp-live"})


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _row() -> re.Match:
    m = re.search(r"^\| 7\.0\.0 \| 2026-10-14 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 7.0.0 | 2026-10-14 | PROPOSED|ACTIVE | MAJOR |` row"
    return m


def _s2320() -> str:
    m = re.search(r"^## 23\.20 .*?(?=^---$)", AGENTS, re.M | re.S)
    assert m
    return _flat(m.group(0))


# ------------------------------------------------------------------------------------------------ the record


def test_header_row_and_status_constant_agree():
    # 11.0.0 (ratified 2026-10-15, #1747 comment) moved the header date; 7.0.0 and 10.0.0 were 2026-10-14;
    # 14.0.0 (ratified 2026-10-16, #1838 comment) and 15.0.0 (ratified 2026-10-21, #1852 comment) moved it again.
    # 16.0.0 (PROPOSED 2026-10-21) sets the header block to 16.0.0 PROPOSED, Effective-Date PENDING, until ratified;
    # ratified 2026-10-21 (#1911 comment 6331278599, 22:33 ET) with Effective-Date 2026-10-21, already listed.
    later_proposed = (tuple(int(x) for x in _control("Policy-Version").split(".")) >= (16, 0, 0)
                      and _control("Status") == "PROPOSED" and _control("Effective-Date") == "PENDING")
    # 18.0.0 (PROPOSED 2026-10-22) takes the ratification day as its Effective-Date, which is not known in advance:
    # any ISO date on or after 2026-10-22 once 18.0.0 or later is ACTIVE.
    later_active = (tuple(int(x) for x in _control("Policy-Version").split(".")) >= (18, 0, 0)
                    and _control("Status") == "ACTIVE"
                    and re.fullmatch(r"\d{4}-\d{2}-\d{2}", _control("Effective-Date") or "") is not None
                    and _control("Effective-Date") >= "2026-10-22")
    assert later_proposed or later_active or (_control("Status") == "ACTIVE" and _control("Effective-Date") in (
        "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-21"))
    status = _row().group(1)
    if _control("Policy-Version") == "7.0.0":
        assert _control("Status") == status and _control("Supersedes") == "5.1.0"
        if status == "PROPOSED":
            assert _control("Effective-Date") == "PENDING"
    assert LD.ADVISORY_MD_POLICY_VERSION == "7.0.0"
    assert LD.ADVISORY_MD_STATUS == status, "only the ratifying edit flips ADVISORY_MD_STATUS"


def test_row_waits_for_the_operator_and_names_the_enforcement():
    status, rest = _row().groups()
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I)
    else:  # ratified 2026-10-14: PR #1725 comment by PatsKiller 2026-10-14T14:54:21Z
        assert re.search(rf"{TOKEN} 1725 73eebc5c1", rest), "ACTIVE 7.0.0 row must record token, PR and sha"
        assert "2026-10-14T14:54:21Z" in rest and "merged #1725 as" in rest
    for frag in ("Operator-directed 2026-10-14", "§23.20", "advisory_lane_guard.py",
                 "tests/test_agents_policy_7_0_0_advisory_market_data.py", "§23.14 byte-identical"):
        assert frag in rest, frag


def test_banner_section_and_23_3_bullet():
    banner = _flat(AGENTS[AGENTS.index("**7.0.0 is "): AGENTS.index("**5.2.0 is ")])
    for frag in ("ACTIVE (MAJOR)", "Ratified by the operator 2026-10-14", f"{TOKEN} 1725 73eebc5c1", "Why MAJOR", "level 2 on moomoo no trading", "ADVISORY_MD_STATUS",
                 "not by analogy", f"{TOKEN} <pr_number> <head_sha>", "Supersedes` is the last ACTIVE version, 5.1.0"):
        assert frag in banner, frag
    sec = _s2320()
    for frag in ("(a) Market data only", "(b) Advisory writes only", "(c) Sends go through the host chokepoint",
                 "(d) No secret travels through n8n", "ADVISORY_MARKET_DATA_LANES", "--submit-validation",
                 "MOMENTUM_SCALP_VALIDATION_SUBMIT", "bypass_router=True", "execution-engineering",
                 "build_child_env", "shrink-only baseline", "§23.14 is unchanged"):
        assert frag in sec, frag
    s233 = AGENTS[AGENTS.index("## 23.3 "): AGENTS.index("## 23.4 ")]
    assert "**Exception (7.0.0) — §23.20 advisory market-data lanes.**" in s233
    assert "It is the second and last class that may" in _flat(s233)
    assert "Second exception class (AGENTS.md 7.0.0 §23.20, ACTIVE: APPROVE_AGENTS_POLICY_7_0_0 1725 73eebc5c1)" in ALLOW["never"]
    assert "Sole exception: trade-ai-scalp-live" in ALLOW["never"]


def test_state_checker_passes_on_branch_and_on_main():
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_rails_and_23_14_are_byte_identical():
    for name, (start, end, digest) in PINNED_SECTIONS.items():
        block = _section(AGENTS, start, end)
        assert hashlib.sha256(block.encode("utf-8")).hexdigest() == digest, f"{name} changed"
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", AGENTS, re.M | re.S).group(0)
    m = re.search(r"^## 23\.14 .*?(?=^## |^---$|^# |\Z)", sec, re.M | re.S)
    block = m.group(0).rstrip("\n").rstrip("-").rstrip("\n").replace(CLAUSE_23_14_16_0_0, CLAUSE_23_14_PRE_16_0_0)  # 16.0.0 clause (2)
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == SECTION_23_14_SHA256


# ------------------------------------------------------------------------------------- the guard on fixtures


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_quote_context_and_l2_subscriptions_are_market_data(tmp_path):
    d = _write(tmp_path, {"lane_q.py": (
        "from futu import OpenQuoteContext, SubType\n"
        "def run():\n    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)\n"
        "    ctx.subscribe(['US.AAPL'], [SubType.ORDER_BOOK, SubType.TICKER])\n"
        "    return ctx.get_order_book('US.AAPL'), ctx.get_rt_ticker('US.AAPL')\n")})
    rep = G.scan_entry(str(d / "lane_q.py"))
    assert rep.market_data_only() and not rep.is_sender and rep.problems() == []


@pytest.mark.parametrize("body,kind", [
    ("from futu import OpenSecTradeContext\nctx = OpenSecTradeContext()\n", "trade_context"),
    ("import futu\nctx = futu.OpenUSTradeContext()\n", "trade_context"),
    ("def f(ctx):\n    ctx.unlock_trade('pw')\n", "trade_context"),
    ("def f(ctx):\n    ctx.place_order(1, 1, 'US.X')\n", "trade_context"),
    ("def f(ctx):\n    ctx.position_list_query()\n", "account_reads"),
    ("def f(api):\n    return api.get_account()\n", "account_reads"),
    ("from alpaca_paper_adapter import AlpacaPaperAdapter\n", "broker_modules"),
    ("import schwab_transport\n", "broker_modules"),
    ("URL = 'https://api.telegram.org/bot%s/sendMessage'\n", "direct_sends"),
    ("import smtplib\n", "direct_sends"),
])
def test_condition_a_and_c_violations_are_found(tmp_path, body, kind):
    d = _write(tmp_path, {"lane_bad.py": body})
    rep = G.scan_entry(str(d / "lane_bad.py"))
    assert getattr(rep, kind), (kind, rep)
    assert rep.problems()


def test_imports_follow_definitions_not_whole_modules(tmp_path):
    d = _write(tmp_path, {
        "fxmod_md.py": ("from futu import OpenQuoteContext\n"
                        "class Quote:\n    def ctx(self):\n        return OpenQuoteContext()\n"
                        "class Account:\n    def ctx(self):\n        from futu import OpenSecTradeContext\n"
                        "        return OpenSecTradeContext().accinfo_query()\n"),
        "lane_uses_quote.py": "from fxmod_md import Quote\nQuote().ctx()\n",
        "lane_uses_account.py": "from fxmod_md import Account\nAccount().ctx()\n",
        "lane_imports_module.py": "import fxmod_md\n",
    })
    assert G.scan_entry(str(d / "lane_uses_quote.py")).market_data_only()
    assert not G.scan_entry(str(d / "lane_uses_account.py")).market_data_only()
    assert not G.scan_entry(str(d / "lane_imports_module.py")).market_data_only()


def test_spawned_child_scripts_are_in_reach_but_docstrings_are_not(tmp_path):
    d = _write(tmp_path, {
        "fxchild_sub.py": "def go(api):\n    api.get_account()\n",
        "lane_spawns.py": "import subprocess, sys\nsubprocess.run([sys.executable, 'fxchild_sub.py'])\n",
        "lane_mentions.py": '"""Runs like fxchild_sub.py does."""\nprint("see fxchild_sub.py")\n',
    })
    assert G.scan_entry(str(d / "lane_spawns.py")).account_reads
    assert not G.scan_entry(str(d / "lane_mentions.py")).account_reads


#: 2026-10-21 (#1417 rebuild review): a `/ "x.py"` path join that is provably only READ is not a spawned child;
#: every use that could run, import or hand the path on stays a spawn (scripts/lib/advisory_lane_guard.py
#: _read_only_path_literals). The child below reads an account, so "in reach" == account_reads non-empty.
_READ_ONLY = {
    "direct_read_text": "def f(root):\n    return len((root / 'fxchild_sub.py').read_text())\n",
    "direct_exists_stat": "def f(root):\n    return (root / 'fxchild_sub.py').exists() and (root / 'fxchild_sub.py').stat()\n",
    "open_read_mode": "def f(root):\n    with open(root / 'fxchild_sub.py', 'r') as fh:\n        return len(fh.read())\n",
    "path_open_rb": "def f(root):\n    with (root / 'fxchild_sub.py').open('rb') as fh:\n        return len(fh.read())\n",
    # the shape of cio_operator_investment_policy.discover_legacy_policy_claims: alias read + a label helper
    "alias_read_and_label_helper": (
        "import re\n"
        "def _label(path, root):\n    try:\n        return str(path.relative_to(root))\n"
        "    except ValueError:\n        return path.name\n"
        "def f(root):\n    p = root / 'scripts' / 'fxchild_sub.py'\n    try:\n        t = p.read_text(encoding='utf-8')\n"
        "    except OSError:\n        t = ''\n    m = re.search(r'x', t)\n    return {'source': _label(p, root), 'm': bool(m)}\n"),
}
_STILL_SPAWN = {
    "subprocess_of_literal": "import subprocess, sys\ndef f(root):\n    subprocess.run([sys.executable, root / 'fxchild_sub.py'])\n",
    "alias_then_subprocess": ("import subprocess, sys\ndef f(root):\n    p = root / 'fxchild_sub.py'\n"
                              "    subprocess.run([sys.executable, str(p)])\n"),
    "alias_then_from_import_run": ("from subprocess import run as go\nimport sys\ndef f(root):\n"
                                   "    p = root / 'fxchild_sub.py'\n    go([sys.executable, p])\n"),
    "read_in_a_spawning_function": ("import subprocess\ndef f(root):\n    p = root / 'fxchild_sub.py'\n    p.read_text()\n"
                                    "    subprocess.run(['true'])\n"),
    "exec_of_read_text": "def f(root):\n    exec((root / 'fxchild_sub.py').read_text())\n",
    "runpy": "import runpy\ndef f(root):\n    runpy.run_path(str(root / 'fxchild_sub.py'))\n",
    "importlib_by_path": ("import importlib.util\ndef f(root):\n"
                          "    return importlib.util.spec_from_file_location('m', root / 'fxchild_sub.py')\n"),
    "open_write_mode": "def f(root):\n    open(root / 'fxchild_sub.py', 'w')\n",
    "module_level_read": "from pathlib import Path\nTEXT = (Path('.') / 'fxchild_sub.py').read_text()\n",
    "alias_to_unknown_callee": "import shlex\ndef f(root):\n    p = root / 'fxchild_sub.py'\n    return shlex.quote(str(p))\n",
    "alias_to_spawning_helper": ("import subprocess, sys\ndef _go(path):\n    subprocess.run([sys.executable, str(path)])\n"
                                 "def f(root):\n    p = root / 'fxchild_sub.py'\n    _go(p)\n"),
    "alias_reassigned": "def f(root):\n    p = root / 'fxchild_sub.py'\n    p.read_text()\n    q = p\n    return q\n",
    "alias_in_fstring": "def f(root):\n    p = root / 'fxchild_sub.py'\n    p.read_text()\n    return f'{p}'\n",
    "global_alias": ("P = None\ndef f(root):\n    global P\n    P = root / 'fxchild_sub.py'\n    P.read_text()\n"),
}
_CHILD = {"fxchild_sub.py": "def go(api):\n    api.get_account()\n"}


@pytest.mark.parametrize("case", sorted(_READ_ONLY))
def test_read_only_path_literal_is_not_a_spawn(tmp_path, case):
    d = _write(tmp_path, {**_CHILD, "lane_reads.py": _READ_ONLY[case]})
    (d / "scripts").mkdir(exist_ok=True)
    (d / "scripts" / "fxchild_sub.py").write_text(_CHILD["fxchild_sub.py"])
    assert not G.scan_entry(str(d / "lane_reads.py")).account_reads, case


@pytest.mark.parametrize("case", sorted(_STILL_SPAWN))
def test_run_import_or_handed_on_path_literal_stays_a_spawn(tmp_path, case):
    d = _write(tmp_path, {**_CHILD, "lane_spawns_path.py": _STILL_SPAWN[case]})
    assert G.scan_entry(str(d / "lane_spawns_path.py")).account_reads, case


def test_the_policy_library_text_read_is_not_a_spawn_and_was_not_rewritten():
    src = (ROOT / "scripts" / "lib" / "cio_operator_investment_policy.py").read_text(encoding="utf-8")
    assert 'decision_path = repo_root / "scripts" / "lib" / "cio_decision_quality.py"' in src
    rep = G.scan_entry("scripts/lib/cio_operator_investment_policy.py")
    assert "scripts/lib/cio_decision_quality.py" not in rep.scanned and not rep.is_sender and not rep.problems()


def test_sends_through_the_chokepoint_and_bypass_sites(tmp_path):
    d = _write(tmp_path, {"lane_send.py": (
        "from telegram_alert import send_telegram\n"
        "def alert(t):\n    send_telegram(t, bypass_router=True)\n    send_telegram(t, bypass_router=False)\n")})
    rep = G.scan_entry(str(d / "lane_send.py"))
    assert rep.is_sender and not rep.direct_sends and len(rep.bypass_router) == 1


def test_submit_switches():
    assert G.submit_tokens(["$PY", "x.py", "--submit-validation"]) == ["--submit-validation"]
    assert G.submit_tokens(["env", "MOMENTUM_SCALP_VALIDATION_SUBMIT=1", "$PY", "x.py"])
    assert G.submit_tokens(["env", "MOMENTUM_SCALP_PAPER_FAST_PATH=1"])
    assert G.submit_tokens([], {"MOMENTUM_SCALP_VALIDATION_SUBMIT": "1"})
    assert G.submit_tokens(["env", "MOMENTUM_SCALP_VALIDATION_SUBMIT=0", "$PY", "x.py", "--apply"]) == []
    assert G.submit_tokens(["$PY", "scripts/run_finviz_momentum_scalp_scan.py", "--run-validation-fast-path"]) == []


# ---------------------------------------------------------------------------------------------- the real lanes


def test_premarket_watch_is_market_data_only_and_sends_through_the_chokepoint():
    rep = G.scan_entry(PREMARKET)
    assert rep.market_data_only(), rep.problems()
    assert rep.is_sender and not rep.direct_sends
    assert {s.rsplit(":", 1)[0] for s in rep.bypass_router} <= LD.ADVISORY_MD_BYPASS_FILES
    assert any("moomoo/client.py:FutuTransport" in s for s in rep.scanned)
    assert not any("MoomooReadOnlyAccount" in s for s in rep.scanned)


@pytest.mark.parametrize("script", ["scripts/run_finviz_momentum_scalp_scan.py", "scripts/auto_proposal_generator.py"])
def test_proposal_lanes_fail_condition_a_through_the_equity_read(script):
    rep = G.scan_entry(script)
    assert not rep.market_data_only()
    assert any("account_policy.py" in x for x in rep.account_reads)


def test_bypass_files_are_on_the_5_1_0_allowlist():
    from tests.test_notification_intents_20261010 import BYPASS_ALLOWLIST

    assert LD.ADVISORY_MD_BYPASS_FILES <= set(BYPASS_ALLOWLIST)


# ----------------------------------------------------------------------------------------------- admission


def _premarket_row(**sched):
    return {
        "lane_id": "active-trader-premarket-watch",
        "scheduler": {"kind": "cron", "expression": "*/5 6-9 * * 1-5", "stage": "shadow", "wave": "W5",
                      "match": "scripts/active_trader/premarket_watch.py",
                      "command_text": ("cd $PROJ && flock -n /tmp/at_premarket.lock timeout 240 $PY "
                                       "scripts/active_trader/premarket_watch.py --apply >> logs/at_premarket_watch.log 2>&1"),
                      **sched},
        "state": "ACTIVE", "recommendation": "KEEP_ON_CRON",
        "rationalization": {"recommendation": "KEEP_ON_CRON"},
        "dispatch": {"mode": "dry_run", "cron": ["*/5 6-9 * * 1-5"], "tz": "America/New_York", "wave": "W5",
                     "class": "pipeline", "priority": 1, "retry_policy": "none"},
    }


ENTRY = {"lane_id": "active-trader-premarket-watch", "command": ["$PY", PREMARKET], "lock": "/tmp/at_premarket.lock",
         "lock_kind": "flock", "timeout_s": 240, "dry_run_arg": [], "live_arg": None, "market_gate": False,
         "env_names": ["DB_HOST", "DB_NAME"]}


def _admit(row, entry, status="ACTIVE"):
    return LD.advisory_md_admission(row, entry, status=status)


def test_admission_refuses_while_proposed_and_admits_once_active():
    entry = dict(ENTRY, dry_run_arg=["--symbols", "AAPL"])
    assert _admit(_premarket_row(), entry, "PROPOSED")[0] is False
    assert _admit(_premarket_row(), entry) == (True, "advisory_md_admitted")
    if LD.ADVISORY_MD_STATUS == "PROPOSED":
        assert LD.dispatch_eligible(_premarket_row()) == (False, "keep_on_cron")
    else:  # ACTIVE: the ceiling lane's KEEP_ON_CRON verdict is lifted by name; any other lane keeps it
        assert LD.dispatch_eligible(_premarket_row()) == (True, "eligible")
        assert LD.dispatch_eligible(dict(_premarket_row(), lane_id="not-in-ceiling")) == (False, "keep_on_cron")


@pytest.mark.parametrize("mutate,why", [
    (lambda r, e: r.update(lane_id="some-other-lane"), "advisory_md_not_in_ceiling"),
    (lambda r, e: r["dispatch"].update({"class": "send"}), "advisory_md_class"),
    (lambda r, e: r["dispatch"].update({"class": "ingest"}), "advisory_md_class"),
    (lambda r, e: e.update(live_arg=["--apply", "--submit-validation"]), "submit"),
    (lambda r, e: e.update(command=["env", "MOMENTUM_SCALP_VALIDATION_SUBMIT=1", "$PY", PREMARKET]), "advisory_md_submit"),
    (lambda r, e: e.update(env_names=["SCHWAB_APP_KEY"]), "broker_credential_env"),
    (lambda r, e: e.update(lock="/tmp/other.lock"), "advisory_md_lock_mismatch"),
    (lambda r, e: e.update(lock_kind="safe_flock"), "advisory_md_lock_kind"),
    (lambda r, e: e.update(dry_run_arg=None), "no_dry_run_arg"),
    (lambda r, e: e.update(dry_run_arg=[], command=["$PY", PREMARKET, "--apply"]), "no_dry_run_arg"),
    (lambda r, e: e.update(dry_run_arg=[], live_arg=["--apply", "--symbols", "X"]), "no_dry_run_arg"),
    (lambda r, e: (e.update(dry_run_arg=[]), r["scheduler"].update(command_text=r["scheduler"]["command_text"]
                   .replace(" --apply", ""))), "no_dry_run_arg"),
])
def test_admission_refusals(mutate, why):
    row, entry = _premarket_row(), dict(ENTRY, dry_run_arg=["--symbols", "AAPL"])
    mutate(row, entry)
    ok, reason = _admit(row, entry)
    assert ok is False and why in reason, reason


def test_bare_command_is_the_dry_run_only_under_an_explicit_cron_apply():
    entry = dict(ENTRY, dry_run_arg=[], live_arg=["--apply"])
    assert _admit(_premarket_row(), entry) == (True, "advisory_md_admitted")


def test_r1_class_admission_routes_ceiling_lanes_to_the_advisory_gate():
    entry = dict(ENTRY, dry_run_arg=["--symbols", "AAPL"])
    ok, why = LD.r1_class_admission(_premarket_row(), entry)
    assert (ok, why.startswith("advisory_md")) == (LD.ADVISORY_MD_STATUS == "ACTIVE", True)


def test_static_errors_for_the_three_ceiling_lanes():
    pm = dict(ENTRY, dry_run_arg=["--symbols", "AAPL"])
    assert LD.advisory_md_static_errors(_premarket_row(), pm) == []
    early = dict(ENTRY, lane_id="finviz-momentum-scalp-early-lane",
                 command=["$PY", "scripts/run_finviz_momentum_scalp_scan.py", "--window", "early"])
    errs = LD.advisory_md_static_errors(dict(_premarket_row(), lane_id=early["lane_id"]), early)
    assert any("account_read" in e for e in errs) and any("broker_module" in e for e in errs)


# --------------------------------------------------------------------------- the dispatcher sender gate (gap fix)


@functools.lru_cache(maxsize=1)
def _dispatched_reach():
    entries = {e["lane_id"]: e for e in ALLOW["lanes"]}
    out = {}
    for row in REGISTRY["lanes"]:
        if LD.dispatch_mode(row) == "off" or row["lane_id"] not in entries:
            continue
        script = G.entry_script(entries[row["lane_id"]]["command"])
        if script:
            out[row["lane_id"]] = G.scan_entry(script)
    return out


def test_no_dispatched_lane_sends_or_reaches_a_broker_outside_the_named_classes():
    bad = {lane: (rep.sends[:2] + rep.problems()[:2]) for lane, rep in _dispatched_reach().items()
           if (rep.is_sender or rep.broker_modules or rep.trade_context or rep.account_reads)
           and lane not in NAMED_SENDER_EXCEPTIONS and lane not in LD.ADVISORY_MARKET_DATA_LANES
           and lane not in BASELINE}
    assert not bad, f"dispatched lane reaches a sender or broker outside §23.3/§23.20 and the baseline: {bad}"


def test_baseline_is_shrink_only():
    reach = _dispatched_reach()
    stale = [lane for lane in BASELINE
             if lane not in reach or not (reach[lane].is_sender or reach[lane].problems())]
    assert not stale, f"remove fixed or undispatched lanes from BASELINE: {stale}"
