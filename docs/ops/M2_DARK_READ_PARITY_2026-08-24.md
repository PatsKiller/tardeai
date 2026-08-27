# M2 dark-read parity

**Date:** 2026-08-25  
**SHADOW telemetry only. CIO_influence=0.**

Agents still read canonical JSONL. A second internal read hits isolated Postgres and is compared, never injected into DecisionPayload, ContextEnvelope, Telegram, or notifications.

Isolated canary (SCHD SCHG CSCO ANET NOC PRSO): `exact_parity=true`, divergences `[]`. Approximate mean latencies: canonical ~3.1ms, shadow ~0.8ms (not a production p95).
