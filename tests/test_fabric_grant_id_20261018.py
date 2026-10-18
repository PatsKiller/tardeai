"""Packets' TRADEAI_FABRIC_GRANT must be a real active guard grant id (2026-10-18: a free-text label passed)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "scripts" / "lib" / "fabric_grant.py"
GID = "c6c7c582214340fb9397fe821fdf224f"


def _ledger(tmp_path, **grants):
    (tmp_path / "grants.json").write_text(json.dumps({"grants": grants}))
    return {"GUARD_APPROVALS_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"}


def _run(env, *args):
    return subprocess.run([sys.executable, str(PY), *args], env=env, capture_output=True, text=True)


def _g(gid=GID, ttl=3600, uses=5):
    return {"grant_id": gid, "expires": time.time() + ttl, "uses": uses, "reason": "r"}


def test_id_prints_the_active_grant(tmp_path):
    env = _ledger(tmp_path, **{"config-write": _g()})
    p = _run(env, "id", "config-write")
    assert p.returncode == 0 and p.stdout.strip() == GID
    assert _run(env, "id", "git-push").returncode == 1


def test_verify_accepts_full_id_and_8_char_prefix_for_an_allowed_tier(tmp_path):
    env = _ledger(tmp_path, **{"config-write": _g()})
    for value in (GID, GID[:8], GID.upper()):
        p = _run(env, "verify", value, "config-write,cron")
        assert p.returncode == 0 and p.stdout.split() == ["config-write", GID], value


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


def test_guard_show_prints_ids_and_guard_id_exists():
    src = (ROOT / "bin" / "guard").read_text(encoding="utf-8")
    assert "id=%s" in src and "fabric_grant.py\" id" in src


def test_live_packets_verify_the_grant_instead_of_accepting_any_value():
    for rel in ("docs/ops/packets/comms-intent-consumer-live-20261017/cutover.sh",
                "docs/ops/packets/hermes-tune-cutover-20261017/cutover.sh",
                "docs/ops/packets/hermes-feedback-cutover-20261017/cutover.sh"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert '"$GRANT_PY" verify "$TRADEAI_FABRIC_GRANT" config-write,cron' in text, rel
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
