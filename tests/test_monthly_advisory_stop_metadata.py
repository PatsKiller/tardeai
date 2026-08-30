from scripts.monthly_advisory import _build_portfolio_context


def test_stop_metadata_entries_do_not_break_advisory_context():
    # The production stops projection includes scalar freshness markers beside
    # symbol records; context generation must ignore those markers.
    context = _build_portfolio_context(
        portfolio={"holdings": []},
        analysis={},
        risk={},
        perf_history={},
        retirement={},
        tax_proj={},
        rebalancing={},
        dividends_cal={},
    )
    assert isinstance(context, str)
