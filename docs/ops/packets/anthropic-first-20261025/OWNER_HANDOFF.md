# Anthropic review handoff

PR #2181; existing branch `work/DSN-20261025-anthropic-first-P1-T1`. Publish the integrated correction once; never force-push, merge or release from the worker session.

## One active-owner source handoff

`scripts/api_v2.py` is held by `safety-fixes-secrets-20261025`, claim `20261025T220717Z-claude-a8902129`. The claim gate refused the overlapping request; no override or edit was made. Add this single entry to the `_needs_action_summary` production `probes` dictionary:

```python
"anthropic": _na.probe_anthropic,
```

`needs_action.probe_anthropic`, its pure rule and source mapping are implemented and tested. Platform-health and Jobs & health integration no longer need owner edits. Until that one-line API registration lands, the needs-action integration is incomplete.

## Operator-only acceptance

Confirm the already delivered key's organization is the intended promotional org and auto-reload remains off. Never expose the key. The shipped policy is disabled, so deployment alone cannot spend the promotion. Enable through a reviewed config change after confirmation; run tiny tier canaries through registered manual callers and reconcile durable credit and canonical ledger events. Forced exhaustion must select the original admitted fallback routes. No canary was run here.

The reset CLI is plan-only by default. It requires explicit `--apply --confirm` matching the promotion and reset scope; it appends an event without erasing spend or holds. It cannot clear actual total-cap exhaustion or repair a corrupt chain. Interrupted batch-metering claims retain their authorization for reconciliation and are not reset into a duplicate emission.

The public report proposes journal source admission/backup and routing-policy wording; no AGENTS.md edits or reviewer identities were invented. Browser/phone proof remains NOT_VERIFIED under the session's sandbox restrictions. Private screenshot outputs stay outside the public repo.
