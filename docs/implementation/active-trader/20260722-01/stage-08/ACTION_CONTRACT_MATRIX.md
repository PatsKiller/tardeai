# Action Contract Matrix — Stage 8
Actions: prime, fire, quick_add, smart_entry, replace, cancel_one, cancel_all_symbol,
cancel_all_account, smart_sell, flatten_symbol, flatten_account, scale_out, runner_convert,
overnight_convert. Results (ONLY): VALIDATED_INACTIVE, BLOCKED, REAUTHORIZATION_REQUIRED,
UNSUPPORTED, UNKNOWN_CAPABILITY, STALE_DATA, RISK_REJECTED. Every outcome.inactive == True;
no broker call; validated actions describe a lab/test intent id + journal event only.
Gate order: authorization active → allowed-action → account/symbol (else REAUTHORIZATION_REQUIRED)
→ capability (UNSUPPORTED/UNKNOWN) → data (STALE/GAP) → risk → destructive confirmation → quantity.
