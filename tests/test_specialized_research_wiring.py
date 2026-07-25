from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECTOR = (ROOT / "scripts/sector_momentum_engine_v4.py").read_text()
INDUSTRY = (ROOT / "scripts/finviz_industry_groups_v4.py").read_text()
DEFENSE = (ROOT / "scripts/defense_recommendations_v11.py").read_text()
PROPOSAL = (ROOT / "scripts/proposal_due_diligence.py").read_text()
POLICY = (ROOT / "config/research_due_diligence_policy.json").read_text()


def test_sector_launcher_attaches_diligence_without_replacing_math():
    assert "base._breadth = breadth_v4" in SECTOR
    assert "sector_due_diligence" in SECTOR
    assert 'row["due_diligence"] = packet' in SECTOR
    assert "covered screener-membership measure, not official" in SECTOR
    assert "base.main()" in SECTOR


def test_industry_launcher_keeps_midday_research_but_gates_downstream_use():
    assert "industry_due_diligence" in INDUSTRY
    assert '"eligible_for_proposal_or_rotation"' in INDUSTRY
    assert 'snapshot.get("capture_kind")' in INDUSTRY
    assert "base.main()" in INDUSTRY


def test_defense_launcher_withholds_nonpassing_cards_but_keeps_audit():
    assert "defense_due_diligence" in DEFENSE
    assert 'groups["get_into"] = eligible' in DEFENSE
    assert 'recommendations["due_diligence_withheld"] = withheld' in DEFENSE
    assert '"recommendation_card_eligible"' in DEFENSE
    assert "oversight cannot restore a withheld card" in DEFENSE.lower()


def test_proposal_producer_requires_upstream_watch_packet_and_exact_ticket():
    assert "watch_due_diligence(packet)" in PROPOSAL
    assert "proposal_due_diligence(" in PROPOSAL
    assert '"EXACT_STORED_PROPOSAL"' in PROPOSAL
    assert "specialized_research_review" in PROPOSAL
    assert '"proposal_state_changed": False' in PROPOSAL
    assert '"model_may_amend_ticket": False' in PROPOSAL


def test_proposal_producer_has_no_proposal_mutation_or_execution_authority():
    lowered = PROPOSAL.lower()
    for forbidden in (
        "update paper_trade_proposals",
        "insert into paper_trade_proposals",
        "delete from paper_trade_proposals",
        "place_order",
        "broker_submit",
        "approve_order",
        "2fa_unlock",
        "premium_review(",
    ):
        assert forbidden not in lowered
    assert '"database_write": false' in lowered
    assert '"proposal_state_write": false' in lowered
    assert '"paid_lane_calls": 0' in lowered


def test_policy_declares_all_specialized_domains_and_model_sovereignty():
    for marker in (
        '"watch"', '"proposal"', '"sector"', '"industry"', '"defense"',
        '"may_override_deterministic_state": false',
        '"paid_lane_automatic": false',
        '"producer_activation": false',
        '"broker_or_order_action": false',
    ):
        assert marker in POLICY


def test_launchers_do_not_install_schedules_or_restart_services():
    joined = "\n".join((SECTOR, INDUSTRY, DEFENSE, PROPOSAL)).lower()
    for forbidden in (
        "crontab ",
        "systemctl ",
        "service restart",
        "sudo ",
        "deploy_defense",
    ):
        assert forbidden not in joined
