from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs/operations/MAYA_INTELLIGENCE_AUTHORITY_MATRIX_2026-07-25.md").read_text()
SOURCE = (ROOT / "scripts/maya_intelligence_contract.py").read_text()


def test_authority_matrix_names_every_required_domain_and_field():
    for domain in ("Watch", "Proposal", "Defense", "Sector", "Industry"):
        assert domain in DOC
    for field in (
        "Trailing P/E", "Forward P/E", "P/B", "P/S", "Support", "Resistance",
        "Catalysts/events", "News provenance/freshness", "News-quality rating",
        "Analyst consensus", "Analyst upgrade", "Analyst downgrade",
    ):
        assert field in DOC


def test_contract_is_read_only_and_has_no_provider_or_execution_path():
    lowered = SOURCE.lower()
    for forbidden in (
        "requests.get(", "requests.post(", "httpx.", "subprocess.", "psycopg2",
        "insert into", "update ", "delete from", "crontab ", "systemctl ",
        "place_order", "broker_submit", "approve_order", "2fa_unlock",
    ):
        assert forbidden not in lowered
    assert 'may_override_gate": false' in lowered
    assert "news evidence quality only; not sentiment or trade authority" in lowered
