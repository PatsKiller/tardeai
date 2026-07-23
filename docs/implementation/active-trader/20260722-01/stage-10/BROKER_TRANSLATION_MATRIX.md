# Broker Translation Matrix — Stage 10
alpaca: native close/cancel when SUPPORTED (reconcile multi-status) else opposite-side close.
moomoo: opposite-side close, LIMIT-only session, Stage 5 rate governors.
schwab: opposite-side close; RTH market only when PLACE_MARKET_RTH SUPPORTED else marketable-limit;
ELECTRONIC_ENTRY_ELIGIBILITY=RESTRICTED -> broker_assist_required. UNKNOWN/UNSUPPORTED capability
fails closed (SimRejected). Excluded brokers raise TranslationError. Tested.
