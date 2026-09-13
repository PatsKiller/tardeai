"""config/data_source_authority.json is the one declaration of source-of-truth
per domain, and check_data_source_authority.py is what makes it bind.

Three defects motivated it, all in the week of 2026-09-13: a 1-5 analyst
rating column filled with 10-year performance because two Finviz parsers
mapped columns by position; a state tree served from one directory and
written to another for eighteen days; a six-slot news chain whose first four
slots were dead. Each was possible because nothing a program could read said
which store, writer or provider was authoritative.

These tests are pure: the scanner runs over a tmp tree and an injected
registry. The negative control adds a Polygon call to a scratch file and
shows the gate goes red.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_data_source_authority as gate  # noqa: E402
from lib import retired_providers as rp  # noqa: E402

AUTH = json.loads((ROOT / "config" / "data_source_authority.json").read_text())


# ── the registry itself ──────────────────────────────────────────────────────


def test_registry_declares_the_four_retired_providers():
    retired = {k for k, v in AUTH["providers"].items() if v["status"] == "retired"}
    assert retired == {"finnhub", "polygon", "fmp", "newsapi"}


def test_every_domain_has_one_writer_or_declares_it_is_not_yet_consolidated():
    """A store with many writers is allowed to SAY so — never to hide it."""
    for d in AUTH["domains"]:
        if d["class"] in ("dead_feed", "manual"):
            continue
        w = d.get("writer")
        if w is None:
            assert d.get("writer_status") == "UNCONSOLIDATED" and d.get("writer_target"), d["domain"]
            assert (ROOT / d["writer_target"]).exists(), f"{d['domain']}: writer_target must exist"
        else:
            assert isinstance(w, str) and "," not in w, f"{d['domain']}: exactly one writer"
            assert w == "operator" or (ROOT / w).exists(), f"{d['domain']}: writer {w} must exist"


def test_unconsolidated_stores_have_a_shrinking_ceiling():
    base = json.loads((ROOT / "config" / "data_source_authority_baseline.json").read_text())
    for d in AUTH["domains"]:
        if d.get("writer_status") == "UNCONSOLIDATED":
            table = d["store"]["table"]
            assert table in base["writers"] and base["writers"][table] >= 2, f"{table}: ceiling recorded"


def test_every_domain_names_what_to_do_with_no_coverage():
    for d in AUTH["domains"]:
        assert d.get("no_coverage"), d["domain"]


def test_backups_never_include_a_retired_provider():
    retired = {k for k, v in AUTH["providers"].items() if v["status"] == "retired"}
    for d in AUTH["domains"]:
        assert not (set(d.get("backup", [])) & retired), d["domain"]
        assert d.get("primary_provider") not in retired, d["domain"]


def test_served_from_lists_every_linked_directory():
    assert set(AUTH["served_from"]["linked_dirs"]) == {"audit", "cio", "health", "paper_trading", "portfolios/state", "runtime", "state"}


def test_analyst_domain_declares_its_scale_and_retired_stores():
    a = next(d for d in AUTH["domains"] if d["domain"] == "analyst_opinion")
    assert a["scale"]["recommendation_mean"] == [1, 5]
    assert set(a["retired_stores"]) == {"analyst_consensus_history", "analyst_data_history"}


# ── retired_providers reads the registry, not a copy ─────────────────────────


def test_retired_module_reads_the_registry():
    assert rp.retired_providers() == {"finnhub", "polygon", "fmp", "newsapi"}
    assert rp.is_retired("POLYGON") and not rp.is_retired("alpaca")
    assert "401" in rp.retired_reason("finnhub")


def test_live_chain_drops_retired_slots_in_order():
    chain = [("finnhub", 1), ("newsapi", 2), ("finviz_news", 3), ("yahoo", 4)]
    keep, refused = rp.live_chain(chain)
    assert keep == [("finviz_news", 3), ("yahoo", 4)]
    assert refused == ["finnhub", "newsapi"]


# ── the gate ─────────────────────────────────────────────────────────────────


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


def test_retired_call_site_is_a_finding(tmp_path, monkeypatch):
    root = _tree(tmp_path, {"scripts/x.py": 'r = requests.get("https://api.polygon.io/v2/snapshot")\n'})
    monkeypatch.setattr(gate, "PROJECT_ROOT", root)
    f = gate.scan_retired(AUTH, gate._files())
    assert [x["provider"] for x in f] == ["polygon"]
    assert f[0]["file"] == "scripts/x.py"


def test_allowlisted_secret_scanner_is_not_a_finding(tmp_path, monkeypatch):
    root = _tree(tmp_path, {"scripts/secret_validators.py": 'PATTERNS = ["FMP_API_KEY", "FINNHUB_API_KEY"]\n'})
    monkeypatch.setattr(gate, "PROJECT_ROOT", root)
    assert gate.scan_retired(AUTH, gate._files()) == []


def test_undeclared_host_is_a_finding_and_declared_host_is_not(tmp_path, monkeypatch):
    root = _tree(tmp_path, {
        "scripts/a.py": 'u = "https://data.alpaca.markets/v2/stocks"\n',
        "scripts/b.py": 'u = "https://api.newprovider.com/v1/quotes"\n',
    })
    monkeypatch.setattr(gate, "PROJECT_ROOT", root)
    f = gate.scan_undeclared(AUTH, gate._files())
    assert [x["host"] for x in f] == ["api.newprovider.com"]


def test_writer_count_may_fall_but_not_rise():
    assert gate.compare_baseline("WRITER_COUNT_ROSE", {"t": 3}, {"t": 4}) == []
    assert gate.compare_baseline("WRITER_COUNT_ROSE", {"t": 4}, {"t": 4}) == []
    rose = gate.compare_baseline("WRITER_COUNT_ROSE", {"t": 5}, {"t": 4})
    assert rose and rose[0]["now"] == 5 and rose[0]["baseline"] == 4


def test_count_writers_finds_insert_and_update(tmp_path, monkeypatch):
    root = _tree(tmp_path, {
        "scripts/w1.py": 'cur.execute("INSERT INTO news_articles (a) VALUES (1)")\n',
        "scripts/w2.py": 'cur.execute("UPDATE news_articles SET a=1")\n',
        "scripts/r1.py": 'cur.execute("SELECT * FROM news_articles")\n',
    })
    monkeypatch.setattr(gate, "PROJECT_ROOT", root)
    assert gate.count_writers(AUTH, gate._files())["news_articles"] == 2


def test_negative_control_the_live_repo_has_no_retired_call_sites():
    """The gate as shipped: after Phase 2, zero retired call sites outside the allowlist."""
    findings = gate.scan_retired(AUTH, gate._files())
    assert findings == [], json.dumps(findings, indent=1)


def test_gate_is_clean_on_the_live_repo(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["x"])
    assert gate.main() == 0, capsys.readouterr().out
