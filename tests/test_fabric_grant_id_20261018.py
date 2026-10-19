"""Packets' TRADEAI_FABRIC_GRANT must be a real active guard grant id (2026-10-18: a free-text label passed)."""
from __future__ import annotations

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import time
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "scripts" / "lib" / "fabric_grant.py"
GID = "c6c7c582214340fb9397fe821fdf224f"


def _ledger(tmp_path, **grants):
    (tmp_path / "grants.json").write_text(json.dumps(grants))
    return {"GUARD_APPROVALS_DIR": str(tmp_path), "PATH": "/usr/bin:/bin",
            "GUARD_AUDIT_LOG": str(tmp_path / "audit.jsonl")}


def _run(env, *args):
    return subprocess.run([sys.executable, str(PY), *args], env=env, capture_output=True, text=True)


def _g(gid=GID, ttl=3600, uses=5):
    return {"grant_id": gid, "expires": time.time() + ttl, "uses": uses, "reason": "r"}


def test_id_prints_the_active_grant(tmp_path):
    env = _ledger(tmp_path, **{"config-write": _g()})
    p = _run(env, "id", "config-write")
    assert p.returncode == 0 and p.stdout.strip() == GID
    assert _run(env, "id", "git-push").returncode == 1


def test_verify_accepts_only_full_id_for_an_allowed_tier(tmp_path):
    env = _ledger(tmp_path, **{"config-write": _g()})
    for value in (GID, GID.upper()):
        p = _run(env, "verify", value, "config-write,cron")
        assert p.returncode == 0 and p.stdout.split() == ["config-write", GID], value
    assert _run(env, "verify", GID[:8], "config-write,cron").returncode == 1


def test_verify_refuses_labels_short_prefixes_other_tiers_expired_and_spent(tmp_path):
    env = _ledger(tmp_path, **{"config-write": _g()})
    for value in ("config-write-20261018T103558", "g1", GID[:7], "", "0" * 32):
        assert _run(env, "verify", value, "config-write,cron").returncode == 1, value
    assert _run(env, "verify", GID, "release-write").returncode == 1
    assert _run(_ledger(tmp_path, **{"config-write": _g(ttl=-1)}), "verify", GID, "config-write").returncode == 1
    assert _run(_ledger(tmp_path, **{"config-write": _g(uses=0)}), "verify", GID, "config-write").returncode == 1


def test_verify_refuses_an_ambiguous_prefix(tmp_path):
    env = _ledger(tmp_path, **{"config-write": _g(GID), "cron": _g(GID[:8] + "f" * 24)})
    assert _run(env, "verify", GID[:8], "config-write,cron").returncode == 1
    assert _run(env, "verify", GID, "config-write,cron").returncode == 0


def test_missing_or_corrupt_ledger_refuses(tmp_path):
    env = {"GUARD_APPROVALS_DIR": str(tmp_path / "none"), "PATH": "/usr/bin:/bin"}
    assert _run(env, "verify", GID, "config-write").returncode == 1
    (tmp_path / "grants.json").write_text("{not json")
    assert _run({"GUARD_APPROVALS_DIR": str(tmp_path)}, "verify", GID, "config-write").returncode == 1


def test_fabric_verifier_refuses_canonical_corrupt_ledger(tmp_path):
    env = _ledger(tmp_path, **{"config-write": _g(uses=-2)})
    assert _run(env, "verify", GID, "config-write").returncode == 1


def test_fabric_verifier_refuses_symlink_ledger(tmp_path):
    target = tmp_path / "fixture.json"
    target.write_text(json.dumps({"config-write": _g()}))
    (tmp_path / "grants.json").symlink_to(target)
    assert _run({"GUARD_APPROVALS_DIR": str(tmp_path)}, "verify", GID, "config-write").returncode == 1


def _action_env(tmp_path, *, uses=2):
    packet = ROOT / "docs/ops/packets/comms-intent-consumer-live-20261017/cutover.sh"
    reason = ("comms.relay n8n-comms-intent-consumer tradeai-dispatcher "
              + hashlib.sha256(packet.read_bytes()).hexdigest()
              + " restart tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service")
    service_id = "f" * 32
    grants = {"config-write": {**_g(uses=uses), "reason": reason},
              "service": {**_g(gid=service_id, uses=uses), "reason": reason}}
    env = _ledger(tmp_path, **grants)
    env.update(TRADEAI_FABRIC_GRANT=GID, TRADEAI_FABRIC_SERVICE_GRANT=service_id)
    return env, grants


def test_action_checks_do_not_consume_and_mutation_consumes_all_required_scopes(tmp_path):
    env, original = _action_env(tmp_path)
    assert _run(env, "authorize", "comms.relay").returncode == 0
    assert json.loads((tmp_path / "grants.json").read_text()) == original
    result = _run(env, "authorize", "comms.relay", "--consume")
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["consumed"] and {r["tier"] for r in receipt["grants"]} == {"config-write", "service"}
    assert all(r["uses_left"] == 1 for r in receipt["grants"])
    ledger = json.loads((tmp_path / "grants.json").read_text())
    assert all(r["uses"] == 1 for r in ledger.values())
    event = json.loads((tmp_path / "audit.jsonl").read_text())
    assert event["consumption_id"] == receipt["consumption_id"] and event["action"] == "comms.relay"


@pytest.mark.parametrize("missing", [
    "comms.relay", "n8n-comms-intent-consumer", "tradeai-dispatcher",
    "tradeai-n8n-run-relay.service", "tradeai-n8n-coordination-gateway.service", "restart", "digest",
])
def test_action_refuses_missing_or_substring_scope_without_partial_consumption(tmp_path, missing):
    env, grants = _action_env(tmp_path)
    token = hashlib.sha256((ROOT / "docs/ops/packets/comms-intent-consumer-live-20261017/cutover.sh").read_bytes()).hexdigest() if missing == "digest" else missing
    for row in grants.values():
        row["reason"] = row["reason"].replace(token, "wrong-" + token + "-suffix")
    _ledger(tmp_path, **grants)
    before = (tmp_path / "grants.json").read_bytes()
    result = _run(env, "authorize", "comms.relay", "--consume")
    assert result.returncode == 1 and "missing exact binding" in result.stdout
    assert (tmp_path / "grants.json").read_bytes() == before
    assert not (tmp_path / "audit.jsonl").exists()


def test_wrong_scope_missing_service_expired_and_unlimited_fail_closed(tmp_path):
    for bad in ("missing_service", "wrong_id", "expired", "unlimited"):
        env, grants = _action_env(tmp_path)
        if bad == "missing_service":
            del grants["service"]
        elif bad == "wrong_id":
            env["TRADEAI_FABRIC_GRANT"] = "0" * 32
        elif bad == "expired":
            grants["service"]["expires"] = time.time() - 1
        else:
            grants["service"]["uses"] = -1
        _ledger(tmp_path, **grants)
        before = (tmp_path / "grants.json").read_bytes()
        assert _run(env, "authorize", "comms.relay", "--consume").returncode == 1, bad
        assert (tmp_path / "grants.json").read_bytes() == before


def test_concurrent_actions_reserve_last_uses_atomically(tmp_path):
    env, _ = _action_env(tmp_path, uses=1)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _run(env, "authorize", "comms.relay", "--consume"), range(8)))
    assert sum(result.returncode == 0 for result in results) == 1
    assert all(r["uses"] == 0 for r in json.loads((tmp_path / "grants.json").read_text()).values())
    assert len((tmp_path / "audit.jsonl").read_text().splitlines()) == 1


def test_accounting_failure_holds_effect_and_never_refunds_grants(tmp_path):
    env, _ = _action_env(tmp_path, uses=1)
    env["GUARD_AUDIT_LOG"] = str(tmp_path)
    result = _run(env, "authorize", "comms.relay", "--consume")
    assert result.returncode == 1 and json.loads(result.stdout)["consumed"] is True
    assert all(r["uses"] == 0 for r in json.loads((tmp_path / "grants.json").read_text()).values())


@pytest.mark.parametrize("action", ["hermes-tune.c2", "hermes-tune.c3", "hermes-tune.rollback",
                                    "hermes-feedback.c3", "hermes-feedback.rollback"])
def test_legacy_mutation_authority_holds_without_reading_or_consuming_grants(tmp_path, action):
    absent = tmp_path / "no-grant-ledger"
    result = _run({"GUARD_APPROVALS_DIR": str(absent)}, "authorize", action, "--consume")
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"schema": "FabricPacketGrantCheck@v1", "ok": False,
        "action": action, "consumed": False, "state": "held", "reason": "reviewed_common_controller_required"}
    assert not absent.exists()


def test_guard_show_prints_ids_and_guard_id_exists():
    src = (ROOT / "bin" / "guard").read_text(encoding="utf-8")
    assert "id=%s" in src and "fabric_grant.py\" id" in src


def test_live_packets_authorize_registered_actions_instead_of_accepting_any_value():
    for rel in ("docs/ops/packets/comms-intent-consumer-live-20261017/cutover.sh",
                "docs/ops/packets/hermes-tune-cutover-20261017/cutover.sh",
                "docs/ops/packets/hermes-feedback-cutover-20261017/cutover.sh"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert '"$GRANT_PY" authorize ' in text and "need_grant --consume" in text, rel
        assert '[[ $APPLY == 0 || -n "${TRADEAI_FABRIC_GRANT:-}" ]]' not in text, rel


def test_every_live_packet_gates_relay_apply_and_restarts_only_via_the_hook():
    """10-18: the tune and feedback relay --apply had no grant check and called the real systemctl."""
    for rel in ("docs/ops/packets/comms-intent-consumer-live-20261017/cutover.sh",
                "docs/ops/packets/hermes-tune-cutover-20261017/cutover.sh",
                "docs/ops/packets/hermes-feedback-cutover-20261017/cutover.sh"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        relay = text.split("\n  relay)", 1)[1].split("\n  ;;", 1)[0].split(";;\n", 1)[0]
        after_dry = relay.split("DRY RUN", 1)[1]
        assert "need_grant" in after_dry.split("cp -p", 1)[0] or "need_grant" in relay.split("[[ $APPLY", 1)[0], rel
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        assert "systemctl --user" not in code.replace('"$SYSTEMCTL_BIN" --user', ""), rel
