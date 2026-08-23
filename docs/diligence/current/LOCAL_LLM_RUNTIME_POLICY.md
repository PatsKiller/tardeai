# Local Model Runtime Policy

**Status:** transition hold
**Updated:** 2026-08-22
**Authority:** READ_ONLY_ADVISORY

## Policy

Trade AI production automation may not use a local generative model for research,
analysis, judgment, sentiment, classification, synthesis, advisory fallback, or
math. Math is deterministic Python. Environment flags cannot restore local
generation.

The only candidate Ollama workload is `nomic-embed-text` through `/api/embed` into
the existing `content_embeddings` contract. It is pinned to:

```
model: nomic-embed-text
digest: 0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f
dimension: 768
```

`scripts/lib/ollama_embedding_policy.py` rejects non-loopback hosts, every endpoint
except `/api/embed`, every other model, non-finite vectors, and dimensions other
than 768. `scripts/audit_no_local_generative_routing.py` is the CI routing gate.

## Current Host Hold

Source enforcement is implemented on the feature branch, but the live host is not
compliant. The 2026-08-22 inventory still has installed generative models and live
host/OpenClaw configuration references. No model may be removed until all source,
cron, systemd, and OpenClaw callers are zero and no process references it.

Therefore the host must report `GPU_MODE=POLICY_VIOLATION` or `UNMEASURED`, not
`EMBEDDINGS_ONLY`, until both conditions pass:

1. 100 representative inputs, each repeated at least five times, reproduce within
   the preregistered floating tolerance, use the GPU, and remain searchable through
   `content_embeddings`.
2. The installed inventory contains only the pinned embedding model and no
   generative model is resident.

If either acceptance condition fails, the required end state is
`GPU_MODE=DISABLED` and the embedding model/runtime dependency is removed.

## Decommission Order

1. Merge and deploy the zero-generative source graph after review and green CI.
2. Remove live cron/systemd/OpenClaw generative references under operator grant.
3. Observe a bounded zero-call window and prove no active process references a
   generative model.
4. Remove generative models with the canonical Ollama removal command.
5. Run embedding acceptance. Keep only the pinned embedding model on pass;
   otherwise remove it and retire Ollama from Trade AI.

This document does not authorize host mutation, model removal, or release
promotion.

## MATURITY_IMPACT

`GPU policy compliance`: `scripts/check_local_model_fleet.py --json` and
`/api/v2/gpu-status`. Stale or incomplete evidence is `UNMEASURED`, never green.
