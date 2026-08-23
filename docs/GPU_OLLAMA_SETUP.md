# Intel Arc B50: Trade AI Runtime Status

**Updated:** 2026-08-22

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

Final state is exactly one of:

- `GPU_MODE=EMBEDDINGS_ONLY`: only the pinned embedding model is installed and all
  reproducibility, GPU-use, latency, residency, and existing-RAG search gates pass.
- `GPU_MODE=DISABLED`: no Trade AI Ollama model or runtime dependency remains.

Health: `scripts/check_local_model_fleet.py --json` and `/api/v2/gpu-status`.
Routing gate: `scripts/audit_no_local_generative_routing.py --json`.

## MATURITY_IMPACT

`GPU policy compliance`: live inventory plus embedding acceptance evidence. Until
that evidence is complete, report `UNMEASURED`/policy violation rather than green.
