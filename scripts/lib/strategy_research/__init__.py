"""strategy_research — READ-ONLY options/strategy research analytics (spec Part D).

EDUCATIONAL_ONLY analysis over the EXISTING options-desk chain read path
(schwab_transport.get_option_chain — the same normalized snapshot
options_engine._schwab_chain consumes). This package:

  * never imports or calls any order / execution / 2FA surface
    (enforced by tests/test_options_strategy_research.py's grep + AST scan);
  * emits JSON analysis only — no DB writes, no queue writes, no candidates;
  * degrades honestly: when chain data is unavailable (weekend, no linked
    account, transport error) every entry point returns
    {"available": False, "reason": ...} — numbers are NEVER fabricated.
"""
from .options_chain import (  # noqa: F401
    EDUCATIONAL_BANNER,
    deep_itm_call_analysis,
    fetch_chain_snapshot,
    parse_chain,
    strategy_feasibility,
)
