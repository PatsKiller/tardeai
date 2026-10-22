"""Ops -> Controls: the Postgres store on a THROWAWAY cluster, and real WebAuthn verification (ANCHOR OPS_CONTROLS_20261022).

* Postgres: tests/support/isolated_pg.py stands up its own initdb cluster (loopback, temp dir, test-only names), the
  real migration is applied there, and the same behaviours the in-memory twin promises are checked against
  PgStore: append-only, hash-chained audit; never-delete triggers; compare-and-set transitions; single-use
  challenges; settings history; least-privilege grants for trade_ai; the down migration archives by rename.
  Skipped where no PostgreSQL server binaries exist. It never connects to the production server.
* WebAuthn: a software authenticator (P-256, the cryptography package) registers and asserts through the real
  py_webauthn library via PasskeyVerifier, with the production RP id and origin; user verification is required.
  Skipped where py_webauthn is not installed (it is an activation dependency; see docs/ops/OPS_CONTROLS.md).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import ops_controls_api as API

S, A = API.S, API.A
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))

try:
    from support.isolated_pg import isolated_cluster, pg_bin_dir

    pg_bin_dir()
    import psycopg2  # noqa: F401  (PgStore needs it; some CI jobs have PG binaries but no driver)
    HAVE_PG = True
except Exception:  # noqa: BLE001
    HAVE_PG = False

needs_pg = pytest.mark.skipif(not HAVE_PG, reason="no PostgreSQL server binaries or no psycopg2 on this host")


@pytest.fixture(scope="module")
def pg():
    if not HAVE_PG:
        pytest.skip("no PostgreSQL server binaries")
    with isolated_cluster() as c:
        r = c.psql("CREATE ROLE trade_ai LOGIN")
        assert r.returncode == 0, r.stderr
        up = c._run(str(pg_bin_dir() / "psql"), "-h", c.host, "-p", str(c.port), "-U", c.user, "-d", c.dbname,
                    "-v", "ON_ERROR_STOP=1", "-f", str(ROOT / "migrations" / "2026_10_22_ops_controls.sql"),
                    env={**os.environ, "PGPASSWORD": c.password})
        assert up.returncode == 0, up.stderr
        yield c


def _store(c) -> "S.PgStore":
    import psycopg2

    return S.PgStore(lambda: psycopg2.connect(host=c.host, port=c.port, dbname=c.dbname, user=c.user,
                                              password=c.password), owned=True)


@needs_pg
def test_pg_store_status_and_request_lifecycle(pg):
    st = _store(pg)
    assert st.tables_status()["state"] == "OK"
    now = datetime.now(timezone.utc)
    row = {"request_id": "opsreq_" + "a" * 20, "idempotency_key": "pg-idem-0001", "kind": "setting.set",
           "direction": "risky", "executor": "applier", "params": {"key": "k.x", "value": 1}, "phrase": "SET k.x",
           "preview": {"summary": "s"}, "expected_state_digest": "d", "actor": "tailnet:op", "status":
           "AWAITING_STEP_UP", "created_at": now, "status_at": now}
    saved, created = st.create_request(row)
    again, created2 = st.create_request(dict(row, request_id="opsreq_" + "b" * 20))
    assert created and not created2 and again["request_id"] == saved["request_id"]
    assert st.transition(saved["request_id"], ("PREVIEWED",), "APPROVED") is None
    r = st.transition(saved["request_id"], ("AWAITING_STEP_UP",), "STEP_UP_VERIFIED", stepup_token_hash="h",
                      stepup_expires_at=now + timedelta(seconds=120), stepup_factor="passkey")
    assert r["status"] == "STEP_UP_VERIFIED" and r["params"] == {"key": "k.x", "value": 1}
    assert st.list_approved() == []


@needs_pg
def test_pg_signed_approval_survives_the_round_trip_in_a_non_utc_session(pg):
    """The CC process signs approved_at it sent; the applier verifies what Postgres hands back (session zone)."""
    import psycopg2

    def connect():
        c = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.dbname, user=pg.user, password=pg.password,
                             options="-c timezone=America/New_York")
        return c
    st = S.PgStore(connect, owned=True)
    key = b"q" * 40
    now = datetime.now(timezone.utc)
    req, _ = st.create_request({"request_id": "opsreq_" + "d" * 20, "idempotency_key": "pg-idem-sig1",
                                "kind": "n8n_live_list.add", "direction": "risky", "executor": "applier",
                                "params": {"lane_id": "x", "n": 0.1}, "expected_state_digest": "e", "actor": "tailnet:o",
                                "status": "STEP_UP_VERIFIED", "stepup_factor": "passkey",
                                "stepup_credential_id": "c"})
    sig = A.sign_approval(key, dict(req, approved_at=now))
    st.transition(req["request_id"], ("STEP_UP_VERIFIED",), "APPROVED", approved_at=now, approval_sig=sig)
    back = st.get_request(req["request_id"])
    assert back["approved_at"].utcoffset() != timedelta(0)  # really came back in the session zone
    assert A.verify_approval(key, back)
    assert not A.verify_approval(key, dict(back, params={"lane_id": "y", "n": 0.1}))
    st.append_audit(actor="o", action="tz", kind=None, request_id=None, outcome="ok", detail={})
    assert S.verify_audit_chain(st.list_audit(500)) and S.verify_audit_chain(_store(pg).list_audit(500))


@needs_pg
def test_pg_audit_is_append_only_and_chained(pg):
    import psycopg2

    st = _store(pg)
    for i in range(3):
        st.append_audit(actor="tailnet:op", action=f"a{i}", kind="k", request_id=None, outcome="ok", detail={"i": i})
    rows = st.list_audit(50)
    assert S.verify_audit_chain(rows)
    assert not hasattr(st, "audit_update") and not hasattr(st, "audit_delete")
    for sql in (f"UPDATE ops_audit SET outcome = 'tampered' WHERE seq = {int(rows[0]['seq'])}",
                f"DELETE FROM ops_audit WHERE seq = {int(rows[0]['seq'])}"):
        r = pg.psql(sql)
        assert r.returncode != 0 and "refused" in r.stderr, (sql, r.stderr)
    assert S.verify_audit_chain(st.list_audit(50)) and isinstance(psycopg2.Error, type)
    # row triggers fire only on rows: give each table one
    st.credential_add({"credential_id": "c1", "name": "n", "public_key": "pk", "user_handle": "u", "created_by": "op",
                       "created_request_id": "r"})
    st.setting_apply("z.z", 1, True, actor="op", request_id="r", expect={"active": False, "value": None})
    st.create_request({"request_id": "opsreq_" + "c" * 20, "idempotency_key": "pg-idem-0002", "kind": "setting.set",
                       "direction": "risky", "executor": "applier", "params": {}, "actor": "op",
                       "status": "PREVIEWED"})
    for sql in ("DELETE FROM ops_applier_requests", "TRUNCATE ops_audit", "DELETE FROM webauthn_credentials",
                "UPDATE operator_settings_history SET actor = 'x'"):
        r = pg.psql(sql)
        assert r.returncode != 0 and ("refused" in r.stderr or "append-only" in r.stderr), (sql, r.stderr)


@needs_pg
def test_pg_settings_history_and_cas(pg):
    st = _store(pg)
    h1 = st.setting_apply("a.b", 0.6, True, actor="op", request_id="r1", expect={"active": False, "value": None})
    h2 = st.setting_apply("a.b", 0.7, True, actor="op", request_id="r2", expect={"active": True, "value": 0.6})
    with pytest.raises(S.StoreError):
        st.setting_apply("a.b", 0.8, True, actor="op", request_id="r3", expect={"active": True, "value": 0.6})
    st.setting_apply("a.b", None, False, actor="op", request_id="r4", expect={"active": True, "value": 0.7})
    cur = st.setting_get("a.b")
    assert cur["active"] is False and cur["value"] == 0.7
    hist = [h for h in st.settings_history(10) if h["key"] == "a.b"]
    assert [h["op"] for h in hist] == ["unset", "set", "set"] and h1["seq"] < h2["seq"]


@needs_pg
def test_pg_challenge_single_use_and_expiry(pg):
    st = _store(pg)
    ch = A.b64url(secrets.token_bytes(16))
    st.challenge_put(request_id="rq", purpose="step_up", challenge=ch,
                     expires_at=datetime.now(timezone.utc) + timedelta(seconds=60))
    assert st.challenge_take(request_id="rq", purpose="step_up", challenge=ch)["challenge"] == ch
    with pytest.raises(S.StoreError) as e:
        st.challenge_take(request_id="rq", purpose="step_up", challenge=ch)
    assert e.value.code == "CHALLENGE_REPLAYED"
    old = A.b64url(secrets.token_bytes(16))
    st.challenge_put(request_id="rq", purpose="step_up", challenge=old,
                     expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    with pytest.raises(S.StoreError) as e:
        st.challenge_take(request_id="rq", purpose="step_up", challenge=old)
    assert e.value.code == "CHALLENGE_EXPIRED"
    with pytest.raises(S.StoreError) as e:
        st.challenge_take(request_id="other", purpose="step_up", challenge=old)
    assert e.value.code == "CHALLENGE_UNKNOWN"


@needs_pg
def test_pg_trade_ai_role_cannot_delete_and_totp_steps_increase(pg):
    st = _store(pg)
    row = st.totp_enroll(label="phone", fingerprint="f" * 16, actor="host")
    assert st.totp_mark_step(row["id"], 100) and not st.totp_mark_step(row["id"], 100)
    r = pg.psql("SET ROLE trade_ai; SELECT count(*) FROM ops_audit")
    assert r.returncode == 0, r.stderr
    r = pg.psql("SET ROLE trade_ai; DELETE FROM totp_recovery")
    assert r.returncode != 0 and "permission denied" in r.stderr


@needs_pg
def test_pg_down_migration_archives_by_rename(pg):
    down = pg._run(str(pg_bin_dir() / "psql"), "-h", pg.host, "-p", str(pg.port), "-U", pg.user, "-d", pg.dbname,
                   "-v", "ON_ERROR_STOP=1", "-f", str(ROOT / "migrations" / "2026_10_22_ops_controls.down.sql"),
                   env={**os.environ, "PGPASSWORD": pg.password})
    assert down.returncode == 0, down.stderr
    st = _store(pg)
    assert st.tables_status()["state"] == "NOT_MIGRATED"
    r = pg.psql("SELECT count(*) FROM ops_audit_archived_20261022")
    assert r.returncode == 0


# ── real py_webauthn with a software authenticator ─────────────────────────────────────────────────────────────────

RP = "ms01-openclaw.tail163d14.ts.net"
ORIGIN = "https://" + RP


class SoftAuthenticator:
    def __init__(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import ec

        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cid = secrets.token_bytes(32)
        self.count = 0

    def _cose(self) -> bytes:
        import cbor2

        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    @staticmethod
    def _cdj(kind: str, challenge: str, origin: str = ORIGIN) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()

    def register(self, challenge: str) -> dict:
        import cbor2

        auth = (hashlib.sha256(RP.encode()).digest() + bytes([0x45]) + (0).to_bytes(4, "big") + bytes(16) +
                len(self.cid).to_bytes(2, "big") + self.cid + self._cose())
        ao = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        b = A.b64url
        return {"id": b(self.cid), "rawId": b(self.cid), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b(self._cdj("webauthn.create", challenge)), "attestationObject": b(ao),
                             "transports": ["internal"]}}

    def assert_(self, challenge: str, *, uv: bool = True, origin: str = ORIGIN) -> dict:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        self.count += 1
        auth = hashlib.sha256(RP.encode()).digest() + bytes([0x05 if uv else 0x01]) + self.count.to_bytes(4, "big")
        cdj = self._cdj("webauthn.get", challenge, origin)
        sig = self.key.sign(auth + hashlib.sha256(cdj).digest(), ec.ECDSA(hashes.SHA256()))
        b = A.b64url
        return {"id": b(self.cid), "rawId": b(self.cid), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b(cdj), "authenticatorData": b(auth), "signature": b(sig),
                             "userHandle": None}}


def test_real_webauthn_register_and_assert_with_uv_required():
    pytest.importorskip("webauthn")
    pytest.importorskip("cbor2")
    v = A.PasskeyVerifier(rp_id=RP, rp_name="Trade AI Ops Controls", origins=[ORIGIN])
    dev = SoftAuthenticator()
    ch = secrets.token_bytes(32)
    opts = v.registration_options(challenge=ch, user_handle=b"u" * 32, user_name="operator", exclude_ids=[])
    assert opts["rp"]["id"] == RP and opts["authenticatorSelection"]["userVerification"] == "required"
    reg = v.verify_registration(credential=dev.register(A.b64url(ch)), challenge=ch)
    assert reg.credential_id == A.b64url(dev.cid)
    ch2 = secrets.token_bytes(32)
    opts = v.authentication_options(challenge=ch2, allow_ids=[reg.credential_id])
    assert opts["userVerification"] == "required"
    ok = v.verify_assertion(credential=dev.assert_(A.b64url(ch2)), challenge=ch2, public_key=reg.public_key,
                            sign_count=reg.sign_count)
    assert ok.new_sign_count == 1 and ok.user_verified
    for bad in (dict(uv=False), dict(origin="https://evil.example")):
        ch3 = secrets.token_bytes(32)
        with pytest.raises(A.AuthError):
            v.verify_assertion(credential=dev.assert_(A.b64url(ch3), **bad), challenge=ch3, public_key=reg.public_key,
                               sign_count=ok.new_sign_count)
    ch4 = secrets.token_bytes(32)
    with pytest.raises(A.AuthError):  # signed over a different challenge than the server issued
        v.verify_assertion(credential=dev.assert_(A.b64url(secrets.token_bytes(32))), challenge=ch4,
                           public_key=reg.public_key, sign_count=ok.new_sign_count)


def test_b64url_round_trip():
    raw = secrets.token_bytes(37)
    assert A.b64url_decode(A.b64url(raw)) == raw and "=" not in A.b64url(raw)
    assert base64.urlsafe_b64decode(A.b64url(raw) + "===") == raw
