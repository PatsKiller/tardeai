# Intel Arc B50: Trade AI Runtime Status

**Updated:** 2026-08-23

The Intel Arc Pro B50 is not an approved Trade AI generative runtime. All local
chat/generate lanes are retired. Do not preload, warm, benchmark, or recommend a
Gemma/Qwen generative model for Trade AI.

The only candidate workload is the pinned `nomic-embed-text` model described in
`docs/diligence/current/LOCAL_LLM_RUNTIME_POLICY.md`. Application traffic is
restricted to loopback `/api/embed`, model `nomic-embed-text`, dimension 768.

Current live inventory is noncompliant because generative models remain installed
and a generative process was observed resident/stopping on 2026-08-22. The source
change does not authorize deleting those models or changing host services. Perform
physical removal only after caller inventory is zero, deployment is authorized,
and a bounded zero-call verification passes.

## 2026-08-23 read-only decommission audit

Command: `scripts/audit_local_model_decommission.py --runtime-root <live-root> --summary`.
The audit made zero mutations and measured the effective rebuild runtime:

| Gate | Result |
|---|---:|
| Live runtime source caller references | 241 |
| New branch source caller references | 171 |
| Active cron intersections | 45 |
| systemd unit intersections | 5 |
| Active OpenClaw config references | 24 (`~/.openclaw/openclaw.json`) |
| Installed generative models | 6 |
| Active generative models | 1 (`gemma3:12b`, 100% GPU when observed) |
| Embedding acceptance | UNMEASURED / not passed |
| Bounded zero-call proof | not passed |

Installed generative digests: `gemma3:4b` `6d0ee830bb54`, `gemma3:27b`
`1dcfe4e5d67c`, `gemma3-overnight:latest` `e2c134128354`, `gemma3:12b`
`7a42254767c1`, `qwen3:8b` `500a1f067a9f`, and `gemma3:12b-ctx4k`
`36c01589bb98`. Embedding candidates are `qwen3-embedding:8b` and
`nomic-embed-text:latest` (`0a109f422b47`); only the latter can qualify under
the requested policy.

`PHYSICAL_REMOVAL_READY=false`; current state is `GPU_MODE=UNRESOLVED_HOLD`,
not either accepted final mode. Do not remove any model yet. The branch removes
local generation from the directly scheduled advisory/research files in the
declared production graph, but the remaining source, schedule, service, and
OpenClaw blockers must reach zero after an authorized cutover and seven-day
zero-call proof.

Final state is exactly one of:

- `GPU_MODE=EMBEDDINGS_ONLY`: only the pinned embedding model is installed and all
  reproducibility, GPU-use, latency, residency, and existing-RAG search gates pass.
- `GPU_MODE=DISABLED`: no Trade AI Ollama model or runtime dependency remains.

Health: `scripts/check_local_model_fleet.py --json` and `/api/v2/gpu-status`.
Routing gate: `scripts/audit_no_local_generative_routing.py --json`.
Physical gate: `scripts/audit_local_model_decommission.py --summary`.

## MATURITY_IMPACT

`GPU policy compliance`: live inventory plus embedding acceptance evidence. Until
that evidence is complete, report `UNMEASURED`/policy violation rather than green.
