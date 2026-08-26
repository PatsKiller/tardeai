# CIO operator freeform agent (2026-08-20)

**READ_ONLY_ADVISORY.** Dual mode: desk intents unchanged + Flash freeform catch-all.

## Behavior

| Intent | Path |
|--------|------|
| `meta_system` | Runtime LLM facts (P0) |
| `reentry` / cash / portfolio / risk / research | Desk gather + card / defer |
| `freeform` | Soft Trade-AI context → Flash grounded answer; general reasoning OK; numbers only from facts; gaps flagged; optional Hermes soft-queue |

Env:
- `CIO_OPERATOR_FREEFORM_FLASH` (default on with intent flash)
- `CIO_OPERATOR_FREEFORM_QUEUE=1` (default) soft-queues thesis gaps for named symbols

## Acceptance

```bash
CIO_OPERATOR_INTENT_FLASH=0 CIO_OPERATOR_FREEFORM_FLASH=0 \
  python3 -c "from lib.cio_operator_desk_loop import handle_operator_desk_question as h
print(h('alex what llm you using')['intent']['intent'])
print(h('alex explain why JEPI fits')['intent']['intent'])"
# → meta_system / freeform
```

Promote exact-main; restart `tradeai-cio-telegram`. INTERDICT unchanged.
