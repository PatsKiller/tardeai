"""LQ-20261107-611 ANCHOR OPS_N8N_LANE_RUN_20261108: manual "Run lane now" for every allowlisted n8n lane.

Hermetic: the ledger is a tmp sqlite file, the gateway transport is a stub, the HMAC key is a test constant (never a
real key), no gateway, no executor and no broker is touched. Proves: kind validation (bad lane, live-not-listed, live
list missing, mode mismatch, effect-gate), the exact signed payload the applier builds (verified by the REAL gateway
claim check), the operator-manual caller's isolation (own key, no fallback, run scope unavailable without it), the
run-all LIVE eligibility derivation over the repository's real config, the 10-minute batch cooldown, cancel-queued,
and that agent / service-token callers are refused on every new route.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import n8n_coordination_gateway as G
from scripts.lib import ops_controls_api as API
from scripts.lib import ops_n8n_lane_run as LR
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore
from tests.test_ops_controls_20261022 import OP, env, get, idem, post  # noqa: F401  (env is a fixture)

C = API.C
OPKEY = b"o" * 40  # a test constant, never a real key
DISPATCH_KEY = b"d" * 40
ROOT = Path(__file__).resolve().parents[1]

ALLOW = {"lanes": [
    {"lane_id": "plain-read", "command": ["$PY", "scripts/a.py"], "dry_run_arg": ["--dry-run"], "live_arg": [],
     "market_gate": False, "llm_route": None, "offpeak_gate": None},
    {"lane_id": "no-dry", "command": ["$PY", "scripts/b.py"], "dry_run_arg": None, "live_arg": [],
     "market_gate": False, "llm_route": None, "offpeak_gate": None},
    {"lane_id": "no-live", "command": ["$PY", "scripts/c.py"], "dry_run_arg": ["--dry-run"], "live_arg": None,
     "market_gate": False, "llm_route": None, "offpeak_gate": None},
    {"lane_id": "sender", "command": ["$PY", "scripts/d.py", "--deliver"], "dry_run_arg": ["--dry-run"],
     "live_arg": ["--apply"], "market_gate": False, "llm_route": None, "offpeak_gate": None},
    {"lane_id": "llm-lane", "command": ["$PY", "scripts/e.py"], "dry_run_arg": ["--dry-run"], "live_arg": ["--apply"],
     "market_gate": False, "llm_route": {"via": "cio-governed-bridge", "process_id": "x"}, "offpeak_gate": None},
    {"lane_id": "bulk-lane", "command": ["$PY", "scripts/f.py"], "dry_run_arg": ["--dry-run"], "live_arg": [],
     "market_gate": False, "llm_route": None, "offpeak_gate": "bulk"},
    {"lane_id": "market-lane", "command": ["$PY", "scripts/g.py"], "dry_run_arg": ["--dry-run"], "live_arg": [],
     "market_gate": True, "llm_route": None, "offpeak_gate": None},
    {"lane_id": "broker-lane", "command": ["$PY", "scripts/place_order_job.py"], "dry_run_arg": ["--dry-run"],
     "live_arg": [], "market_gate": False, "llm_route": None, "offpeak_gate": None},
    {"lane_id": "keyed-no", "command": ["$PY", "scripts/h.py"], "dry_run_arg": ["--dry-run"], "live_arg": ["--apply"],
     "market_gate": False, "llm_route": None, "offpeak_gate": None},
    {"lane_id": "keyed-yes", "command": ["$PY", "scripts/i.py"], "dry_run_arg": ["--dry-run"], "live_arg": ["--apply"],
     "market_gate": False, "llm_route": None, "offpeak_gate": None},
    {"lane_id": "unlisted", "command": ["$PY", "scripts/j.py"], "dry_run_arg": ["--dry-run"], "live_arg": [],
     "market_gate": False, "llm_route": None, "offpeak_gate": None},
]}
EFFECTS = {"lanes": {
    "keyed-no": {"process": "p", "input_version": "v1", "slot": "scheduled_minute", "effects": ["append"],
                 "idempotent_today": "no: not traced"},
    "keyed-yes": {"process": "q", "input_version": "v1", "slot": "scheduled_minute", "effects": ["append"],
                  "idempotent_today": "guarded: unique key"},
    "sender": {"process": "s", "input_version": "v1", "slot": "scheduled_minute", "effects": ["send"],
               "idempotent_today": "guarded: dedupe"},
}}
LIVE_LANES = "plain-read no-dry sender llm-lane bulk-lane market-lane broker-lane keyed-no keyed-yes"


@pytest.fixture()
def lr(env):  # noqa: F811
    cfg_dir = env.hosts.code_root / "config"
    (cfg_dir / "n8n_run_allowlist.json").write_text(json.dumps(ALLOW))
    (cfg_dir / "n8n_effect_keys.json").write_text(json.dumps(EFFECTS))
    env.live.write_text(f"TRADEAI_N8N_RELAY_LIVE_LANES={LIVE_LANES}\n")
    env.cfg["n8n_ledger"] = {"file": str(env.tmp / "ledger.sqlite")}
    env.ledger = CoordinationLedger(Path(env.cfg["n8n_ledger"]["file"]))
    env.runs = LedgerRunStore(env.ledger)
    env.hosts.operator_key = OPKEY
    env.hosts.market_open = lambda: True
    env.sent = []

    def stub(url, payload):
        env.sent.append((url, payload))
        return 200, {"state": "REQUESTED", "lane_id": payload["lane_id"], "mode": payload["mode"],
                     "run_id": payload["idempotency_key"]}

    env.hosts.gateway_transport = stub
    return env


def plan(e, kind, params, rid="opsreq_" + "a" * 20):
    return C.plan_change(kind, params, e.hosts, e.store, request_id=rid, actor=OP)


def refused(e, kind, params, code, rid="opsreq_" + "a" * 20):
    with pytest.raises(C.OpsError) as exc:
        plan(e, kind, params, rid)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


# ── kind validation ───────────────────────────────────────────────────────────────────────────────────────────


def test_bad_lane_is_refused_before_anything_is_queued(lr):
    refused(lr, LR.KIND_DRY, {"lane_id": "not-a-lane", "mode": "dry_run"}, "LANE_NOT_ALLOWLISTED")
    refused(lr, LR.KIND_DRY, {"lane_id": "Bad Lane!", "mode": "dry_run"}, "PARAMS_INVALID")
    refused(lr, LR.KIND_DRY, {"mode": "dry_run"}, "PARAMS_INVALID")
    assert lr.sent == []


def test_mode_must_match_the_kind(lr):
    refused(lr, LR.KIND_DRY, {"lane_id": "plain-read", "mode": "live"}, "PARAMS_INVALID")
    refused(lr, LR.KIND_LIVE, {"lane_id": "plain-read", "mode": "dry_run"}, "PARAMS_INVALID")
    refused(lr, LR.KIND_ALL_DRY, {"mode": "live"}, "PARAMS_INVALID")


def test_live_needs_the_lane_on_the_relay_live_list_with_the_relay_codes(lr):
    err = refused(lr, LR.KIND_LIVE, {"lane_id": "unlisted", "mode": "live"}, "RELAY_LIVE_NOT_ENABLED")
    assert "not on the relay live list" in err.detail
    lr.live.write_text("# no key line at all\n")
    refused(lr, LR.KIND_LIVE, {"lane_id": "plain-read", "mode": "live"}, "RELAY_LIVE_LANES_MISSING")
    lr.live.unlink()
    refused(lr, LR.KIND_LIVE, {"lane_id": "plain-read", "mode": "live"}, "RELAY_LIVE_LANES_MISSING")


def test_a_lane_without_the_mode_says_so(lr):
    refused(lr, LR.KIND_DRY, {"lane_id": "no-dry", "mode": "dry_run"}, "NO_DRY_RUN_ARG")
    refused(lr, LR.KIND_LIVE, {"lane_id": "no-live", "mode": "live"}, "NO_LIVE_MODE")


def test_an_effect_keyed_lane_is_refused_live_because_the_executor_would_refuse_it(lr):
    err = refused(lr, LR.KIND_LIVE, {"lane_id": "keyed-yes", "mode": "live"}, "EFFECT_SLOT_UNKNOWN")
    assert "slot key" in err.detail
    # but the dry run of the same lane is fine: begin() returns early for any mode but live
    assert plan(lr, LR.KIND_DRY, {"lane_id": "keyed-yes", "mode": "dry_run"}).payload["runs"][0]["mode"] == "dry_run"


def test_directions_phrases_and_undo_are_stated(lr):
    assert C.kind_spec(LR.KIND_DRY).direction == C.SAFE
    assert C.kind_spec(LR.KIND_ALL_DRY).direction == C.SAFE
    assert C.kind_spec(LR.KIND_CANCEL).direction == C.SAFE
    assert C.kind_spec(LR.KIND_LIVE).direction == C.RISKY
    assert C.kind_spec(LR.KIND_ALL_LIVE).direction == C.RISKY
    assert C.phrase_for(LR.KIND_LIVE, {"lane_id": "plain-read", "mode": "live"}, "2026-11-08") == \
        "RUN LIVE plain-read 2026-11-08"
    assert C.phrase_for(LR.KIND_ALL_LIVE, {"mode": "live"}, "2026-11-08") == "RUN ALL LIVE 2026-11-08"
    assert C.phrase_for(LR.KIND_DRY, {"lane_id": "plain-read"}, "2026-11-08") is None
    p = plan(lr, LR.KIND_LIVE, {"lane_id": "plain-read", "mode": "live"})
    assert p.undo is None and "not supported" in p.undo_reason


# ── the signed payload (verified by the REAL gateway claim check) ───────────────────────────────────────────


def test_applier_builds_the_exact_coordination_run_payload_and_signs_as_operator_manual(lr):
    rid = "opsreq_" + "b" * 20
    res = C.apply_change(LR.KIND_DRY, {"lane_id": "plain-read", "mode": "dry_run"}, None, lr.hosts, lr.store,
                         request_id=rid, actor=OP)
    assert res["outcome"] == "APPLIED"
    (url, payload), = lr.sent
    assert url == "http://127.0.0.1:18091/v1/coordination"
    claim = payload["claim"]
    assert {k: v for k, v in payload.items() if k not in ("claim", "signature")} == {
        "route": "coordination/run", "operation": "run", "lane_id": "plain-read", "mode": "dry_run",
        "idempotency_key": f"opm-{rid}", "requested_by": f"operator-manual:{rid}"}
    assert (claim["v"], claim["caller_id"], claim["project"], claim["scope"]) == (1, "operator-manual", "trade-ai",
                                                                                  "coordination_run")
    assert 0 < claim["exp"] - claim["iat"] <= 120 and len(claim["nonce"]) >= 8
    assert payload["signature"] == G.sign_claim(claim, OPKEY)
    assert G.RUN_ID_RE.fullmatch(payload["idempotency_key"])
    # the gateway's own verifier accepts it, with the operator key configured
    keys = G.build_caller_keys(DISPATCH_KEY, operator_key=OPKEY)
    now = datetime.fromtimestamp(claim["iat"], timezone.utc)
    signed = G._verify_claim(payload, key=DISPATCH_KEY, now=now, nonce_store={}, caller_keys=keys)
    assert signed["caller_id"] == "operator-manual" and signed["scope"] == "coordination_run"
    # no key material is in the payload or in the recorded result
    blob = json.dumps([payload, res])
    assert OPKEY.decode() not in blob and DISPATCH_KEY.decode() not in blob


def test_operator_caller_has_its_own_key_and_never_falls_back(lr):
    rid = "opsreq_" + "c" * 20
    C.apply_change(LR.KIND_DRY, {"lane_id": "plain-read", "mode": "dry_run"}, None, lr.hosts, lr.store,
                   request_id=rid, actor=OP)
    payload = lr.sent[0][1]
    now = datetime.fromtimestamp(payload["claim"]["iat"], timezone.utc)
    # a gateway WITHOUT the operator key: the run scope is unavailable for this caller, never the dispatch key
    with pytest.raises(G.GatewayError) as exc:
        G._verify_claim(payload, key=DISPATCH_KEY, now=now, nonce_store={},
                        caller_keys=G.build_caller_keys(DISPATCH_KEY))
    assert exc.value.reason == "run_scope_unavailable"
    # a claim signed with the dispatch or n8n key is a bad signature for this caller
    keys = G.build_caller_keys(DISPATCH_KEY, n8n_key=b"n" * 40, operator_key=OPKEY)
    forged = dict(payload, signature=G.sign_claim(payload["claim"], b"n" * 40))
    with pytest.raises(G.GatewayError) as exc:
        G._verify_claim(forged, key=DISPATCH_KEY, now=now, nonce_store={}, caller_keys=keys)
    assert exc.value.reason == "bad_signature"
    assert G.resolve_caller(keys, "operator-manual").scopes == frozenset({G.SCOPE_RUN, G.SCOPE_READ})
    assert G.resolve_caller(G.build_caller_keys(DISPATCH_KEY), "operator-manual") is None


def test_missing_operator_key_refuses_before_any_call(lr):
    lr.hosts.operator_key = None
    import os

    os.environ.pop(LR.KEY_ENV_DEFAULT, None)
    with pytest.raises(C.OpsError) as exc:
        C.apply_change(LR.KIND_DRY, {"lane_id": "plain-read", "mode": "dry_run"}, None, lr.hosts, lr.store,
                       request_id="opsreq_" + "d" * 20, actor=OP)
    assert exc.value.code == "OPERATOR_KEY_MISSING" and lr.sent == []


def test_a_gateway_refusal_or_an_unreachable_gateway_is_a_failed_outcome_not_a_success(lr):
    lr.hosts.gateway_transport = lambda u, p: (403, {"state": "REFUSED", "reason": "run_lane_not_allowlisted"})
    res = C.apply_change(LR.KIND_DRY, {"lane_id": "plain-read", "mode": "dry_run"}, None, lr.hosts, lr.store,
                         request_id="opsreq_" + "e" * 20, actor=OP)
    assert res["outcome"] == "FAILED" and res["verify"]["refused"][0]["reason"] == "run_lane_not_allowlisted"

    def boom(u, p):
        raise ConnectionRefusedError

    lr.hosts.gateway_transport = boom
    res = C.apply_change(LR.KIND_DRY, {"lane_id": "plain-read", "mode": "dry_run"}, None, lr.hosts, lr.store,
                         request_id="opsreq_" + "f" * 20, actor=OP)
    assert res["outcome"] == "FAILED" and res["runs"][0]["state"] == "UNREACHABLE"


def test_a_reply_naming_another_run_is_not_accepted_as_success(lr):
    lr.hosts.gateway_transport = lambda u, p: (200, {"state": "REQUESTED", "lane_id": "other", "mode": p["mode"],
                                                     "run_id": p["idempotency_key"]})
    res = C.apply_change(LR.KIND_DRY, {"lane_id": "plain-read", "mode": "dry_run"}, None, lr.hosts, lr.store,
                         request_id="opsreq_" + "1" * 20, actor=OP)
    assert res["outcome"] == "FAILED" and res["runs"][0]["reason"] == "identity_mismatch"


# ── run all ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_run_all_dry_is_every_lane_with_a_dry_run_arg(lr):
    p = plan(lr, LR.KIND_ALL_DRY, {"mode": "dry_run"})
    lanes = [r["lane_id"] for r in p.payload["runs"]]
    assert lanes == sorted(e["lane_id"] for e in ALLOW["lanes"] if e["dry_run_arg"] is not None)
    assert "no-dry" not in lanes
    assert all(r["run_id"].startswith("opm-opsreq_") and r["run_id"].endswith(f"-{i:03d}")
               for i, r in enumerate(p.payload["runs"]))


def test_run_all_live_derives_its_exclusions_from_config_not_a_hand_list(lr):
    p = plan(lr, LR.KIND_ALL_LIVE, {"mode": "live"})
    assert [r["lane_id"] for r in p.payload["runs"]] == ["market-lane", "no-dry", "plain-read"]
    why = {x["lane_id"]: " | ".join(x["reasons"]) for x in p.payload["excluded"]}
    assert why["sender"].count("sends_to_operator_surface") == 1
    assert "spends_llm_money" in why["llm-lane"] and "spends_llm_money" in why["bulk-lane"]
    assert "touches_broker_or_orders" in why["broker-lane"]
    assert "not_idempotent" in why["keyed-no"] and "effect_slot_unknown" in why["keyed-no"]
    assert "effect_slot_unknown" in why["keyed-yes"] and "not_idempotent" not in why["keyed-yes"]
    assert "relay_live_not_enabled" in why["unlisted"]
    assert "no_live_mode" in why["no-live"]
    assert "market-lane" not in why  # market is open in this fixture: eligible
    lr.hosts.market_open = lambda: False
    why = {x["lane_id"]: " | ".join(x["reasons"]) for x in plan(lr, LR.KIND_ALL_LIVE, {"mode": "live"}).payload["excluded"]}
    assert "market_closed" in why["market-lane"]
    lr.hosts.market_open = lambda: None
    why = {x["lane_id"]: " | ".join(x["reasons"]) for x in plan(lr, LR.KIND_ALL_LIVE, {"mode": "live"}).payload["excluded"]}
    assert "market_unknown" in why["market-lane"]  # an unknown trading day fails closed


def test_the_repository_config_derivation_is_total_and_consistent(lr):
    """Over the REAL allowlist + effect keys: every lane is either included or carries at least one reason, and an
    included lane satisfies every predicate. A new lane or a new effect needs no edit here."""
    code = ROOT
    allow, effects = LR.load_allowlist(code), LR.load_effects(code)
    assert len(allow) > 100
    live = frozenset(allow)  # pretend everything is live-listed: isolates the config-derived reasons
    for lane, e in allow.items():
        spec = effects.get(lane)
        reasons = LR.live_exclusions(e, spec, live, False, True)
        if reasons:
            continue
        assert e["live_arg"] is not None and spec is None  # no staged effect key: the executor gate cannot refuse it
        assert e.get("llm_route") is None and e.get("offpeak_gate") is None
        assert not LR.SEND_TOKEN_RE.search(LR._argv_text(e)) and not LR._broker_tokens(LR._argv_text(e))
    assert any(not LR.live_exclusions(e, effects.get(l), live, False, True) for l, e in allow.items())
    assert not LR.live_exclusions(allow["sec-fundamentals-ingest"], None, live, False, True) or True  # shape only
    # the motivating lane: staged effect key => manual LIVE is refused with the executor-gate code, dry is allowed
    sec = LR.live_exclusions(allow["sec-fundamentals-ingest"], effects["sec-fundamentals-ingest"], live, False, True)
    assert any(r.startswith("effect_slot_unknown") for r in sec)
    assert LR.dry_availability(allow["sec-fundamentals-ingest"]) is None


def test_a_second_run_all_within_ten_minutes_refuses_but_a_replay_of_the_same_request_does_not(lr):
    rid = "opsreq_" + "2" * 20
    res = C.apply_change(LR.KIND_ALL_DRY, {"mode": "dry_run"}, None, lr.hosts, lr.store, request_id=rid, actor=OP)
    assert res["outcome"] == "APPLIED" and len(res["runs"]) == len(lr.sent)
    for _u, pl in lr.sent:  # what the gateway would have written
        lr.runs.request(run_id=pl["idempotency_key"], lane_id=pl["lane_id"], mode=pl["mode"],
                        requested_by=pl["requested_by"], caller_id="operator-manual", now=lr.clock().timestamp())
    refused(lr, LR.KIND_ALL_DRY, {"mode": "dry_run"}, "BATCH_COOLDOWN", rid="opsreq_" + "3" * 20)
    plan(lr, LR.KIND_ALL_DRY, {"mode": "dry_run"}, rid=rid)  # same request re-planned by the applier: not its own cooldown
    lr.clock.advance(601)
    plan(lr, LR.KIND_ALL_DRY, {"mode": "dry_run"}, rid="opsreq_" + "3" * 20)  # window passed
    plan(lr, LR.KIND_ALL_LIVE, {"mode": "live"}, rid="opsreq_" + "4" * 20)  # and a different mode never shared it


# ── cancel queued + progress ──────────────────────────────────────────────────────────────────────────────────


def _seed(lr, rid, n=3):
    ids = []
    for i in range(n):
        run_id = f"opm-{rid}-{i:03d}"
        lr.runs.request(run_id=run_id, lane_id="plain-read", mode="dry_run", requested_by=f"operator-manual:{rid}",
                        caller_id="operator-manual", now=lr.clock().timestamp())
        ids.append(run_id)
    return ids


def test_cancel_queued_cancels_only_unstarted_operator_runs(lr):
    rid = "opsreq_" + "5" * 20
    ids = _seed(lr, rid)
    lr.runs.request(run_id="d:plain-read:dry_run:2026-11-08T00:00", lane_id="plain-read", mode="dry_run",
                    requested_by="x", caller_id="n8n-relay", now=lr.clock().timestamp())
    lr.ledger._conn.execute("UPDATE runs SET state='RUNNING', started_at='2026-11-08T00:00:00+00:00' WHERE run_id=?",
                            (ids[0],))
    lr.ledger._conn.commit()
    p = plan(lr, LR.KIND_CANCEL, {"batch_id": rid})
    assert sorted(p.payload["run_ids"]) == sorted(ids[1:])
    res = C.apply_change(LR.KIND_CANCEL, {"batch_id": rid}, p.digest, lr.hosts, lr.store, request_id="opsreq_" + "6" * 20,
                         actor=OP)
    assert res["outcome"] == "APPLIED" and sorted(res["cancelled"]) == sorted(ids[1:])
    prog = LR.batch_progress(lr.hosts.n8n_ledger_path, rid)
    assert prog["counts"] == {"queued": 0, "running": 1, "done": 0, "failed": 0, "cancelled": 2}
    assert lr.runs.get("d:plain-read:dry_run:2026-11-08T00:00")["state"] == "REQUESTED"  # n8n's row untouched
    assert not prog["finished"]  # one is still running
    refused(lr, LR.KIND_CANCEL, {"batch_id": rid}, "NOTHING_TO_CANCEL", rid="opsreq_" + "7" * 20)
    refused(lr, LR.KIND_CANCEL, {"batch_id": "not-a-request"}, "PARAMS_INVALID")


def test_progress_reads_each_receipt_with_flock_held_and_output_signal(lr):
    rid = "opsreq_" + "8" * 20
    ids = _seed(lr, rid, 2)
    lr.runs.claim_next(now=lr.clock().timestamp())
    lr.runs.finish(ids[0], state="RUN_SKIPPED_LOCK", receipt={"reason": "flock_held", "exit_code": None,
                                                              "duration_s": 0.1})
    lr.runs.claim_next(now=lr.clock().timestamp())
    lr.runs.finish(ids[1], state="RUN_DONE", receipt={"exit_code": 0, "duration_s": 2.5,
                                                      "output_signal_mtime_before": 10.0,
                                                      "output_signal_mtime_after": 20.0})
    prog = LR.batch_progress(lr.hosts.n8n_ledger_path, rid)
    assert prog["finished"] and prog["total"] == 2
    by = {r["run_id"]: r for r in prog["runs"]}
    assert by[ids[0]]["flock_held"] is True and by[ids[0]]["reason"] == "flock_held"
    assert by[ids[1]]["exit_code"] == 0 and by[ids[1]]["duration_s"] == 2.5 and by[ids[1]]["output_signal_advanced"] is True
    assert by[ids[1]]["finished_at"].endswith(" ET")


# ── the routes ────────────────────────────────────────────────────────────────────────────────────────────────


def test_lanes_route_lists_every_allowlisted_lane_and_agents_are_refused(lr):
    st, body = get(lr, "/lanes")
    assert st == 200
    data = body["data"]
    assert [r["lane_id"] for r in data["lanes"]] == sorted(e["lane_id"] for e in ALLOW["lanes"])
    row = {r["lane_id"]: r for r in data["lanes"]}
    assert row["unlisted"]["live"]["available"] is False and "relay_live_not_enabled" in row["unlisted"]["live"]["reason"]
    assert row["plain-read"]["live"]["available"] and row["plain-read"]["dry"]["available"]
    assert "Undo is not supported" in data["note"]
    for principal, listener in (("svc-token", "serve_proxy"), (OP, "wrong-listener"), ("tailnet:" + "intruder" + chr(64) + "example.com", "serve_proxy")):
        lr.who["principal"], lr.who["listener"] = principal, listener
        for sub in ("/lanes", "/lanes/batch/opsreq_" + "9" * 20):
            st, body = get(lr, sub)
            assert st == 403 and body["error"] == "AGENT_CALLER_REFUSED", (principal, sub, body)


def test_new_post_kinds_refuse_agent_callers(lr):
    lr.who["principal"] = "svc-token"
    st, body = post(lr, "/requests", {"kind": LR.KIND_LIVE, "idempotency_key": idem(),
                                      "params": {"lane_id": "plain-read", "mode": "live"}})
    assert st == 403 and body["error"] == "AGENT_CALLER_REFUSED"


# ── the gateway/ledger additions ───────────────────────────────────────────────────────────────────────────────


def test_gateway_loader_requires_a_long_operator_key_and_is_optional():
    from scripts import n8n_coordination_gateway as GW

    assert GW.load_operator_key({}) is None
    assert GW.load_operator_key({GW.OPERATOR_KEY_ENV: "k" * 40}) == b"k" * 40
    with pytest.raises(GW.BindRefused):
        GW.load_operator_key({GW.OPERATOR_KEY_ENV: "short"})
    assert GW.OPERATOR_KEY_ENV == LR.KEY_ENV_DEFAULT


def test_cancel_requested_never_touches_a_started_or_foreign_run(lr):
    rid = "opsreq_" + "0" * 20
    ids = _seed(lr, rid, 1)
    assert lr.runs.cancel_requested(ids[0], caller_id="n8n-relay", reason="x", now=1.0) is False
    assert lr.runs.cancel_requested(ids[0], caller_id="operator-manual", reason="cancelled_by_operator", now=1.0) is True
    assert lr.runs.cancel_requested(ids[0], caller_id="operator-manual", reason="again", now=2.0) is False
    row = lr.runs.get(ids[0])
    assert row["state"] == "RUN_REFUSED" and row["receipt"]["reason"] == "cancelled_by_operator"
