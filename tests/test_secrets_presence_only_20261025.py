"""Secrets are presence-only (page audit 2026-10-25).

The System Admin tab showed the last four characters of every secret to an unauthenticated loopback
reader. Every reader now gets "set" / "not set"; only an authenticated operator (a ``tailnet:`` principal)
also gets when the key was last set and the plain config identifiers. Agents (service-token) and
unauthenticated readers get presence only. No API emits any character of a secret. Synthetic values only.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "scripts"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import secrets_admin  # noqa: E402
from lib import cc_auth  # noqa: E402

SYNTH_SECRET = "synthetic-secret-value-WXYZ"
SYNTH_DB = "fixture-db-pass-QRST"
SYNTH_CFG = "fixture-login@example.invalid"
TAILS = ("WXYZ", "QRST", "-WXYZ", "e-WXYZ")


@pytest.fixture
def store(tmp_path, monkeypatch):
    env = {"ANTHROPIC_API_KEY": SYNTH_SECRET, "DB_PASSWORD": SYNTH_DB, "MOOMOO_OPEND_LOGIN_ACCOUNT": SYNTH_CFG}
    monkeypatch.setattr(secrets_admin, "_read_secret_store", lambda: ([], dict(env)))
    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        json.dumps({"ts": "2026-10-20T12:00:00+00:00", "key": "ANTHROPIC_API_KEY", "actor": "tailnet:x", "action": "set"}) + "\n"
        + json.dumps({"ts": "2026-10-22T12:00:00+00:00", "key": "ANTHROPIC_API_KEY", "actor": "tailnet:x", "action": "set"}) + "\n"
        + "not json\n"
    )
    monkeypatch.setattr(secrets_admin, "AUDIT_PATH", audit)
    return env


def _rows(out):
    return {r["key"]: r for r in out["secrets"]}


def _no_value_chars(blob: str):
    assert SYNTH_SECRET not in blob and SYNTH_DB not in blob
    for t in TAILS:
        assert t not in blob, t
    assert "••••" not in blob


@pytest.mark.parametrize("principal", [None, "", "service-token", "disabled", "exempt"])
def test_non_operator_gets_presence_only(store, principal):
    out = secrets_admin.list_secrets(principal=principal)
    blob = json.dumps(out)
    _no_value_chars(blob)
    assert SYNTH_CFG not in blob  # config identifiers are operator-only too
    rows = _rows(out)
    assert rows["ANTHROPIC_API_KEY"]["present"] is True
    assert rows["DB_PASSWORD"]["present"] is True
    assert rows["OPENAI_API_KEY"]["present"] is False
    assert all("masked" not in r and "last_set_at" not in r and "value" not in r for r in out["secrets"])
    assert out["detail"] == "presence_only"


def test_operator_gets_age_but_never_the_secret(store):
    out = secrets_admin.list_secrets(principal="tailnet:operator@example.invalid")
    _no_value_chars(json.dumps(out))
    rows = _rows(out)
    assert rows["ANTHROPIC_API_KEY"]["last_set_at"] == "2026-10-22T12:00:00+00:00"  # latest write wins
    assert "last_set_at" not in rows["DB_PASSWORD"]  # unknown age stays absent, never invented
    assert rows["MOOMOO_OPEND_LOGIN_ACCOUNT"]["value"] == SYNTH_CFG
    assert out["detail"] == "operator"


def test_mask_is_a_presence_word():
    assert secrets_admin._mask(SYNTH_SECRET) == "set"
    assert secrets_admin._mask("") is None and secrets_admin._mask(None) is None


def test_snaptrade_status_never_shows_characters(monkeypatch):
    from scripts.brokers import snaptrade_credentials as sc
    monkeypatch.setattr(sc, "_read_env", lambda: {sc.CLIENT_ID_KEY: "FIXTURE-CLIENT-ABCD", sc.CONSUMER_KEY_KEY: SYNTH_SECRET,
                                                  sc.USER_ID_KEY: "fixture-user-EFGH", sc.USER_SECRET_KEY: SYNTH_DB})
    blob = json.dumps([sc.status(), sc.user_status()])
    assert "ABCD" not in blob and "EFGH" not in blob and "FIXT" not in blob and "fixt" not in blob
    _no_value_chars(blob)
    assert sc.status()["client_id_masked"] == "set"


def test_provider_cost_label_has_no_key_characters():
    from scripts.lib.provider_cost.identity import redacted_key_id
    label = redacted_key_id(SYNTH_SECRET, provider="deepseek")
    assert label.startswith("ds_fp")
    for t in TAILS:
        assert t not in label
    assert redacted_key_id("abc") and "abc" not in redacted_key_id("abc")


def test_alpaca_status_never_shows_key_characters(monkeypatch):
    src = (ROOT / "scripts" / "alpaca_paper_adapter.py").read_text()
    assert "self.api_key[-4:]" not in src and "self.api_key[:4]" not in src


def test_no_secret_tail_slicing_left_in_known_emitters():
    for rel in ("scripts/api_v2.py", "scripts/secrets_admin.py", "scripts/fred_data_ingest.py",
                "scripts/brokers/snaptrade_credentials.py", "scripts/lib/provider_cost/identity.py"):
        src = (ROOT / rel).read_text()
        assert "t[-8:]" not in src and "FINVIZ_API_TOKEN', '')[-8:]" not in src, rel
        assert "api_key[-4:]" not in src and 'v[-4:]' not in src and "key[-4:]" not in src, rel


@pytest.fixture
def api_v2_mod(monkeypatch, tmp_path):
    if "api_v2" not in sys.modules:
        fake_dotenv = types.ModuleType("dotenv")
        fake_dotenv.load_dotenv = lambda *a, **k: False  # never load host credentials into the test
        monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    # the route reloads secrets_admin, so feed it through the tmpfs render path it reads first
    render = tmp_path / "tradeai" / "env"
    render.parent.mkdir(parents=True)
    render.write_text(f"ANTHROPIC_API_KEY={SYNTH_SECRET}\nDB_PASSWORD={SYNTH_DB}\nMOOMOO_OPEND_LOGIN_ACCOUNT={SYNTH_CFG}\n")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    import api_v2
    yield api_v2
    cc_auth.set_request_principal("")
    import importlib
    importlib.reload(secrets_admin)


@pytest.mark.parametrize("principal", ["", "service-token"])
def test_admin_secrets_route_is_presence_only_for_non_operators(api_v2_mod, principal):
    cc_auth.set_request_principal(principal)
    st, body = api_v2_mod.handle("/api/v2/admin/secrets", method="GET")
    assert st == 200
    blob = json.dumps(body)
    _no_value_chars(blob)
    assert SYNTH_CFG not in blob
    rows = {r["key"]: r for r in body["data"]["secrets"]}
    assert rows["ANTHROPIC_API_KEY"]["present"] is True


def test_admin_secrets_route_operator_detail(api_v2_mod):
    cc_auth.set_request_principal("tailnet:operator@example.invalid")
    st, body = api_v2_mod.handle("/api/v2/admin/secrets", method="GET")
    assert st == 200
    _no_value_chars(json.dumps(body))
    assert body["data"]["detail"] == "operator"
