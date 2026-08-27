# CIO operator desk loop — P0 intent routing (2026-08-20)

**READ_ONLY_ADVISORY.** Telegram INTERDICT stays as deployed.

## P0 bug (live proof)

Ask: `alex what llm you using`  
Got: full re-entry READY/NEAR dump (DHX/MOGU…).

Cause: `analyze_operator_intent` defaulted unmatched text to
`needs = ["reentry_ready", "portfolio"]` → gather always built a re-entry card.

## Fix

1. **`meta_system` intent** — LLM/model/DeepSeek/Flash/authority/status asks  
   Needs: `runtime_llm` / `runtime_status` only.  
   Answer from `config/cio_llm_policy.yaml` + `call_governed_llm` facts (`deepseek-v4-flash`).
2. **Removed** default `reentry_ready`/`portfolio`. Unmatched → `unclear` clarifier.
3. **Gather** attaches re-entry / portfolio / risk / research **only** when those needs are set.
4. Snapshot domains via `get_cio_snapshot` for cash/portfolio/risk/hermes_research.
5. Blocking research gaps → `register_advisory_gaps` + Hermes `operator_forced` + pending fulfill.

## Acceptance

```bash
CIO_OPERATOR_INTENT_FLASH=0 python3 - <<'PY'
from scripts.lib.cio_operator_desk_loop import handle_operator_desk_question
out = handle_operator_desk_question("alex what llm you using")
text = out["text"]
assert out["intent"]["intent"] == "meta_system"
assert "deepseek" in text.lower() or "flash" in text.lower()
assert "READY TO REVIEW" not in text and "DHX" not in text
print("P0_OK")
PY
```

Re-entry asks still return READY/NEAR + levels. No S0 `defensive_observe` wallpaper as Telegram body.

## Promote

Exact-main prepare/promote; restart `tradeai-cio-telegram` user service. Keep `CIO_TELEGRAM_INTERDICT=1` unless operator explicitly opens converse policy.
