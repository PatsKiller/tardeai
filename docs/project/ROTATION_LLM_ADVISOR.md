# Rotation LLM Advisor Runbook

**Status:** Active advisory workflow  
**Created:** 2026-06-16  
**Script:** `scripts/rotation_llm_advisor.py`  
**Safety:** Advisory-only allocation review. No broker action.

## Purpose

The rotation advisor lets the operator ask free-form portfolio allocation questions using real holdings, symbol-card intelligence, and the advisory rotation scorer.

Example question types:

- Review whether XLB exposure should be reduced to increase SPCX exposure.
- Review whether Mag 7 exposure is too concentrated across funds and ETFs.
- Review whether defense exposure should be reduced relative to energy.
- Review which account type is best suited for a growth allocation.

## Safety contract

The advisor cannot place, cancel, submit, route, or approve broker actions. It cannot change holdings. It produces review notes only.

Each answer should include:

1. Direct portfolio review answer
2. Possible reduce candidates
3. Possible add candidates
4. Suggested review range, not instructions
5. Account-specific notes
6. Missing data and confidence warnings
7. Advisory class: `HOLD`, `WATCH`, `ADD_REVIEW`, `TRIM_REVIEW`, `ROTATE_REVIEW`, or `RESEARCH_MORE`

## Grounded-answer validation

The advisor builds a deterministic grounding report before calling the local model. This report includes:

- symbols detected in the question
- current holding value and accounts for those symbols
- symbol-card sector / asset class / analyst fields
- rotation-engine summary
- data-quality warnings

Natural-language action words such as `TRIM`, `REDUCE`, `ADD`, `ROTATE`, and `REVIEW` are excluded from ticker extraction.

If the local model overreaches, the advisor replaces the model answer with a grounded answer and preserves the raw model answer under `llm_answer_raw` when `--json` is used.

The validator flags common failures:

- numeric trim percentages when the rotation engine has no supported trim/add/rotation idea
- saying `no missing data` when sector or analyst fields are missing
- claiming tax impact without cost-basis or gain/loss data
- likely sector mismatch, such as calling XLB Industrials when metadata says Materials
- applying a symbol-specific recommendation to an account type where that symbol is not held

To inspect a blocked local answer:

```bash
python3 scripts/rotation_llm_advisor.py \
  --question "Review whether XLB exposure should be reduced to increase SPCX exposure." \
  --backend local \
  --cards data/runtime/symbol_cards_latest.json \
  --json
```

Look at:

```text
answer_validation
llm_answer_raw
grounded_answer
```

Use `--allow-ungrounded-llm` only for debugging, not for operator decisions.

## Local LLM usage

```bash
python3 scripts/rotation_llm_advisor.py \
  --question "Review whether XLB exposure should be reduced to increase SPCX exposure." \
  --backend local \
  --cards data/runtime/symbol_cards_latest.json
```

## Auto fallback usage

```bash
python3 scripts/rotation_llm_advisor.py \
  --question "Review whether Mag 7 exposure is too concentrated across funds and ETFs." \
  --backend auto \
  --cards data/runtime/symbol_cards_latest.json \
  --json
```

## OAuth/cloud prompt usage

```bash
python3 scripts/rotation_llm_advisor.py \
  --question "Review whether defense exposure should be reduced relative to energy." \
  --backend oauth_prompt \
  --cards data/runtime/symbol_cards_latest.json \
  --json
```

The script writes an evidence prompt under:

```text
data/runtime/rotation_prompts/
```

That prompt can be sent to an external OAuth-connected LLM for a second opinion. The prompt includes the same advisory-only safety framing.

## Dual LLM Advisor — local + free/OAuth Grok (manual paste)

**Script:** `scripts/rotation_dual_llm_advisor.py`

This wrapper runs the grounded rotation context through the local model and then writes a
**free/OAuth Grok prompt file** for the operator to paste manually into the Grok web/app channel.

### Hard guarantees

- **No xAI API key.** The script reads no key and needs none.
- **No paid xAI API call.** Grok is never invoked programmatically.
- **No outbound HTTP request.** The script does no network I/O of its own; it only builds context,
  optionally runs the local model, and writes a prompt file to disk.
- **Use free/OAuth Grok manually** by pasting the generated prompt into a Grok session you have
  already logged into with your free/OAuth account. The script never sends anything to Grok for you.

Grok is a **manual second opinion only**. Deterministic grounding is authoritative — the Grok prompt
cannot override it. When grounding reports no model-supported action, the final `answer_mode` is
`grounded_no_supported_action`, regardless of any later Grok paste.

### Flags

| Flag | Effect |
|---|---|
| `--skip-local` | Build the grounded answer + Grok prompt only; do not wait on the local model. |
| `--print-grok-prompt-path` | Print only the path of the generated Grok OAuth prompt `.md` file. |
| `--print-grok-prompt` | Print the full prompt with copy markers (`===== COPY BELOW INTO GROK =====` … `===== END GROK PROMPT =====`) and the `Prompt file:` path. |
| `--json` | Emit a single clean JSON object. Noisy local-model console output is captured (via `contextlib.redirect_stdout`/`redirect_stderr`) into `local_console_output`, so `--json` stays valid for `jq`. |

### Prompt file location

```text
data/runtime/rotation_prompts/
```

### Examples

Generate the Grok prompt without waiting on the local model, and get just the path:

```bash
python3 scripts/rotation_dual_llm_advisor.py \
  --question "Should I trim XLB for SPCX? How much should I trim?" \
  --cards data/runtime/symbol_cards_latest.json \
  --skip-local \
  --print-grok-prompt-path
```

Print the full prompt with copy markers (paste the body between the markers into Grok):

```bash
python3 scripts/rotation_dual_llm_advisor.py \
  --question "Should I trim XLB for SPCX? How much should I trim?" \
  --cards data/runtime/symbol_cards_latest.json \
  --skip-local \
  --print-grok-prompt
```

Clean JSON for pipelines:

```bash
python3 scripts/rotation_dual_llm_advisor.py \
  --question "Should I trim XLB for SPCX? How much should I trim?" \
  --cards data/runtime/symbol_cards_latest.json \
  --skip-local \
  --json | jq -r '.grok_oauth_prompt_path'
```

## Required inputs

| Input | Default | Purpose |
|---|---|---|
| Holdings | `data/portfolios/state/holdings.json` | Current account and position context |
| Symbol cards | `data/runtime/symbol_cards_latest.json` | Sector, analyst, news, profile context |
| ETF overrides | `config/etf_classification_overrides.json` | ETF/fund classification handling |
| Fidelity fund codes | `config/fidelity_fund_code_map.json` | Manual 401k/fund-code mapping |

## Fidelity fund-code mapping

If the scorer outputs a fund code such as `3905`, do not treat it as a normal ticker. Map it in `config/fidelity_fund_code_map.json` first.

Minimum fields:

```json
{
  "3905": {
    "display_name": "Actual Fidelity fund name",
    "asset_class": "401k_fund",
    "sector": "Large Cap Growth / S&P 500 / Target Date / Bond / etc.",
    "mag7_exposure_pct": 0.0,
    "manual_only": true,
    "mapping_status": "verified"
  }
}
```

Until mapped, any idea involving the code should remain `WATCH` or `RESEARCH_MORE`.

## Supporting commands

Refresh cards:

```bash
curl -s http://localhost:7777/api/v2/symbol-cards > data/runtime/symbol_cards_latest.json
```

Validate cards:

```bash
python3 scripts/validate_symbol_card_quality.py --input data/runtime/symbol_cards_latest.json --json
```

Run advisory scorer:

```bash
python3 scripts/rotation_intelligence_engine.py \
  --input data/portfolios/state/holdings.json \
  --cards data/runtime/symbol_cards_latest.json \
  --min-pair-score 35
```

Ask local advisor:

```bash
python3 scripts/rotation_llm_advisor.py \
  --question "Review whether XLB exposure should be reduced to increase SPCX exposure." \
  --backend local \
  --cards data/runtime/symbol_cards_latest.json
```

## Frontend/API follow-up

The CLI workflow is the foundation. The next UI/API pass should expose:

- `GET /api/v2/rotation/summary`
- `GET /api/v2/rotation/pairs`
- `POST /api/v2/rotation/ask`
- Command Center v3 `RotationIntelligence` page
- Rotation question box with local/OAuth prompt mode selector
- Evidence drawer with holdings, sector, analyst/news, and account notes

## A1A note

This workflow changes advisory behavior and documentation, so it is subject to A1A documentation consistency rules.
