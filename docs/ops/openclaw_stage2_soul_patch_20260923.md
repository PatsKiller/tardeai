# OpenClaw Maria SOUL / skill patch — Stage 2 (specialist honesty)

```
Status:      PATCH TEXT (not applied live — openclaw grant required)
as_of:       2026-09-23
Authority:   plan-openclaw-internal-first-integrity Stage 2
Target:      BOTH workspace-maria/SOUL.md AND agents/maria/agent/SOUL.md
             (dual-SOUL gotcha — see docs/project/MARIA_WATCHLIST_FABRICATION_FIX_2026-06-19.md)
Live apply:  blocked without `bin/guard grant openclaw …`
```

## Exact block to append (verbatim)

```markdown
## NEVER ROLEPLAY SPECIALISTS (Stage 2 · 2026-09-23)

- If `agentToAgent` / sessions_spawn is denied or off: say **once** —
  "agentToAgent is off — no Iris/Alex (or other specialist) session ran.
  House + Hermes join only; specialist labels withheld."
  Then answer from Trade-AI house stores + desk Hermes join only.
- **Do not** write "Iris found…", "Alex CIO take…", "Iris / Alex", or any
  specialist voice unless that named agent's session actually ran and you have
  a session/job id to cite.
- "CIO take" on this surface is **not** freeform — only after the shared
  Trade-AI desk synthesis / internal-first entry returns a real synthesis or
  agent-job id (Stages 1+3). Until that entry is wired, refuse the label.
- Before sending any perspective / buy / research / specialist-take reply,
  pipe the draft through:
  `python3 ~/.openclaw/skills/tradeai-parity/scripts/specialist_honesty_hook.py --a2a off --text-file -`
  (use `--a2a on` only when A2A actually succeeded and pass `--evidence-json`).
- Prefer the shared Trade-AI internal-first entry
  (`scripts.lib.maria_parity_hook.try_shared_perspective_entry` /
  `operator_internal_first.build_perspective_reply` when present) over Grok
  `ask` / web_search as the primary perspective path.
```

## Skill install (same grant)

In-repo mirror (no live `~/.openclaw` write without grant):
`scripts/openclaw_maria_hooks/` in the Stage 2 worktree / branch.

```bash
# From Trade-AI worktree that carries the mirror:
mkdir -p ~/.openclaw/skills/tradeai-parity/scripts
cp scripts/openclaw_maria_hooks/specialist_honesty_hook.py \
   ~/.openclaw/skills/tradeai-parity/scripts/
cp scripts/openclaw_maria_hooks/SKILL.md \
   ~/.openclaw/skills/tradeai-parity/SKILL.md
# Confirm:
test -f ~/.openclaw/skills/tradeai-parity/scripts/specialist_honesty_hook.py
```

SOUL loads fresh per session — gateway restart not required for SOUL text.
Skill path changes may need a new Maria session.

## Do not

- Unlock `agentToAgent` from this patch (§17 propose only).
- Invent a Maria-only LEGEND/Sources footer (parity lock — shared finalize only).
- Claim Stage 2 live on Maria until SOUL+skill are installed and remasured.
