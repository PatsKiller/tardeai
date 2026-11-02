"""DSN-20261101 P1: EDGAR segment extractor, deterministic map, shadow receipt, model-classified stub.

All offline: tests/fixtures/edgar/<SYM>/ holds real SEC responses recorded 2026-11-01 (gzip-wrapped; manifest.json
carries the sha256 and length of the exact response bytes). No network, no store, no model.
"""
from __future__ import annotations

import ast
import gzip
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.issuer_segments import classifier, edgar_fetch, mapping, shadow, xbrl_segments  # noqa: E402
from lib.market_risk.contract import assert_no_behavior_fields  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "edgar"
CFG = mapping.load_map()
ISSUERS = {
    "SPCX": {"cik": "1181412", "profile": "industrials", "accession": "0001628280-26-066880"},
    "T": {"cik": "732717", "profile": "comm", "accession": "0000732717-26-000372"},
    "IBM": {"cik": "51143", "profile": "tech", "accession": "0000051143-26-000095"},
    "HON": {"cik": "773840", "profile": "industrials", "accession": "0000773840-26-000143"},
}
# Operator-APPROVED SPCX option A revenue split (PR #2460, operator in-session "A + capex AI"; 10-Q
# 0001628280-26-066880 Notes 3 and 18). The capex ai_basket overlay (0.839) is an operator override, not a filing split.
SPCX_APPROVED = {"industrials": 0.1212, "comm": 0.3970, "tech": 0.4818}


def _extract(sym: str) -> dict:
    i = ISSUERS[sym]
    return shadow.extract_issuer(edgar_fetch.FixtureFetcher(FIX / sym), symbol=sym, cik=i["cik"],
                                 profile_group=i["profile"], cfg=CFG)


def _parsed(sym: str) -> dict:
    i = ISSUERS[sym]
    ext = CFG["extraction"]
    got = edgar_fetch.fetch_filing(edgar_fetch.FixtureFetcher(FIX / sym), i["cik"], ext["revenue_concepts"])
    return xbrl_segments.parse_instance(
        got["instance"], revenue_concepts=ext["revenue_concepts"], segment_axis=ext["segment_axis"],
        drilldown_axes=ext["drilldown_axes"], consolidation_axis=ext["consolidation_axis"],
        operating_segments_member=ext["operating_segments_member"], reconciling_members=ext["reconciling_members"],
        labels=xbrl_segments.parse_labels(got.get("labels")))


# ── fixtures are the real responses, byte for byte ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sym", sorted(ISSUERS))
def test_fixture_manifest_sha256(sym):
    man = json.loads((FIX / sym / "manifest.json").read_text(encoding="utf-8"))
    ok = [e for e in man["entries"].values() if e["status"] == 200]
    assert len(ok) >= 5  # companyconcept, index, instance, labels, FilingSummary
    for e in ok:
        body = gzip.decompress((FIX / sym / e["file"]).read_bytes())
        assert hashlib.sha256(body).hexdigest() == e["sha256"] and len(body) == e["bytes"]
        assert e["recorded_at"].startswith("2026-11-01")
    assert any(ISSUERS[sym]["accession"].replace("-", "") in u for u in man["entries"])


def test_fixture_fetcher_refuses_unrecorded_and_tampered(tmp_path):
    f = edgar_fetch.FixtureFetcher(FIX / "SPCX")
    with pytest.raises(edgar_fetch.FetchError, match="not_recorded"):
        f.get("https://data.sec.gov/api/xbrl/companyconcept/CIK0000000001/us-gaap/Revenues.json")
    man = json.loads((FIX / "SPCX" / "manifest.json").read_text(encoding="utf-8"))
    url, e = next((u, e) for u, e in man["entries"].items() if e["status"] == 200)
    d = tmp_path / "SPCX"
    d.mkdir()
    (d / e["file"]).write_bytes(gzip.compress(b"tampered", mtime=0))
    (d / "manifest.json").write_text(json.dumps({"entries": {url: e}}), encoding="utf-8")
    with pytest.raises(edgar_fetch.FetchError, match="sha256_mismatch"):
        edgar_fetch.FixtureFetcher(d).get(url)


# ── companyconcept finds the newest filing; the tag varies by issuer ───────────────────────────────────────────

@pytest.mark.parametrize("sym,concept", [("SPCX", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                                         ("T", "Revenues"), ("IBM", "Revenues"),
                                         ("HON", "RevenueFromContractWithCustomerExcludingAssessedTax")])
def test_latest_filing_from_companyconcept(sym, concept):
    got = edgar_fetch.latest_periodic_filing(edgar_fetch.FixtureFetcher(FIX / sym), ISSUERS[sym]["cik"],
                                             CFG["extraction"]["revenue_concepts"])
    assert got["accession"] == ISSUERS[sym]["accession"]
    assert got["form"] == "10-Q" and got["concept"] == concept


# ── parser goldens, to the dollar ──────────────────────────────────────────────────────────────────────────────

def _segs(p):
    return {r["member"]: r["revenue_usd"] for r in p["segments"]}


def test_parse_spcx():
    p = _parsed("SPCX")
    assert p["concept"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert p["period"] == {"start": "2026-07-01", "end": "2026-09-30", "days": 91, "kind": "Q"}
    assert p["consolidated_usd"] == 14_575_000_000 and p["reconciles"] and p["unallocated_usd"] == 0
    assert _segs(p) == {"spcx:SpaceMember": 1_767_000_000, "spcx:ConnectivityMember": 5_248_000_000,
                        "spcx:SIMember": 7_560_000_000}
    si = next(r for r in p["segments"] if r["member"] == "spcx:SIMember")
    kids = {c["member"]: c["revenue_usd"] for c in si["children"] if c["axis"] == "srt:ProductOrServiceAxis"}
    assert kids == {"us-gaap:AdvertisingMember": 538_000_000, "spcx:SISolutionsAndInfrastructureMember": 7_022_000_000}


def test_parse_t_resegmented_q3():
    p = _parsed("T")
    assert p["consolidated_usd"] == 32_322_000_000
    assert _segs(p) == {"t:AdvancedConnectivitySegmentMember": 29_481_000_000, "t:LegacySegmentMember": 1_519_000_000,
                        "t:LatinAmericaSegmentMember": 1_240_000_000}
    assert [(r["member"], r["revenue_usd"]) for r in p["reconciling"]] == [("us-gaap:CorporateAndOtherMember", 82_000_000)]
    assert p["unallocated_usd"] == 0


def test_parse_ibm_operating_segments_tagging():
    p = _parsed("IBM")
    assert p["consolidated_usd"] == 17_103_000_000
    assert _segs(p) == {"ibm:SoftwareMember": 7_804_000_000, "ibm:ConsultingMember": 5_335_000_000,
                        "ibm:InfrastructureMember": 3_707_000_000, "ibm:FinancingMember": 192_000_000}
    assert p["unallocated_usd"] == 65_000_000 and p["reconciles"]


def test_parse_hon_contract_revenue_tag():
    p = _parsed("HON")
    assert p["concept"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert p["consolidated_usd"] == 4_994_000_000
    assert _segs(p) == {"hon:BuildingAutomationMember": 2_020_000_000,
                        "hon:ProcessAutomationAndTechnologyMember": 1_859_000_000,
                        "hon:IndustrialAutomationMember": 1_115_000_000}


def test_labels_come_from_the_label_linkbase():
    p = _parsed("SPCX")
    assert {r["label"] for r in p["segments"]} == {"Space", "Connectivity", "SI"}


# ── mapping goldens ────────────────────────────────────────────────────────────────────────────────────────────

def test_spcx_reproduces_the_operator_approved_split():
    s = _extract("SPCX")
    assert s["status"] == "ok" and s["flags"] == [] and s["queue"] == []
    assert s["groups"] == pytest.approx(SPCX_APPROVED, abs=1e-4)
    assert s["themes"] == {"ai_basket": pytest.approx(0.4818, abs=1e-4)}
    assert s["source"]["accession"] == "0001628280-26-066880"
    rules = {ln["member"]: ln["rule_id"] for ln in s["lines"]}
    assert rules == {"spcx:SpaceMember": "spcx-space", "spcx:ConnectivityMember": "kw-comm",
                     "us-gaap:AdvertisingMember": "std-advertising",
                     "spcx:SISolutionsAndInfrastructureMember": "spcx-si-solutions"}


def test_t_maps_to_comm():
    s = _extract("T")
    assert s["groups"] == {"comm": 1.0} and s["queue"] == []
    assert s["residual"]["members"] == ["us-gaap:CorporateAndOtherMember"]
    assert s["residual"]["share"] == pytest.approx(0.0025, abs=1e-4)


def test_ibm_maps_to_tech_plus_financials():
    s = _extract("IBM")
    assert set(s["groups"]) == {"tech", "financials"}
    assert s["groups"]["financials"] == pytest.approx(192 / 17103, abs=1e-4)
    assert s["groups"]["tech"] == pytest.approx(1 - 192 / 17103, abs=1e-4)


def test_hon_maps_to_industrials():
    s = _extract("HON")
    assert s["groups"] == {"industrials": 1.0} and s["queue"] == []


def _parsed_synthetic(labels):
    segs = [{"member": f"x:{i}Member", "label": lab, "revenue_usd": 100, "children": []} for i, lab in enumerate(labels)]
    return {"status": "ok", "concept": "us-gaap:Revenues", "period": {}, "consolidated_usd": 100 * len(labels),
            "segments": segs, "reconciling": [], "unallocated_usd": 0, "reconciles": True}


def test_ambiguous_label_is_never_auto_mapped():
    s = mapping.map_issuer(_parsed_synthetic(["Software and Banking", "Cloud"]), cik=1, symbol="X",
                           profile_group="industrials", cfg=CFG)
    q = s["queue"]
    assert len(q) == 1 and q[0]["reason"] == "ambiguous" and q[0]["candidates"] == ["financials", "tech"]
    assert "segment_unmapped_fallback" in s["flags"]
    assert s["groups"] == {"industrials": 0.5, "tech": 0.5}


def test_unmapped_line_falls_back_visibly():
    s = mapping.map_issuer(_parsed_synthetic(["Widgets"]), cik=1, symbol="X", profile_group=None, cfg=CFG)
    assert s["groups"] == {"unknown": 1.0}
    assert {"segment_unmapped_fallback", "no_profile_sector"} <= set(s["flags"])
    assert s["lines"][0]["basis"] == "profile_fallback"


def test_theme_overlay_only_from_issuer_rules():
    for p in CFG["label_patterns"]:
        assert p["group"] in CFG["sector_keys"]
    for r in CFG["standard_member_rules"]:
        assert r["group"] in CFG["sector_keys"] and "themes" not in r
    s = mapping.map_issuer(_parsed_synthetic(["AI cloud software"]), cik=1, symbol="X", profile_group="tech", cfg=CFG)
    assert s["themes"] == {}


def test_drilldown_that_does_not_reconcile_is_flagged():
    p = _parsed("SPCX")
    si = next(r for r in p["segments"] if r["member"] == "spcx:SIMember")
    si["children"] = [c for c in si["children"] if c["member"] != "us-gaap:AdvertisingMember"]
    s = mapping.map_issuer(p, cik="1181412", symbol="SPCX", profile_group="industrials", cfg=CFG)
    assert "drilldown_not_reconciled:spcx:SIMember" in s["flags"]
    assert any(q["member"] == "spcx:SIMember" for q in s["queue"])


def test_no_behavior_field_in_split_or_receipt():
    r = shadow.build_receipt([_extract(s) for s in sorted(ISSUERS)], mode="replay")
    assert_no_behavior_fields(r)
    assert "weight" not in json.dumps(r)


# ── shadow only ────────────────────────────────────────────────────────────────────────────────────────────────

def test_receipt_refuses_repo_paths(tmp_path):
    r = shadow.build_receipt([], mode="replay")
    for bad in (ROOT / "config" / "issuer_segments.json", ROOT / "config" / "x.json", Path("/home/x/receipt.json")):
        with pytest.raises(PermissionError):
            shadow.write_receipt(r, bad)
    p = shadow.write_receipt(r, tmp_path / "data" / "runtime" / "issuer_segments_shadow.json")
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["shadow"] is True and doc["store_written"] is False and doc["live_lookthrough_wired"] is False


def test_cli_replay_writes_only_the_receipt(tmp_path, capsys):
    import issuer_segments_shadow as cli
    before = (ROOT / "config" / "issuer_segments.json").read_bytes()
    out = tmp_path / "receipt.json"
    args = ["--replay", str(FIX), "--receipt", str(out)]
    for sym, i in ISSUERS.items():
        args += ["--issuer", f"{sym}:{i['cik']}:{i['profile']}"]
    assert cli.main(args) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [i["symbol"] for i in doc["issuers"]] == list(ISSUERS)
    assert doc["issuers"][0]["groups"] == pytest.approx(SPCX_APPROVED, abs=1e-4)
    assert (ROOT / "config" / "issuer_segments.json").read_bytes() == before


def _imports(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add("." * node.level + (node.module or ""))
            mods |= {a.name for a in node.names}
    return mods


def test_market_risk_does_not_read_the_shadow_path():
    for p in (ROOT / "scripts" / "lib" / "market_risk").glob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert "issuer_segments_shadow" not in src and "issuer_segment_map" not in src, p
        assert not any("issuer_segments" in m for m in _imports(p) if m.startswith(("lib.", "scripts.", "."))), p


# The extractor package, and the market-risk scoring modules this design will feed (§3.3). market_risk/curation.py
# (alert-card wording, off) is outside the scoring path and is not scanned here.
_NO_MODEL = sorted((ROOT / "scripts" / "lib" / "issuer_segments").glob("*.py")) + [
    ROOT / "scripts" / "lib" / "market_risk" / f
    for f in ("lookthrough.py", "risk_budget.py", "exposure.py", "sectors.py", "book_precision.py")]


@pytest.mark.parametrize("path", _NO_MODEL, ids=lambda p: p.name)
def test_no_model_client_imported(path):
    banned = ("n8n_model_job", "llm_", "bridge", "anthropic", "openai", "model_router")
    for p in [path]:
        for m in _imports(p):
            assert not any(b in m for b in banned), (p, m)


# ── model-classified path: stub + deterministic acceptance gate ────────────────────────────────────────────────

def test_classifier_stub_never_calls_a_model():
    out = classifier.classify({"member": "x:YMember", "label": "Y"}, "text")
    assert out["status"] == classifier.NOT_BUILT and out["model_called"] is False and out["group"] is None
    assert CFG["classifier"]["enabled"] is False


TEXT = "The Energy and   Sustainability Solutions segment sells\nrefrigerants and catalysts."
KEYS = CFG["sector_keys"]


@pytest.mark.parametrize("out,reason", [
    ({"group": "materials", "quote": "sells refrigerants and catalysts", "confidence": 0.9}, None),
    ({"group": "materials", "quote": "sells chemicals", "confidence": 0.9}, "quote_not_in_filing"),
    ({"group": "materials", "quote": "", "confidence": 0.9}, "quote_not_in_filing"),
    ({"group": "materials", "quote": "refrigerants and catalysts", "confidence": 0.69}, "below_confidence_floor"),
    ({"group": "materials", "quote": "refrigerants and catalysts", "confidence": "high"}, "below_confidence_floor"),
    ({"group": "ai_basket", "quote": "refrigerants and catalysts", "confidence": 0.99}, "group_not_a_sector_key"),
])
def test_acceptance_gate(out, reason):
    r = classifier.accept({**out, "theme_suggestion": "ai_basket"}, TEXT, sector_keys=KEYS,
                          min_confidence=CFG["classifier"]["min_confidence"])
    assert r["reason"] == reason and r["accepted"] is (reason is None)
    assert r["theme_applied"] is False
    if reason:
        assert r["flag"] == "segment_unmapped_fallback" and r["group"] is None
    else:
        assert r["basis"] == "model_classified" and r["group"] == "materials"
