"""AGENTS.md PreToolUse guard hook for Claude Code (scripts/hooks/agents_guard_pretooluse.py).

Hermetic: HOME, TRADEAI_STATE_ROOT and GUARD_APPROVALS_DIR point into tmp_path; the real grant
ledger, persistent-state and ~/.claude are never touched. Rules come from the repo config.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "hooks" / "agents_guard_pretooluse.py"
RULES = REPO / "config" / "agents_guard_hook_rules.json"
SCRATCH = "/tmp/claude-1000/sess/scratchpad"


def _load():
    spec = importlib.util.spec_from_file_location("agents_guard_pretooluse", HOOK)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


hook = _load()


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    # HOME must sit outside every temp-allowlist glob (tmp_path is under /tmp/pytest-of-*, which is
    # allowlisted), so it is a path that is never created: the hook only does string math on it.
    home = Path("/nonexistent-agh-home") / tmp_path.name
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(tmp_path / "approvals"))
    monkeypatch.setenv("TRADEAI_AGENTS_GUARD_RULES", str(RULES))
    monkeypatch.setenv("TRADEAI_AGENTS_GUARD_MODE", "deny")
    return home


def _home() -> str:
    return os.environ["HOME"]


def _grant(tier: str, *, expires_in: int = 1800, uses: int = 5) -> None:
    d = Path(os.environ["GUARD_APPROVALS_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    p = d / "grants.json"
    doc = json.loads(p.read_text()) if p.exists() else {}
    doc[tier] = {"expires": int(time.time()) + expires_in, "uses": uses, "reason": "test"}
    p.write_text(json.dumps(doc))


def _run(tool: str = "Bash", cwd: str | None = None, **ti):
    payload = {
        "session_id": "sess-1",
        "cwd": cwd or f"{_home()}/tradeai-wt-test",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": ti,
        "transcript_path": "/dev/null",
    }
    return hook.run(json.dumps(payload))


def denied_rules(cmd: str | None = None, *, tool: str = "Bash", cwd: str | None = None, **ti) -> set[str]:
    if cmd is not None:
        ti["command"] = cmd
    out, records, _ = _run(tool, cwd, **ti)
    ids = {r["rule_id"] for r in records if r["would_deny"]}
    if ids:
        body = json.loads(out)
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    else:
        assert out == ""
    return ids


H = "~"  # expanded by the shell parser to $HOME (tmp)

# --------------------------------------------------------------------------- broker

BROKER_DENY = [
    ("curl -X POST https://api.schwabapi.com/trader/v1/accounts/ABC/orders -d @o.json", "broker.live_host_call"),
    ('bash -c "curl -s https://api.alpaca.markets/v2/orders"', "broker.live_host_call"),
    ("sudo -E env FOO=1 wget -qO- https://api.snaptrade.com/api/v1/trade", "broker.live_host_call"),
    ("python3 -c 'import requests; requests.post(\"https://api.schwabapi.com/trader/v1/x\")'", "broker.live_host_call"),
    ('python3 -c "from scripts.brokers import c; c.place_order(o)"', "broker.order_invoke"),
    (
        "python3 - <<'EOF'\nfrom alpaca.trading.client import TradingClient\nTradingClient().submit_order(o)\nEOF",
        "broker.order_invoke",
    ),
    (".venv/bin/python scripts/brokers/broker_entry_pilot.py --symbol X", "broker.order_invoke"),
    ("cd scripts && python3 -m brokers.options_order_pilot", None),  # module form is relative; see allow list
    ("BROKER_LIVE_ENABLED=1 python3 scripts/report.py", "broker.live_flag"),
    ("export TRADEAI_LIVE_ORDERS=true", "broker.live_flag"),
    ("cat config/broker_credentials.env", "broker.live_credential"),
    ('psql -c "select * from schwab_tokens"', "broker.live_credential"),
]


@pytest.mark.parametrize("cmd,rule", [c for c in BROKER_DENY if c[1]])
def test_broker_denies(cmd, rule):
    assert rule in denied_rules(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "curl -s https://paper-api.alpaca.markets/v2/account",
        "grep -rn api.schwabapi.com scripts/",
        "pytest -q tests/test_broker_entry_pilot.py",
        "ruff check scripts/brokers/broker_entry_pilot.py",
        "BROKER_LIVE_ENABLED=0 python3 scripts/report.py",
        "python3 -m scripts.brokers_report --dry-run",
    ],
)
def test_broker_allows(cmd):
    assert not {r for r in denied_rules(cmd) if r.startswith("broker.")}


def test_broker_execution_edit_needs_grant():
    p = f"{_home()}/tradeai-wt-x/scripts/brokers/order_intent.py"
    assert "broker.execution_code_edit" in denied_rules(tool="Edit", file_path=p, old_string="a", new_string="b")
    _grant("execution-engineering")
    out, records, _ = _run("Edit", None, file_path=p, old_string="a", new_string="b")
    assert out == ""
    assert [r["rule_action"] for r in records] == ["allowed_by_grant"]


def test_broker_execution_edit_via_sed_in_bash():
    assert "broker.execution_code_edit" in denied_rules("sed -i 's/a/b/' scripts/active_trader/session_control.py")


# --------------------------------------------------------------------------- delete


@pytest.mark.parametrize(
    "cmd,rule",
    [
        ("rm -rf ~/trade-ai-releases/archive/old-release", "delete.recursive_rm"),
        ("rm -fr data/runtime", "delete.recursive_rm"),
        ('rm -r -f "$DIR"', "delete.recursive_rm"),
        ("rm -rf /tmp/claude-1000/../../etc/x", "delete.recursive_rm"),
        ("sudo rm --recursive --force /var/lib/x", "delete.recursive_rm"),
        ("cd /tmp/claude-1000/x && cd ~/repo && rm -rf build2", "delete.recursive_rm"),
        ("find . -name '*.pyc' | xargs rm -rf", "delete.recursive_rm"),
        ('for d in a b; do rm -rf "$d"; done', "delete.recursive_rm"),
        ("find . -name '*.log' -delete", "delete.find_delete"),
        (r"find data -name x -exec rm {} \;", "delete.find_delete"),
        ("git clean -fdx", "delete.git_clean"),
        ("git -C ~/repo clean -f", "delete.git_clean"),
        ("shred -u notes.txt", "delete.shred_truncate"),
        ("truncate -s 0 data/runtime/x.jsonl", "delete.shred_truncate"),
        ('psql "$DSN" -c "DROP TABLE foo"', "delete.sql_destructive"),
        ("psql -c 'DELETE FROM holdings;'", "delete.sql_destructive"),
        ("psql trade_ai <<SQL\nTRUNCATE TABLE x;\nSQL", "delete.sql_destructive"),
        ("python3 -c \"cur.execute('DROP SCHEMA lab CASCADE')\"", "delete.sql_destructive"),
        ("docker volume rm m8m_n8n_data", "delete.docker_volume"),
        ("docker system prune -af", "delete.docker_volume"),
        ("docker compose -f lab.yml down -v", "delete.docker_volume"),
    ],
)
def test_delete_denies(cmd, rule):
    assert rule in denied_rules(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        f"rm -rf {SCRATCH}/build",
        "cd /tmp/claude-1000/x && rm -rf build",
        "rm -rf /tmp/pytest-of-u/pytest-1",
        "rm -rf ~/tradeai-wt-foo/node_modules ~/tradeai-wt-foo/frontend/dist",
        "rm -f single.txt",
        f"find {SCRATCH} -type f -delete",
        "git clean -n -d",
        f"truncate -s 0 {SCRATCH}/x.log",
        'psql -c "DELETE FROM t WHERE id = 3"',
        "grep -rn 'DROP TABLE' docs/",
        "docker volume ls",
        "echo '# rm -rf /' && ls",
    ],
)
def test_delete_allows(cmd):
    assert not {r for r in denied_rules(cmd) if r.startswith("delete.")}


def test_archive_expiry_exception_is_off_and_honoured_when_enabled(tmp_path, monkeypatch):
    doc = json.loads(RULES.read_text())
    assert doc["archive_expiry_exception"]["enabled"] is False
    assert "delete.recursive_rm" in denied_rules("rm -rf ~/trade-ai-releases/archive/r1")
    doc["archive_expiry_exception"]["enabled"] = True
    alt = tmp_path / "rules.json"
    alt.write_text(json.dumps(doc))
    monkeypatch.setenv("TRADEAI_AGENTS_GUARD_RULES", str(alt))
    assert "delete.recursive_rm" not in denied_rules("rm -rf ~/trade-ai-releases/archive/r1")


# --------------------------------------------------------------------------- remote routing


@pytest.mark.parametrize(
    "cmd,rule",
    [
        ("git push --no-verify -u origin feat/x", "remote.hook_bypass"),
        ("git commit -n -m wip", "remote.hook_bypass"),
        ("git -c core.hooksPath=/dev/null commit -m x", "remote.hook_bypass"),
        ("git config core.hooksPath /dev/null", "remote.hook_bypass"),
        ("TRADEAI_SKIP_SECRETS_SCAN=1 git push origin feat/x", "remote.hook_bypass"),
        ("export TRADEAI_SKIP_SECRETS_SCAN=1", "remote.hook_bypass"),
        ("chmod -x .githooks/pre-push", "remote.hook_bypass"),
        ("git push upstream feat/x", "remote.non_origin_push"),
        ("git push https://github.com/o/r.git HEAD:feat/x", "remote.non_origin_push"),
        ("git remote set-url origin git@example.com:o/r.git", "remote.non_origin_push"),
        ("git push origin HEAD:main", "remote.push_to_main"),
        ("git push --force origin main", "remote.push_to_main"),
        ("git push origin +feat/x:refs/heads/master", "remote.push_to_main"),
        ("gh api -X PUT repos/o/r/pulls/12/merge", "remote.gh_api_ref_write"),
        ("gh api repos/o/r/pulls/12/update-branch -X PUT", "remote.gh_api_ref_write"),
        ("gh api repos/o/r/git/refs/heads/main -X PATCH -f sha=abc", "remote.gh_api_ref_write"),
        ("gh api repos/o/r/branches/feat/rename -f new_name=feat2", "remote.gh_api_ref_write"),
        (
            "gh api graphql -f query='mutation { mergePullRequest(input:{}) { clientMutationId } }'",
            "remote.gh_api_ref_write",
        ),
        ("curl -X PUT https://api.github.com/repos/o/r/pulls/3/merge", "remote.gh_api_ref_write"),
        ("git branch -m old new", "remote.branch_rename"),
    ],
)
def test_remote_denies(cmd, rule):
    assert rule in denied_rules(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "git push -u origin feat/agents-guard-hook",
        "git push",
        "git push origin feat/main-fix",
        'git commit -m "fix the -n flag"',
        "gh api repos/o/r/git/refs/heads/main",
        "gh api repos/o/r/pulls/12",
        "git branch --show-current",
        "TRADEAI_SKIP_SECRETS_SCAN=0 git push origin feat/x",
        "git config --get core.hooksPath",
    ],
)
def test_remote_allows(cmd):
    assert not {r for r in denied_rules(cmd) if r.startswith("remote.")}


def test_pr_merge_is_log_only_even_in_deny_mode():
    out, records, _ = _run(command="gh pr merge 1555 --squash")
    assert out == ""
    assert [(r["rule_id"], r["would_deny"], r["denied"]) for r in records] == [("remote.pr_merge", False, False)]


def test_mcp_merge_tool_logged_not_denied():
    out, records, _ = _run("mcp__github__merge_pull_request", None, owner="o", repo="r", pullNumber=3)
    assert out == "" and records[0]["rule_id"] == "remote.pr_merge"


# --------------------------------------------------------------------------- secrets


@pytest.mark.parametrize(
    "cmd",
    [
        "cat .env",
        'cat ".env"',
        "cat /run/user/1000/tradeai/env",
        "grep TOKEN ~/.config/tradeai/agent-operator.env",
        "cat .env | grep KEY",
        "xxd < .env",
        "bash -c 'tail -n 3 ~/.config/tradeai/x.env'",
        "cut -d= -f2 .env",
        "echo $SCHWAB_API_KEY",
        "printenv FINVIZ_API_TOKEN",
        "bws secret get 0000-1111",
        "cat /proc/self/environ",
    ],
)
def test_secrets_denies(cmd):
    assert "secrets.read" in denied_rules(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "grep -o '^[A-Z_]*=' /run/user/1000/tradeai/env",
        "grep -oE '^[A-Z_][A-Z0-9_]*=' .env",
        "grep -c TOKEN .env",
        "cat .env.example",
        "cut -d= -f1 .env",
        'echo "${#SCHWAB_API_KEY}"',
        "printenv PATH",
        "set -a; . /run/user/1000/tradeai/env; set +a; python3 scripts/x.py",
        "ls -la ~/.config/tradeai",
    ],
)
def test_secrets_allows(cmd):
    assert not {r for r in denied_rules(cmd) if r.startswith("secrets.")}


def test_secrets_read_tool_and_write_tool():
    assert "secrets.read" in denied_rules(tool="Read", file_path=f"{_home()}/repo/.env")
    assert not denied_rules(tool="Read", file_path=f"{_home()}/repo/README.md")
    assert "secrets.write" in denied_rules(tool="Write", file_path=f"{_home()}/repo/config/x.env", content="A=1")
    assert not denied_rules(tool="Grep", path=f"{_home()}/repo/.env", pattern="A", output_mode="files_with_matches")


def test_env_dump_is_log_only():
    out, records, _ = _run(command="env")
    assert out == "" and records[0]["rule_id"] == "secrets.env_dump" and records[0]["would_deny"] is False


# --------------------------------------------------------------------------- live ops


@pytest.mark.parametrize(
    "cmd,rule,tier",
    [
        ("systemctl --user restart tradeai-cio-reactive.service", "liveops.service", "service"),
        ("sudo systemctl restart postgresql", "liveops.service", "service"),
        ("systemctl --user daemon-reload", "liveops.service", "service"),
        ("docker restart m8m-n8n", "liveops.service", "service"),
        ("docker compose up -d", "liveops.service", "service"),
        ("crontab -r", "liveops.cron", "cron"),
        ("crontab -e", "liveops.cron", "cron"),
        (f"crontab {SCRATCH}/cron.txt", "liveops.cron", "cron"),
        ("crontab -l | sed 's/a/b/' | crontab -", "liveops.cron", "cron"),
        ("bash scripts/cio_phase2_exact_main_deploy.sh promote", "liveops.deploy", "release-write"),
        ("TRADEAI_RELEASE_PR=1 scripts/cio_phase2_exact_main_deploy.sh prepare", "liveops.deploy", "release-write"),
    ],
)
def test_liveops_needs_grant(cmd, rule, tier):
    assert rule in denied_rules(cmd)
    _grant(tier)
    assert rule not in denied_rules(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "systemctl --user status tradeai-cio-reactive",
        "systemctl --user restart pipewire",
        "crontab -l",
        "docker ps",
        "docker restart scratch-test-container",
        "bash scripts/cio_phase2_exact_main_deploy.sh --help",
        "bin/guard show",
        "bin/guard request cron --reason 'PR #1 sha abc'",
    ],
)
def test_liveops_allows(cmd):
    assert not denied_rules(cmd)


def test_expired_or_used_grant_does_not_count():
    _grant("cron", expires_in=-5)
    assert "liveops.cron" in denied_rules("crontab -r")
    _grant("cron", uses=0)
    assert "liveops.cron" in denied_rules("crontab -r")
    _grant("cron", uses=-1)
    assert "liveops.cron" not in denied_rules("crontab -r")


def test_corrupt_ledger_counts_as_no_grant():
    d = Path(os.environ["GUARD_APPROVALS_DIR"])
    d.mkdir(parents=True)
    (d / "grants.json").write_text("{not json")
    _out, records, _ = _run(command="crontab -r")
    assert records[0]["grant_state"] == "ledger_unreadable" and records[0]["would_deny"]


def test_self_grant_and_ledger_write_denied():
    assert "liveops.self_grant" in denied_rules("bin/guard grant cron --for 30m --uses 1")
    assert "liveops.self_grant" in denied_rules(
        tool="Write", file_path=f"{_home()}/.cursor/approvals/grants.json", content="{}"
    )
    assert "liveops.self_grant" in denied_rules("echo '{}' > ~/.cursor/approvals/grants.json")


# --------------------------------------------------------------------------- governed paths


@pytest.mark.parametrize(
    "rel,tool",
    [
        ("trade-ai-releases/portfolio-server/abc-main/AGENTS.md", "Edit"),
        ("trade-ai-releases/CURRENT/config/data_source_authority.json", "Write"),
        ("trade-ai-releases/portfolio-server/abc/.github/workflows/ci.yml", "MultiEdit"),
        ("trade-ai-releases/persistent-state/config/guard_policy.json", "Write"),
    ],
)
def test_governed_served_edit_denied(rel, tool):
    assert "governed.served_edit" in denied_rules(tool=tool, file_path=f"{_home()}/{rel}", content="x")


def test_governed_allowed_in_worktree_and_non_governed_state():
    assert not denied_rules(tool="Edit", file_path=f"{_home()}/tradeai-wt-x/AGENTS.md", old_string="a", new_string="b")
    assert not denied_rules(
        tool="Write", file_path=f"{_home()}/trade-ai-releases/persistent-state/data/runtime/x.json", content="{}"
    )


def test_governed_bash_write_and_notebook():
    assert "governed.served_edit" in denied_rules("sed -i 's/a/b/' ~/trade-ai-releases/CURRENT/.githooks/pre-push")
    assert "governed.served_edit" in denied_rules(
        tool="NotebookEdit", notebook_path=f"{_home()}/trade-ai-releases/CURRENT/scripts/hooks/x.ipynb", new_source="x"
    )


def test_claude_settings_edit_denied():
    assert "governed.hook_config" in denied_rules(
        tool="Edit", file_path=f"{_home()}/.claude/settings.json", old_string="a", new_string="b"
    )
    assert "governed.hook_config" in denied_rules("cat x >> ~/.claude/settings.json")


# --------------------------------------------------------------------------- shell parsing edge cases


@pytest.mark.parametrize(
    "cmd,rule",
    [
        ("echo hi; rm -rf data", "delete.recursive_rm"),
        ("true && (cd data && rm -rf runtime)", "delete.recursive_rm"),
        ("x=$(rm -rf data/old)", "delete.recursive_rm"),
        ("nohup timeout 30 nice -n 5 rm -rf data &", "delete.recursive_rm"),
        ("eval 'git push origin HEAD:main'", "remote.push_to_main"),
        ("bash <<'EOF'\ncrontab -r\nEOF", "liveops.cron"),
        ("ssh -p 22 host 'rm -rf /srv/data'", "delete.recursive_rm"),
        ("flock /tmp/l -c 'crontab -r'", "liveops.cron"),
    ],
)
def test_parsing_edge_cases(cmd, rule):
    assert rule in denied_rules(cmd)


def test_mcp_shell_tool_is_analysed():
    assert "delete.recursive_rm" in denied_rules(tool="mcp__box__run_command", command="rm -rf data")


def test_benign_commands_produce_no_log(tmp_path):
    out, records, _ = _run(command="ls -la && git status && pytest -q tests/test_x.py | tail -3")
    assert out == "" and records == []


# --------------------------------------------------------------------------- modes, output, logging


def test_log_mode_never_denies(monkeypatch):
    monkeypatch.setenv("TRADEAI_AGENTS_GUARD_MODE", "log")
    for cmd in [
        "rm -rf data",
        "git push --no-verify origin main",
        "cat .env",
        "crontab -r",
        "curl https://api.schwabapi.com/trader/v1/accounts",
    ]:
        out, records, _ = _run(command=cmd)
        assert out == ""
        assert records and all(r["would_deny"] and not r["denied"] and r["mode"] == "log" for r in records)


def test_mode_resolution(monkeypatch):
    monkeypatch.delenv("TRADEAI_AGENTS_GUARD_MODE")
    assert hook.resolve_mode(json.loads(RULES.read_text())) == "log"  # shipped default
    assert hook.resolve_mode({"mode": "deny"}) == "deny"
    monkeypatch.setenv("TRADEAI_AGENTS_GUARD_MODE", "bogus")
    assert hook.resolve_mode({"mode": "deny"}) == "log"


def test_deny_output_shape():
    out, _records, _ = _run(command="rm -rf data")
    body = json.loads(out)
    assert set(body) == {"hookSpecificOutput"}
    hso = body["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse" and hso["permissionDecision"] == "deny"
    assert "delete.recursive_rm" in hso["permissionDecisionReason"] and "AGENTS.md" in hso["permissionDecisionReason"]


def test_log_record_is_redacted_and_hashed(tmp_path):
    secret = "Zq9" + "x7" * 15
    cmd = (
        f"FINVIZ_API_TOKEN={secret} curl -H 'Authorization: Bearer {secret}' https://api.alpaca.markets/v2/orders "
        + "a" * 400
    )
    _out, records, lpath = _run(command=cmd)
    hook.append_log(lpath, records)
    text = Path(lpath).read_text()
    assert secret not in text
    rec = json.loads(text.splitlines()[0])
    assert rec["schema"] == "AgentsGuardDecision@v1"
    assert len(rec["command_preview"]) <= 200
    assert len(rec["command_sha256"]) == 64
    assert {"ts", "session_id", "tool", "rule_id", "would_deny", "reason"} <= set(rec)
    assert lpath.startswith(os.environ["TRADEAI_STATE_ROOT"]) and lpath.endswith("data/runtime/agents_guard_hook.jsonl")


def test_redact_keeps_git_sha_masks_tokens():
    sha = "377e9b536" + "0" * 31
    assert sha in hook.redact(f"git show {sha}")
    assert "ghp_" not in hook.redact("gh auth login --with-token ghp_" + "A1b2" * 9)


def _subprocess(stdin: str, env_extra: dict | None = None, exe: str | None = None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        [exe or sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env, timeout=30
    )


def _log_lines() -> list[dict]:
    p = Path(os.environ["TRADEAI_STATE_ROOT"]) / "data" / "runtime" / "agents_guard_hook.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.mark.parametrize("stdin", ["{not json", "", "[1,2]", "null"])
def test_fail_open_on_bad_payload(stdin):
    cp = _subprocess(stdin)
    assert cp.returncode == 0 and cp.stdout == ""
    assert _log_lines()[-1]["rule_id"] == "hook.error"


def test_fail_open_when_rules_missing(tmp_path):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf data"}, "cwd": "/srv/agh"})
    cp = _subprocess(payload, {"TRADEAI_AGENTS_GUARD_RULES": str(tmp_path / "missing.json")})
    assert cp.returncode == 0 and cp.stdout == ""
    assert _log_lines()[-1]["rule_id"] == "hook.error"


def test_fail_open_when_log_unwritable(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf data"}, "cwd": "/srv/agh"})
    cp = _subprocess(payload, {"TRADEAI_STATE_ROOT": str(blocker)})
    assert cp.returncode == 0 and "deny" in cp.stdout  # still decides; logging failure is swallowed


def test_subprocess_deny_and_allow_with_system_python3():
    exe = shutil.which("python3") or sys.executable
    deny = _subprocess(
        json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD:main"}, "cwd": "/tmp/claude-1000/t"}
        ),
        exe=exe,
    )
    assert deny.returncode == 0 and json.loads(deny.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    allow = _subprocess(
        json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/tmp/claude-1000/t"}), exe=exe
    )
    assert allow.returncode == 0 and allow.stdout == ""


def test_performance_under_200ms():
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "cwd": "/tmp/claude-1000/t",
            "tool_input": {
                "command": "cd /tmp/claude-1000/x && bash -c 'git push --no-verify origin main' | tee out.log; " * 20
            },
        }
    )
    best = min(_timed(payload) for _ in range(5))
    assert best < 0.200, best
    t0 = time.perf_counter()
    for _ in range(50):
        hook.run(payload)
    assert (time.perf_counter() - t0) / 50 < 0.050


def _timed(payload: str) -> float:
    t0 = time.perf_counter()
    _subprocess(payload)
    return time.perf_counter() - t0


# --------------------------------------------------------------------------- the rules file


def test_rules_file_contract():
    doc = json.loads(RULES.read_text())
    assert doc["schema"] == "AgentsGuardHookRules@v1" and doc["version"]
    assert doc["mode"] == "log"
    ids = [r["id"] for r in doc["rules"]]
    assert len(ids) == len(set(ids))
    for r in doc["rules"]:
        assert "AGENTS.md" in r["section"], r["id"]
        assert r["action"] in ("deny", "log"), r["id"]
        assert r["reason"], r["id"]
    families = {r["family"] for r in doc["rules"]}
    assert {"broker", "delete", "remote", "secrets", "liveops", "governed"} <= families
    for path in (HOOK, RULES):
        assert ("/home/" + "johnclaw") not in path.read_text()


# --------------------------------------------------------------------------- regressions from the transcript replay (2026-10-09)


def test_shell_variable_resolves_to_scratch():
    assert not denied_rules(f'S={SCRATCH}; rm -rf "$S/wake-proof2"')
    assert "delete.recursive_rm" in denied_rules('S=data; rm -rf "$S/runtime"')


def test_heredoc_file_text_is_not_sql():
    assert not denied_rules("cat > notes.md <<'EOF'\nwe DROP SCHEMA x in psql\nEOF")
    assert not denied_rules('gh pr create --title t --body "guard against DROP SCHEMA via psql"')


def test_push_from_memory_repo_is_out_of_scope():
    cwd = f"{_home()}/.claude/projects/-x/memory"
    assert not denied_rules("git add -A && git commit -qm m && git push -q origin main", cwd=cwd)


def test_long_grep_pattern_is_linear_time():
    pat = "\\|".join(["MAX_CALLS_PER_PROCESS_" + str(i) for i in range(40)]) + "!"
    t0 = time.perf_counter()
    denied_rules(f'grep -on "{pat}" .env')
    assert time.perf_counter() - t0 < 0.05


# --------------------------------------------------------------------------- weekly report


def _report_mod():
    spec = importlib.util.spec_from_file_location(
        "report_agents_guard_hook", REPO / "scripts" / "report_agents_guard_hook.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_weekly_report_counts_and_false_positive_candidates(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADEAI_AGENTS_GUARD_MODE", "log")
    lpath = None
    for sess in ("a", "b", "c"):
        payload = {
            "session_id": sess,
            "tool_use_id": f"t-{sess}",
            "cwd": "/tmp/claude-1000/t",
            "tool_name": "Bash",
            "tool_input": {"command": "cat .env"},
        }
        _out, records, lpath = hook.run(json.dumps(payload))
        hook.append_log(lpath, records)
    _out, records, lpath = _run(command="gh pr merge 9 --squash")
    hook.append_log(lpath, records)
    with open(lpath, "a") as fh:
        fh.write("not json\n")
    rep = _report_mod()
    assert rep.main(["--log", lpath, "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["by_rule"]["secrets.read"]["would_deny"] == 3
    assert body["by_rule"]["remote.pr_merge"]["log"] == 1
    assert body["top_would_deny"][0]["count"] == 3
    fp = body["false_positive_candidates"][0]
    assert "secrets.read" in fp["rules"] and any("3 sessions" in w for w in fp["why"])
    assert body["unparseable_lines"] == 1
    assert rep.main(["--log", lpath]) == 0
    assert "secrets.read" in capsys.readouterr().out


def test_weekly_report_missing_log(tmp_path, capsys):
    rep = _report_mod()
    assert rep.main(["--log", str(tmp_path / "none.jsonl"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["records"] == 0


@pytest.mark.parametrize(
    "cmd",
    [
        "grep -n '^def \\|load_dotenv\\|\\.env' scripts/x.py",
        "cat ~/.config/tradeai/bin/run_poller.sh",
        "find . -name __pycache__ -type d -prune -exec rm -rf {} +",
        "find . -name '*.pyc' -delete",
        "rm -rf tests/lib/__pycache__ .pytest_cache",
        "bin/guard grant --help",
        "git -C ~/nyc-dof-auction push origin master",
        "git -c core.hooksPath=.githooks commit -qm x",
        'TMP=$(mktemp -d); rm -rf "$TMP"',
        f"S={SCRATCH}; R=$S/repo; rm -rf $R",
        "git push --force-with-lease=feat/x:$(git rev-parse --short origin/feat/x) origin feat/x",
        "ln -s ~/repo/.env .env",
        f"cp -p ~/.config/tradeai/bin/w.sh {SCRATCH}/w.env",
        "python3 - <<'EOF'\ns = open('t.py').read().replace('place_order(a)', 'place_order(b)')\nEOF",
    ],
)
def test_replay_false_positives_now_allowed(cmd):
    assert not denied_rules(cmd)


def test_unresolvable_cd_makes_relative_targets_unknown():
    assert "delete.recursive_rm" in denied_rules('cd "$WT" && rm -rf build')
