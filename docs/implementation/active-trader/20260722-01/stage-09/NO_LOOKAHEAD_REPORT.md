# No-Lookahead Report — Stage 9
DecisionInput carries only fields observed at/before as_of; `contains_future_data=True` is refused by
every entry point (prime/fire/res/rrs/runner) with ValueError('lookahead'). Tested. The engine never
reads a value dated after as_of; replay uses the same snapshots as live would, guaranteeing equality.
