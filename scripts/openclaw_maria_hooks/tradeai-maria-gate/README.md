# tradeai-maria-gate (OpenClaw plugin)

**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0

This is the in-repo mirror of `~/.openclaw/extensions/tradeai-maria-gate/`. The operator decided on
2026-09-23 to "hook Maria through the gateway". The plugin registers one OpenClaw
`message_sending` hook. For each outbound Maria message, it runs
`scripts/maria_outbound_gate.py` from the served release (CURRENT) and delivers the gated text.

## What the bridge does

It uses `scripts/lib/maria_outbound_gate.py`, which composes existing house code:

1. It removes Iris/Alex/CIO labels that have no specialist run behind them. When it removes
   any, it adds the 🔒 policy notice once.
2. When a line claims "0 findings" or "queued, not analyzed", it checks the desk Hermes join
   (opr_/res_/results). If the desk has a result, it replaces the line with the join's
   honesty line and the `res_` ids.
3. It runs the CIO stance gate on the text around each named subject. These are the outcomes:
   - Bullish text against a bearish CIO decision is held. The reply is replaced by a held
     notice, so the chat never goes silent.
   - Bullish text with no CIO decision on file is also held (fail closed).
   - Bullish text against a neutral CIO decision is rewritten to WATCH.
   - Every stance decision gets a `[CIO Stance: …]` line.
4. It adds a 🆔 footer in the comms editor's format, puts the LEGEND first, and ends with
   `finalize_operator_reply`: Origin, then Sources, then the authority tail.

Advice about position size is flagged on the receipt. The reply text is not changed for it.

## Scope

- **Telegram only.** OpenClaw's Telegram delivery passes no `sessionKey` to `message_sending`.
- **Maria's chat.** A message is in scope when the recipient is in `chatIds` (default
  `8797974247`), or when the session key starts with `agent:maria:`.
- **Other agents are skipped.** Any other agent's session key is left alone.
- **The CIO desk bot is never affected.** It is a separate Python process.

## Modes

The mode is read in this order: `MARIA_GATE_MODE` env, then plugin `config.mode`, then
`~/.config/tradeai/maria_gate_mode`. If none is set, the default is `observe`.

| Mode | Behaviour |
|------|-----------|
| `off` | No bridge call. |
| `observe` | Runs the bridge and writes a receipt (`applied: false`). The original text is delivered unchanged. |
| `live` | Delivers the gated text. If the bridge errors or times out, the original is delivered with `⚠️ unverified — house gate unavailable` added. It never drops a message silently. |

Receipts are written to `~/.local/state/tradeai/maria_outbound_gate_receipts.jsonl`. Plugin events
are logged to `~/.local/state/tradeai/maria_gate_plugin.log`.

## Enable

Enable only after the bridge is merged and promoted, so that
`CURRENT/scripts/maria_outbound_gate.py` exists.

1. Check that the bridge is in the served release:
   `ls ~/trade-ai-releases/portfolio-server/CURRENT/scripts/maria_outbound_gate.py`
2. Run a dry run with no delivery:
   `echo '{"content":"NOC is a BUY","to":"8797974247","mode":"observe"}' | MARIA_GATE_RECEIPTS=off ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python ~/trade-ai-releases/portfolio-server/CURRENT/scripts/maria_outbound_gate.py`
3. Start in observe mode: `mkdir -p ~/.config/tradeai && echo observe > ~/.config/tradeai/maria_gate_mode`
4. Back up `~/.openclaw/openclaw.json`, then add the plugin id to `plugins.allow` and add its entry:

   ```diff
      "plugins": {
        "entries": {
   +      "tradeai-maria-gate": { "enabled": true },
          ...
        },
        "allow": [
   +      "tradeai-maria-gate",
          "searxng",
          ...
   ```
5. Restart the gateway. Config changes need a restart.
6. Confirm the plugin loaded: `openclaw plugins inspect tradeai-maria-gate`
7. Send a test message to Maria. Then read the newest row of `maria_outbound_gate_receipts.jsonl`
   and the newest line of `maria_gate_plugin.log`.
8. After one clean observe session, switch to live: `echo live > ~/.config/tradeai/maria_gate_mode`.
   No restart is needed, because the mode file is read on every message.

To roll back, run `echo off > ~/.config/tradeai/maria_gate_mode`. This takes effect immediately.
To remove the plugin entirely, take the allow and entries lines back out and restart the gateway.

## Tests

- Plugin: `node --test gate-core.test.js`. This is offline and stubs the bridge.
- Bridge: `pytest tests/test_maria_outbound_gate_20260923.py`. The fixture is the real 12:26Z
  S reply.
