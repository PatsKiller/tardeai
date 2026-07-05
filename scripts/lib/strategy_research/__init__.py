"""strategy_research — READ-ONLY options/strategy research analytics (spec Part D).

EDUCATIONAL_ONLY analysis over the EXISTING options-desk chain read path
(schwab_transport.get_option_chain — the same normalized snapshot
options_engine._schwab_chain consumes). This package:

  * never imports or calls any order / execution / 2FA surface
    (enforced by tests/test_options_strategy_research.py's grep + AST scan);
  * emits JSON analysis only — no queue writes, no candidates. The single
    carve-out is iv_history.snapshot_iv, which upserts daily ATM-IV rows
    into the options_iv_history MARKET-DATA table (advisory IV-rank
    context; never queues/orders/execution state — see iv_history.py);
  * degrades honestly: when chain data is unavailable (weekend, no linked
    account, transport error) every entry point returns
    {"available": False, "reason": ...} — numbers are NEVER fabricated,
    and IV rank reports "insufficient history" below 20 stored days.
"""
from .options_chain import (  # noqa: F401
    EDUCATIONAL_BANNER,
    deep_itm_call_analysis,
    fetch_chain_snapshot,
    parse_chain,
    strategy_feasibility,
)
from .iv_history import (  # noqa: F401
    extract_atm_iv,
    iv_rank,
    snapshot_iv,
    verdict_for_rank,
)
