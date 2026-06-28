# Kill Switch Matrix

_Generated: 2026-06-28T02:06:07.238286+00:00_  
_Source: `brokers.kill_switches.status()`_  
**Status: PASS**

Kill switches hard-block live submit. They are re-checked at submit time and after approval.

```json
{
  "ok": true,
  "levels": [
    "global",
    "broker",
    "account",
    "strategy",
    "symbol",
    "asset_class",
    "options_only",
    "equities_only",
    "llm_oversight",
    "proposal_generation",
    "live_submit"
  ],
  "active": [],
  "audit_tail": [],
  "switches": []
}
```
