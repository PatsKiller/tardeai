# Telegram message contract

The canonical operator-message boundary is `scripts/lib/message_contract.py`.
Every outbound message is classified into a registered `MessageEnvelope@v1` before
the existing occurrence outbox decides delivery. Raw producers use the compatibility
adapter during migration; they do not select a route by supplying a class string.

The registry is `telegram-formatting-registry@v1` and currently covers CIO decisions,
entry/watch, scalp, re-entry, options, protection/risk, approvals, platform
availability, data integrity, research, digests, health/operations, market context,
progress/status, operator answers, and the safe `unknown` type.

`render_message()` is the single card renderer. It escapes all values, prints required
fields in registry order, leaves missing values explicit, keeps evidence/diagnostics in
an expandable block, and splits on paragraph boundaries within Telegram's UTF-16 limit.
Unknown or ambiguous messages route only to Command Center and are appended to the
classification audit queue. DeepSeek shadow proposals, when recorded, are redacted
advice only and cannot change the envelope, route, or delivery.

Run the registry check with:

```sh
PYTHONPATH=scripts python3 scripts/check_telegram_message_registry.py
```

New production types require a registry entry, renderer fixture, routing decision,
missing-data fixture, and outbox/digest coverage.
