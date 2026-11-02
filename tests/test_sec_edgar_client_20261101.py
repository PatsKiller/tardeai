"""DSN-20261101 P0-T2: the SEC User-Agent contact comes from one helper, fails closed, and never sits in code.

Synthetic addresses only (example.org). Nothing here reads the operator's real local override: every test points
SEC_EDGAR_CLIENT_LOCAL at a temp file (or a path that does not exist).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import sec_edgar_client as sc  # noqa: E402

SYNTHETIC = "sec-ops-test@example.org"


@pytest.fixture
def no_local(tmp_path, monkeypatch):
    monkeypatch.setenv(sc.LOCAL_ENV, str(tmp_path / "absent.local.json"))
    return tmp_path


@pytest.fixture
def synthetic_local(tmp_path, monkeypatch):
    p = tmp_path / "sec.local.json"
    p.write_text(json.dumps({"contact": SYNTHETIC}), encoding="utf-8")
    monkeypatch.setenv(sc.LOCAL_ENV, str(p))
    return p


@pytest.fixture
def no_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("a request was attempted although the contact is not configured")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)


def test_committed_config_is_the_placeholder():
    doc = json.loads((ROOT / "config" / "sec_edgar_client.json").read_text(encoding="utf-8"))
    assert doc["contact"].startswith("REQUIRED")
    assert "@" not in json.dumps({k: v for k, v in doc.items() if k != "_comment"})
    assert doc["local_override_keys"] == ["contact"]
    assert doc["max_rps"] <= 8 and doc["spacing_s"] >= 0.125


def test_placeholder_fails_closed(no_local):
    cfg = sc.load_config()
    assert cfg.contact_source == "config"
    assert sc.contact_problem(cfg.contact) == "placeholder"
    with pytest.raises(sc.SecContactError, match="placeholder"):
        sc.user_agent(cfg)


@pytest.mark.parametrize("value,problem", [("", "empty"), ("   ", "empty"), ("REQUIRED: x", "placeholder"),
                                           ("not an address", "not_an_address"), ("a@b", "not_an_address"),
                                           ("TradeAI a@example.org", "not_an_address")])
def test_bad_contacts_fail_closed_without_echoing_the_value(tmp_path, monkeypatch, value, problem):
    p = tmp_path / "l.json"
    p.write_text(json.dumps({"contact": value}), encoding="utf-8")
    monkeypatch.setenv(sc.LOCAL_ENV, str(p))
    with pytest.raises(sc.SecContactError) as ei:
        sc.user_agent()
    assert problem in str(ei.value)
    if value.strip():
        assert value.strip() not in str(ei.value)


def test_local_override_supplies_the_contact(synthetic_local):
    cfg = sc.load_config()
    assert cfg.contact_source == "local_override"
    assert sc.user_agent(cfg) == f"TradeAI {SYNTHETIC}"
    assert sc.headers("application/xml", cfg) == {"User-Agent": f"TradeAI {SYNTHETIC}", "Accept": "application/xml"}


def test_local_override_cannot_change_anything_but_the_contact(tmp_path, monkeypatch):
    p = tmp_path / "l.json"
    p.write_text(json.dumps({"contact": SYNTHETIC, "app": "Other", "max_rps": 50, "spacing_s": 0}), encoding="utf-8")
    monkeypatch.setenv(sc.LOCAL_ENV, str(p))
    cfg = sc.load_config()
    assert (cfg.app, cfg.max_rps, cfg.spacing_s) == ("TradeAI", 8, 0.15)


def test_local_path_is_configurable_in_config(tmp_path, monkeypatch):
    monkeypatch.delenv(sc.LOCAL_ENV, raising=False)
    lp = tmp_path / "x.local.json"
    lp.write_text(json.dumps({"contact": SYNTHETIC}), encoding="utf-8")
    base = json.loads((ROOT / "config" / "sec_edgar_client.json").read_text(encoding="utf-8"))
    base["local_override_path"] = str(lp)
    cp = tmp_path / "sec_edgar_client.json"
    cp.write_text(json.dumps(base), encoding="utf-8")
    assert sc.user_agent(sc.load_config(cp)) == f"TradeAI {SYNTHETIC}"


def test_missing_committed_config_fails_closed(tmp_path):
    with pytest.raises(sc.SecContactError, match="missing"):
        sc.load_config(tmp_path / "nope.json")


def test_fetch_refuses_before_any_request(no_local, no_network):
    with pytest.raises(sc.SecContactError):
        sc.fetch_bytes("https://data.sec.gov/submissions/CIK0000000001.json")


def test_throttle_spaces_requests():
    cfg = sc.SecClientConfig(app="T", contact=SYNTHETIC, max_rps=8, spacing_s=0.15, timeout_s=5, contact_source="t")
    t = [100.0]
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        t[0] += s

    sc._LAST[0] = 0.0
    sc.throttle(cfg, sleep=sleep, clock=lambda: t[0])
    sc.throttle(cfg, sleep=sleep, clock=lambda: t[0])
    assert slept and abs(slept[-1] - 0.15) < 1e-9
    fast = sc.SecClientConfig(app="T", contact=SYNTHETIC, max_rps=50, spacing_s=0.0, timeout_s=5, contact_source="t")
    assert fast.min_interval_s == pytest.approx(0.1)  # never faster than SEC's 10/s


# ── every SEC caller goes through the helper and fails closed ──────────────────────────────────────────────────

def test_sec_data_ingest_refuses_without_contact(no_local, no_network):
    import sec_data_ingest as sdi
    with pytest.raises(sc.SecContactError):
        sdi._sec_get("https://data.sec.gov/submissions/CIK0000000001.json")
    with pytest.raises(sc.SecContactError):
        sdi._get_cik("AAPL")


def test_companyfacts_reader_refuses_without_contact(no_local, no_network):
    from lib.financial_senses import sec_companyfacts_reader as r
    with pytest.raises(sc.SecContactError):
        r._default_fetcher("https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json")
    assert not hasattr(r, "SEC_HEADERS")


def test_filing_documents_refuses_without_contact(no_local, no_network):
    from lib import sec_filing_documents as d
    with pytest.raises(sc.SecContactError):
        d._default_text_fetcher("https://www.sec.gov/Archives/edgar/data/1/2/ex99.htm")


def test_callers_send_the_configured_contact(synthetic_local, monkeypatch):
    seen: list[str] = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        seen.append(req.get_header("User-agent"))
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sc, "throttle", lambda *a, **k: None)
    import sec_data_ingest as sdi
    from lib.financial_senses import sec_companyfacts_reader as r
    sdi._sec_get("https://data.sec.gov/x.json")
    r._default_fetcher("https://data.sec.gov/y.json")
    assert seen == [f"TradeAI {SYNTHETIC}"] * 2


# ── public repo: no e-mail address inside any User-Agent string under scripts/ ─────────────────────────────────

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# RFC 2606 / RFC 6761 reserved names cannot identify a person; everything else is a finding.
_RESERVED = re.compile(r"@(?:[A-Za-z0-9-]+\.)*(?:example\.(?:com|org|net)|example|test|invalid|localhost)$", re.I)
_UA = re.compile(r"user[-_ ]?agent|\b[A-Z_]*_UA\b|\bUA\s*=", re.I)
_EXTS = {".py", ".sh", ".js", ".mjs", ".ts", ".json", ".yaml", ".yml"}


def ua_email_findings(root: Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*")):
        if p.suffix not in _EXTS or not p.is_file() or "__pycache__" in p.parts:
            continue
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, line in enumerate(lines):
            if not _UA.search(line):
                continue
            window = "\n".join(lines[i:i + 3])  # a header value may wrap onto the next lines
            for m in _EMAIL.finditer(window):
                if not _RESERVED.search(m.group(0)):
                    out.append(f"{p.relative_to(root.parent)}:{i + 1}")
    return sorted(set(out))


def test_no_email_address_in_any_user_agent_under_scripts():
    assert ua_email_findings(ROOT / "scripts") == []


def test_scanner_catches_a_planted_address(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "a.py").write_text('H = {"User-Agent": "TradeAI someone@realmail.net"}\n', encoding="utf-8")
    (d / "b.py").write_text('SEC_UA = (\n    "TradeAI other@company.io"\n)\n', encoding="utf-8")
    (d / "c.py").write_text('H = {"User-Agent": "TradeAI contact@example.com"}\n', encoding="utf-8")
    assert ua_email_findings(d) == ["scripts/a.py:1", "scripts/b.py:1"]
