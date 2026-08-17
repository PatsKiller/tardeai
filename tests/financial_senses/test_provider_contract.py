"""Provider contract tests: envelope schema, provenance, authority, failure states."""
from __future__ import annotations

import pytest

from financial_senses.result import (
    AUTHORITY,
    Claim,
    Fact,
    FinancialSenseResult,
    STATUS_CONFLICT,
    STATUS_INVALID_REQUEST,
    STATUS_NOT_CONFIGURED,
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    make_result,
)
from financial_senses.provider import BaseProvider, Capability, ProviderHealth
from financial_senses.source_governance import (
    SOURCE_PRIMARY_REGULATORY,
    SOURCE_MODEL_INFERENCE,
)


def test_result_defaults():
    r = make_result("test", "test.cap")
    assert r.provider == "test"
    assert r.capability == "test.cap"
    assert r.status == STATUS_OK
    assert r.authority == AUTHORITY
    assert r.version == "1.0"


def test_authority_is_fixed_read_only():
    r = make_result("x", "y")
    with pytest.raises(ValueError):
        r.set_status("NOT_A_STATUS")
    # authority cannot be silently changed in validation
    r.authority = "TRADE"
    assert any("authority" in e for e in r.validate())


def test_status_enum_rejects_unknown():
    with pytest.raises(ValueError):
        make_result("x", "y", status="BOGUS")


def test_fact_requires_provenance():
    r = make_result("x", "y")
    r.facts.append(Fact(key="revenue", value=100.0))
    errs = r.validate()
    assert any("revenue" in e for e in errs)


def test_fact_with_source_and_as_of_is_valid():
    r = make_result("x", "y")
    r.facts.append(
        Fact(
            key="revenue",
            value=100.0,
            source_type=SOURCE_PRIMARY_REGULATORY,
            as_of="2024-12-31",
            quality="HIGH",
        )
    )
    assert r.validate() == []


def test_fact_missing_quality_is_rejected():
    r = make_result("x", "y")
    r.facts.append(
        Fact(key="revenue", value=100.0, source_type=SOURCE_PRIMARY_REGULATORY, as_of="2024-12-31")
    )
    assert any("quality" in e for e in r.validate())


def test_model_inference_cannot_back_fact():
    r = make_result("x", "y")
    r.facts.append(
        Fact(
            key="stress_pnl",
            value=-5000.0,
            source_type=SOURCE_MODEL_INFERENCE,
            as_of="2024-12-31",
            quality="MEDIUM",
        )
    )
    assert any("cannot back a FACT" in e for e in r.validate())


def test_model_estimate_is_valid_and_not_a_fact():
    from financial_senses.result import ModelEstimate

    r = make_result("x", "y")
    r.add_estimate(
        ModelEstimate(key="stress_pnl", value=-5000.0, as_of="2024-12-31", quality="MEDIUM")
    )
    assert r.validate() == []
    assert len(r.facts) == 0


def test_claim_requires_source_type():
    r = make_result("x", "y")
    r.claims.append(Claim(text="the company is growing", claim_type="growth"))
    errs = r.validate()
    assert any("claims[0]" in e for e in errs)


def test_unsupported_claim_allowed_without_source():
    r = make_result("x", "y")
    r.claims.append(Claim(text="no evidence", claim_type="UNSUPPORTED"))
    assert r.validate() == []


def test_serialization_roundtrip():
    r = make_result("sec_edgar", "sec.resolve_cik")
    r.facts.append(
        Fact(key="cik", value="0000320193", source_type=SOURCE_PRIMARY_REGULATORY, as_of="2024-01-01")
    )
    d = r.to_dict()
    assert d["authority"] == AUTHORITY
    assert d["status"] == STATUS_OK
    assert d["facts"][0]["key"] == "cik"


class _P(BaseProvider):
    name = "dummy"
    version = "1.0.0"

    def _capabilities(self):
        return [Capability("dummy.read", "READ_ONLY")]

    def _query(self, capability, request):
        return self._ok(capability)


def test_provider_health_and_capabilities():
    p = _P()
    h = p.health()
    assert isinstance(h, ProviderHealth)
    assert h.status == STATUS_OK
    assert [c.name for c in p.capabilities()] == ["dummy.read"]


def test_provider_unknown_capability_is_unavailable():
    p = _P()
    r = p.query("dummy.nope", {})
    assert r.status == STATUS_UNAVAILABLE
    assert any("not exposed" in w for w in r.warnings)


def test_provider_not_configured():
    p = _P()
    p._configured = False
    p._config_detail = "no key"
    r = p.query("dummy.read", {})
    assert r.status == STATUS_NOT_CONFIGURED


def test_provider_fail_soft_on_exception():
    class _Boom(_P):
        def _query(self, capability, request):
            raise RuntimeError("boom")

    p = _Boom()
    r = p.query("dummy.read", {})
    assert r.status == STATUS_UNAVAILABLE
    assert any("boom" in w for w in r.warnings)


def test_invalid_request_status():
    p = _P()
    r = p._invalid("dummy.read", "bad input")
    assert r.status == STATUS_INVALID_REQUEST


def test_source_governance_assert_no_inference_as_fact():
    from financial_senses.source_governance import assert_no_inference_as_fact

    assert assert_no_inference_as_fact(SOURCE_MODEL_INFERENCE) is not None
    assert assert_no_inference_as_fact(SOURCE_PRIMARY_REGULATORY) is None


class _InvalidOkProvider(BaseProvider):
    """Deliberately returns STATUS_OK with an invalid envelope.

    Proves the public query() fail-closed path: no exception escapes, the
    status is downgraded to PARTIAL, and validation warnings are present.
    """

    name = "invalid_ok"
    version = "1.0.0"

    def _capabilities(self):
        return [Capability("invalid_ok.read", "READ_ONLY")]

    def _query(self, capability, request):
        r = self._ok(capability)
        r.facts.append(
            Fact(
                key="stress_pnl",
                value=-5000.0,
                source_type=SOURCE_MODEL_INFERENCE,
                as_of="2024-12-31",
                quality="MEDIUM",
            )
        )
        return r


def test_invalid_ok_envelope_fails_closed_via_public_query():
    p = _InvalidOkProvider()
    # Must not raise (no NameError, no escaping exception).
    r = p.query("invalid_ok.read", {})
    assert r.status == STATUS_PARTIAL
    assert any("validation:" in w for w in r.warnings)
    assert any("cannot back a FACT" in w for w in r.warnings)
    assert r.authority == AUTHORITY


def test_invalid_ok_envelope_missing_quality_downgrades():
    class _MissingQuality(_InvalidOkProvider):
        def _query(self, capability, request):
            r = self._ok(capability)
            r.facts.append(
                Fact(
                    key="revenue",
                    value=100.0,
                    source_type=SOURCE_PRIMARY_REGULATORY,
                    as_of="2024-12-31",
                )
            )
            return r

    p = _MissingQuality()
    r = p.query("invalid_ok.read", {})
    assert r.status == STATUS_PARTIAL
    assert any("lacks quality" in w for w in r.warnings)
