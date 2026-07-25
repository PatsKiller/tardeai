from scripts.research_due_diligence_census import CONTRACT, census


def packet(domain, state, *, release=False, subject="sample", missing=None, hard=None, warnings=None):
    return {
        "contract": "research-due-diligence-v1",
        "domain": domain,
        "subject": subject,
        "state": state,
        "release_allowed": release,
        "evidence_hash": f"{domain.lower()}-hash",
        "missing_evidence": missing or [],
        "hard_failures": hard or [],
        "warnings": warnings or [],
    }


def test_census_counts_all_specialized_domains_and_proposal_release():
    report = census([{
        "sector": packet("SECTOR", "VERIFIED", release=True),
        "industry": [packet("INDUSTRY", "REVIEW_REQUIRED", warnings=["close not confirmed"])],
        "defense": packet("DEFENSE", "REJECTED", hard=["account sizing incomplete"]),
        "watch": packet("WATCH", "INSUFFICIENT_EVIDENCE", missing=["source missing"]),
        "proposal": packet("PROPOSAL", "REJECTED", hard=["INDUSTRY research state=REVIEW_REQUIRED"]),
    }])

    assert report["contract"] == CONTRACT
    assert report["read_only"] is True
    assert report["packet_count"] == 5
    assert report["domain_summary"]["SECTOR"]["release_eligible"] == 1
    assert report["domain_summary"]["INDUSTRY"]["release_blocked"] == 1
    assert report["proposal_release_eligible"] == 0
    assert report["authority"] == {
        "database_write": False,
        "packet_rebuild": False,
        "model_provider_call": False,
        "schedule_change": False,
        "service_restart": False,
        "external_action": False,
    }


def test_census_ignores_unrelated_json_and_preserves_blocker_kinds():
    report = census([{
        "unrelated": {"contract": "something-else", "domain": "SECTOR"},
        "rows": [
            packet("WATCH", "REVIEW_REQUIRED", warnings=["technical freshness is UNKNOWN"]),
            packet("DEFENSE", "INSUFFICIENT_EVIDENCE", missing=["methodology_version missing"]),
        ],
    }])

    assert report["packet_count"] == 2
    blockers = {(row["domain"], row["kind"], row["reason"]): row["count"] for row in report["top_blockers"]}
    assert blockers[("WATCH", "warning", "technical freshness is UNKNOWN")] == 1
    assert blockers[("DEFENSE", "missing", "methodology_version missing")] == 1
