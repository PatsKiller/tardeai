"""LQ-20261107-1258: the self-heal fixer runs on DeepSeek, and an incomplete provider block REFUSES the cycle.

Operator 2026-11-08: "self-heal must use the free/cheap APIs, not Anthropic." Before this row
``config/self_heal_fixer.json`` had no ``claude.provider``, so every cycle ran the Claude Code CLI on the
operator's Anthropic subscription (the 16:21 cycle reported $3.72 notional for 3 failed jobs). The provider
plumbing (launcher, key-on-stdin, egress, auth_mode) landed on 2026-11-03; what was missing was the block itself
and a REFUSAL for the case that used to fail open: a block that is named but cannot run used to keep the CLI's own
OAuth login silently. That is the one outcome the operator ruled out.

Every test here is synthetic: a fake key file, a synthetic ``HOME``, no network, no real key read, no model call.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import self_heal_fixer as FX  # noqa: E402
from lib import self_heal_fixer as F  # noqa: E402

LIVE_CONFIG = ROOT / "config" / "self_heal_fixer.json"
#: The fixed clock of every refusal test: a refusal carries a timestamp, and a wall clock would change the receipt.
NOW = datetime(2026, 11, 8, 22, 0, tzinfo=timezone.utc)
#: Anything token-shaped in a config value: the provider block may name a PATH, never key material.
TOKEN_SHAPED = re.compile(r"\b(sk|ghp|xox[bp])[-_][A-Za-z0-9]{8,}")


def _live() -> dict:
    return json.loads(LIVE_CONFIG.read_text(encoding="utf-8"))


def _synthetic_home(tmp_path: Path, *, key: bool = True) -> dict:
    """A HOME whose only content is an optional FAKE key file at the configured path."""
    home = tmp_path / "home"
    (home / ".config" / "tradeai").mkdir(parents=True, exist_ok=True)
    if key:
        (home / ".config" / "tradeai" / "deepseek_api_key").write_text("proof-fake-not-a-key\n", encoding="utf-8")
    return {"HOME": str(home), "PATH": "/usr/bin:/bin"}


def _attempt(tmp_path: Path, provider: dict):
    cfg = {
        "repo": {"repo_root": str(tmp_path / "repo"), "python": sys.executable,
                 "worktree_root": str(tmp_path / "wt"), "branch_prefix": "shf/"},
        "claude": {"bin": str(tmp_path / "claude"), "timeout_s": 5, "provider": provider,
                   "env_names": ["HOME", "PATH"], "auth": {"mode": "credentials_file"}},
        "agent_sandbox": {"enabled": False, "egress_allow": ["api.anthropic.com:443"]},
    }
    return FX.Attempt({"job_id": "shf-test", "lane": "test", "signature": "sig-0123456789"},
                      {"base_sha": "0" * 40}, cfg=cfg, environ={"HOME": str(tmp_path)},
                      now=lambda: NOW, evidence_dir=tmp_path, may_push=False, backend="claude_code")


# ---------------------------------------------------------------- the config itself
def test_the_live_config_runs_on_deepseek_and_binds_no_oauth_credential(tmp_path):
    """The operator's requirement as a property of the shipped config, not of a copy."""
    cfg = _live()
    env = _synthetic_home(tmp_path)
    state = FX.provider_block_state(cfg, env)
    assert state["state"] == FX.PROVIDER_ACTIVE, state
    assert state["name"] == "deepseek" and state["reason"] == "provider_active", state
    assert state["auth_mode"] == "none", "a DeepSeek run must bind no Anthropic credential"
    assert state["egress_allow"] == ["api.deepseek.com:443"], state["egress_allow"]
    assert state["launcher"].endswith("scripts/lib/self_heal_deepseek_launch.py"), state["launcher"]
    assert Path(state["launcher"]).is_file(), f"the launcher the config names does not exist: {state['launcher']}"
    assert state["launcher_readable"] is True
    assert state["key_file"] == str(Path(env["HOME"]) / ".config" / "tradeai" / "deepseek_api_key"), state
    assert state["key_readable"] is True
    # a PATH reference, never key material (the fake key above is not in the config)
    assert TOKEN_SHAPED.search(json.dumps(cfg["claude"]["provider"])) is None, "provider block holds a token"

    egress, auth_cfg = FX.provider_plan_view(cfg, env)
    assert "api.deepseek.com:443" in egress, egress
    assert auth_cfg["claude"]["auth"]["mode"] == "none", auth_cfg["claude"]["auth"]
    binds, why = F.agent_auth_binds(auth_cfg, home=env["HOME"], agent_home=str(tmp_path / "ah"), probe=lambda p: "file")
    assert binds == [] and why == "auth:none", (binds, why)


def test_no_provider_block_is_the_explicit_anthropic_cli_path(tmp_path):
    """Off is a decision, not an accident: a config with no provider (or name anthropic) still runs, with OAuth."""
    env = _synthetic_home(tmp_path)
    for provider in ({}, {"name": "anthropic"}, None):
        cfg = _live()
        if provider is None:
            cfg["claude"].pop("provider", None)
        else:
            cfg["claude"]["provider"] = provider
        state = FX.provider_block_state(cfg, env)
        assert state["state"] == FX.PROVIDER_OFF, state
        assert state["reason"] in ("provider_absent", "provider_is_anthropic_cli"), state
        assert FX.provider_cycle_refusal(cfg, env, apply=True)[0] is None
        _egress, auth_cfg = FX.provider_plan_view(cfg, env)
        assert auth_cfg["claude"]["auth"]["mode"] == cfg["claude"]["auth"]["mode"], provider


# ---------------------------------------------------------------- the refusal (the operator's hard requirement)
def _drop(key):
    return lambda prov: prov.pop(key)


def _set(key, value):
    return lambda prov: prov.update({key: value})


INCOMPLETE = {
    "provider-launcher-missing": (_drop("launcher"), "provider_block_incomplete:provider_launcher_missing",
                                  FX.PROVIDER_INCOMPLETE),
    "provider-key-file-missing": (_drop("key_file"), "provider_block_incomplete:provider_key_file_missing",
                                  FX.PROVIDER_INCOMPLETE),
    "provider-auth-mode-credentials": (_set("auth_mode", "credentials_file"),
                                       "provider_block_incomplete:provider_auth_mode_invalid", FX.PROVIDER_INCOMPLETE),
    "provider-auth-mode-absent": (_drop("auth_mode"), "provider_block_incomplete:provider_auth_mode_invalid",
                                  FX.PROVIDER_INCOMPLETE),
    "provider-egress-empty": (_set("egress_allow", []), "provider_block_incomplete:provider_egress_missing",
                              FX.PROVIDER_INCOMPLETE),
    # a shape-complete block whose launcher is not on this host: a runtime fact, refused before intake as well
    "provider-launcher-absent": (_set("launcher", "{repo_root}/scripts/lib/absent_launcher.py"),
                                 "provider_launcher_unavailable", FX.PROVIDER_ACTIVE),
}


@pytest.mark.parametrize("case", sorted(INCOMPLETE), ids=sorted(INCOMPLETE))
def test_an_incomplete_provider_block_refuses_the_cycle(tmp_path, capsys, case):
    """END TO END through main(): rc 2, the typed reason, a receipt written, and NO state created.

    The dry run is refused too: a plan that quotes an Anthropic run would describe the thing the operator ruled out.
    """
    mutate, expected, expected_state = INCOMPLETE[case]
    cfg = _live()
    mutate(cfg["claude"]["provider"])
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    state_root = tmp_path / "state"
    out = tmp_path / "out"
    rc = FX.main(
        ["--cycle", "--config", str(cfg_path), "--out", str(out)],
        environ={**_synthetic_home(tmp_path), "TRADEAI_STATE_ROOT": str(state_root)},
        now=lambda: NOW,
        grant_reader=lambda tier: None,
    )
    assert rc == 2, rc
    printed = json.loads(capsys.readouterr().out)
    assert printed["refused"] == expected, printed
    assert printed["provider"]["state"] == expected_state, printed["provider"]
    receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["refused"] == printed["refused"] and receipt["mode"] == "dry_run", receipt
    assert not state_root.exists(), "a refused cycle must not create or write state"


def test_a_live_cycle_refuses_an_unreadable_key_but_a_dry_run_does_not(tmp_path):
    """A missing key file must stop --apply BEFORE a claim, and must not stop a plan (a plan never reads the key)."""
    cfg = _live()
    env = _synthetic_home(tmp_path, key=False)
    reason, state = FX.provider_cycle_refusal(cfg, env, apply=True)
    assert reason == "provider_key_unavailable", (reason, state)
    assert state["key_readable"] is False and state["state"] == FX.PROVIDER_ACTIVE
    reason, state = FX.provider_cycle_refusal(cfg, env, apply=False)
    assert reason is None and state["state"] == FX.PROVIDER_ACTIVE, state
    _synthetic_home(tmp_path, key=True)          # the operator rendered the key: the live guard lets the cycle run
    reason, state = FX.provider_cycle_refusal(cfg, env, apply=True)
    assert reason is None and state["key_readable"] is True, state


def test_a_half_block_cannot_launch_the_anthropic_cli(tmp_path):
    """Attempt-level backstop: an incomplete block is a problem, and it adds no provider host to the allowlist."""
    half = {"name": "deepseek", "launcher": str(tmp_path / "launch.py"), "auth_mode": "none",
            "egress_allow": ["api.deepseek.com:443"]}                  # no key_file
    attempt = _attempt(tmp_path, half)
    assert attempt.provider_setup_problem() == "provider_key_file_missing"
    assert attempt.egress_allow() == ["api.anthropic.com:443"], "a half block must not add the provider host"
    (tmp_path / "launch.py").write_text("# launcher\n", encoding="utf-8")
    good = {**half, "key_file": str(tmp_path / "k")}
    assert _attempt(tmp_path, good).provider_setup_problem() is None
    assert _attempt(tmp_path, good).egress_allow() == ["api.anthropic.com:443", "api.deepseek.com:443"]
