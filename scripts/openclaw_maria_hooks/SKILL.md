---
name: tradeai-parity
description: Stage 2 specialist-honesty scrub + hook for shared internal-first entry (Maria).
---

# tradeai-parity (Stage 2)

**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0

In-repo mirror lives at `scripts/openclaw_maria_hooks/` (not under `.openclaw/`
in-tree — live install still targets `~/.openclaw/skills/tradeai-parity/` and
needs an **openclaw** grant).

## When to use

Before Maria sends a ticker perspective / buy / research / “Iris or CIO take”
reply, run the honesty hook so Iris/Alex/CIO labels cannot appear unless a real
specialist run happened.

If `agentToAgent` is off (default): say so once, then house + Hermes join only —
**never** roleplay Iris/Alex.

## Commands

```bash
# Scrub a draft reply (stdin → stdout). A2A off:
python3 scripts/openclaw_maria_hooks/specialist_honesty_hook.py --a2a off --text-file -

# With real A2A session evidence (JSON list):
python3 scripts/openclaw_maria_hooks/specialist_honesty_hook.py --a2a on \
  --evidence-json '[{"agent_id":"iris","run_or_session_id":"sess_…","source":"openclaw_a2a"}]' \
  --text-file -
```

## Stages 1+3 (sibling)

When `scripts.lib.operator_internal_first.build_perspective_reply` lands, Maria
must call that shared entry (via Trade-AI PYTHONPATH) for perspective intents —
this skill must **not** invent a second LEGEND/Sources footer.

## Install (openclaw grant)

```bash
mkdir -p ~/.openclaw/skills/tradeai-parity/scripts
cp scripts/openclaw_maria_hooks/specialist_honesty_hook.py \
   ~/.openclaw/skills/tradeai-parity/scripts/
cp scripts/openclaw_maria_hooks/SKILL.md \
   ~/.openclaw/skills/tradeai-parity/SKILL.md
```

See `docs/ops/openclaw_stage2_soul_patch_20260923.md` for the SOUL block.
