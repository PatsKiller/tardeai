# Hermes Compatibility Audit — Trade AI v12

**Date:** 2026-05-30
**Status:** AUDIT COMPLETE — install decision pending operator approval
**Audited tool:** [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)

---

## 1. What Is Hermes?

Hermes is a **real, actively maintained autonomous AI agent** built by Nous Research. It is not just a model family — it is a full CLI tool with persistent memory, autonomous skill creation, and multi-platform deployment.

| Attribute | Value |
|-----------|-------|
| Repository | github.com/NousResearch/hermes-agent |
| License | MIT |
| Language | Python (89.1%) |
| Install | `pip install hermes-agent` or project-scoped `setup-hermes.sh` |
| Current version | 0.14.0+ |
| Stars | 173K |

---

## 2. Compatibility Answers

### Q1: Install behavior

**Two paths:**

| Method | Scope | What it creates |
|--------|-------|-----------------|
| `pip install hermes-agent` | Global (system Python or venv) | `hermes` binary, Python packages |
| `./setup-hermes.sh` (project-scoped) | Local `.venv` | Same, but isolated to project directory |

**Recommendation:** Use project-scoped install inside `hermes_sidecar/` with its own venv. Avoids polluting system Python or Trade AI's `.venv`.

### Q2: Memory storage

| Item | Default Location | Override |
|------|-----------------|----------|
| Config | `~/.hermes/config.yaml` | `$HERMES_HOME` env var |
| Memories | `~/.hermes/memories/` | `$HERMES_HOME` |
| Skills | `~/.hermes/skills/` | `$HERMES_HOME` |
| Sessions | `~/.hermes/sessions/` | `$HERMES_HOME` |
| Logs | `~/.hermes/logs/` | `$HERMES_HOME` |
| API keys | `~/.hermes/.env` | `$HERMES_HOME` |

**Recommendation:** Set `HERMES_HOME` to `hermes_sidecar/.hermes` to keep everything project-scoped. No global `~/.hermes` pollution.

### Q3: Local model support

**YES — fully supported.**

| Provider | Supported | Notes |
|----------|-----------|-------|
| Ollama | YES | OpenAI-compatible endpoint at `localhost:11434/v1` |
| llama.cpp | YES | Via OpenAI-compatible server |
| LM Studio | YES | Via OpenAI-compatible endpoint |
| vLLM | YES | Via OpenAI-compatible endpoint |

**Critical requirement:** Hermes requires **≥64K token context window**.

**Current system status:**

| Model | Native context | Hermes 64K requirement | Status |
|-------|---------------|----------------------|--------|
| gemma3:12b | **131,072** tokens | 64K needed | **PASS** |
| gemma3:4b | 131,072 tokens | 64K needed | PASS (fallback only) |
| Gemma4 31B (llama.cpp) | 131,072 tokens | 64K needed | PASS (off-hours only) |

**Note:** Ollama's default `num_ctx` is 2048-4096 at runtime. Hermes may need to request a larger context via API parameters, or we may need a Modelfile with `PARAMETER num_ctx 65536`. This should be tested during Phase P0 smoke test — if gemma3:12b rejects large context at runtime, we create a Modelfile alias (no model routing change, just a context param).

### Q4: External API calls

**Hermes does NOT phone home by default.** It connects only to the configured LLM provider.

| Feature | External call? | Required? |
|---------|---------------|-----------|
| LLM generation | To configured provider only | YES (local Ollama = no external) |
| Web search (Firecrawl) | Yes | NO — optional skill |
| TTS (ElevenLabs) | Yes | NO — optional |
| Browser (Browserbase) | Yes | NO — optional |
| Nous Portal | Yes | NO — optional cloud dashboard |
| Gateway messaging | To platform APIs | NO — only if gateway enabled |

**With local Ollama as provider and no optional skills enabled, Hermes makes zero external network calls.**

### Q5: Project scoping

**YES — fully supported.**

- Set `HERMES_HOME=hermes_sidecar/.hermes` for project-scoped config/memory
- Use `setup-hermes.sh` for project-scoped venv
- All data stays under the project directory

### Q6: Sandboxing

**Partial.** Hermes is a Python process with filesystem access. It does not have built-in sandboxing.

**Mitigation via our sidecar wrapper:**

- `run_hermes_readonly.sh` unsets all Trade AI secrets from env
- Filesystem contract in `HERMES_READ_ONLY_PILOT_PLAN.md` defines allowed read/write paths
- No cron, no gateway, no DB credentials passed
- Manual runs only during pilot

**Hermes can read any file the user can read.** The safety boundary is enforced by:
1. Not passing credentials via env
2. Not enabling gateway/cron
3. Operator review of all outputs
4. Hermes MEMORY.md containing explicit safety rules

### Q7: Claude Code conflict

**NO conflict.** Hermes and Claude Code are independent tools:

| Aspect | Claude Code | Hermes |
|--------|-------------|--------|
| Runtime | Node.js | Python |
| Config | `~/.claude/` | `~/.hermes/` (or `$HERMES_HOME`) |
| Port | None (CLI) | None (CLI), or gateway port if enabled |
| LLM | Anthropic API | Configurable (Ollama for us) |
| Purpose | Implementation mechanic | Research/memory sidecar |

Both can run simultaneously. Hermes even has documented integration with Claude Code via Tool Gateway MCP bridge — though we would not enable that during pilot.

### Q8: Rollback/uninstall

**Clean and straightforward:**

| Scenario | Commands |
|----------|----------|
| Project-scoped install | `rm -rf hermes_sidecar/` |
| Global pip install | `pip uninstall hermes-agent` |
| Global config cleanup | `rm -rf ~/.hermes` (only if it didn't exist before) |
| Gateway stop | `hermes gateway stop` then `systemctl --user disable hermes-gateway` |

**Our plan:** Project-scoped only, so rollback is `rm -rf hermes_sidecar/`. No global state to clean up.

### Q9: Gateway/daemon mode

**YES, Hermes has a gateway mode** (`hermes gateway setup/install/start`).

| Feature | What it does |
|---------|-------------|
| `hermes gateway setup` | Configures messaging integrations |
| `hermes gateway install` | Creates systemd user service |
| `hermes gateway start` | Starts persistent daemon |

**We must NOT enable any of these during pilot.** The install plan already prohibits gateway setup.

---

## 3. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Hermes writes to `~/.hermes` globally | MEDIUM | Set `HERMES_HOME` to project path |
| Hermes calls cloud APIs by default | LOW | Configure local Ollama only, no API keys |
| Hermes creates systemd service | MEDIUM | Do not run `hermes gateway install` |
| Hermes context window too small | LOW | gemma3:12b supports 131K natively; may need num_ctx param |
| Hermes reads Trade AI secrets from env | MEDIUM | Wrapper script unsets all secrets |
| Hermes modifies Trade AI files | LOW | Filesystem contract + manual review |
| Hermes conflicts with Trade AI cron/Ollama | LOW | No cron, shares Ollama (max_concurrent=1 enforced) |
| Hermes can't function without cloud key | LOW | Local Ollama confirmed compatible |

---

## 4. Ollama Concurrency Note

Trade AI and Hermes would share the same Ollama instance. Current policy: `max_concurrent=1`.

During pilot (manual runs only), this is fine — operator controls when Hermes runs vs when Trade AI enrichment runs. If Hermes moves to scheduled runs later, we'll need to coordinate with Trade AI's cron schedule to avoid model contention.

**No change needed for pilot.**

---

## 5. Context Window Verification Plan

gemma3:12b advertises 131K native context. Ollama may default to a smaller runtime context. During Phase P0:

1. Run `hermes doctor` — it reports detected context window
2. If < 64K reported, create a Modelfile:
   ```
   FROM gemma3:12b
   PARAMETER num_ctx 65536
   ```
3. Register as `gemma3-hermes:12b` — does NOT change production routing
4. Point Hermes config to the new tag

**This is a configuration adjustment, not a model routing change.**

---

## 6. Install Decision Matrix

| Question | Answer | Blocker? |
|----------|--------|----------|
| Does Hermes exist as a real tool? | YES | No |
| Can it use local Ollama? | YES | No |
| Does it need cloud API keys? | NO (with local Ollama) | No |
| Can config be project-scoped? | YES (via HERMES_HOME) | No |
| Does it conflict with Claude Code? | NO | No |
| Can it be cleanly uninstalled? | YES (rm -rf sidecar) | No |
| Does gemma3:12b meet context requirement? | YES (131K ≥ 64K) | No |
| Does it auto-create cron/services? | NO (only if gateway enabled) | No |
| Any identified blockers? | **NONE** | — |

---

## 7. Recommendation

**Hermes is compatible with Trade AI's current architecture.** No blockers identified.

### Recommended install approach

1. Project-scoped install in `hermes_sidecar/` with local venv
2. `HERMES_HOME=hermes_sidecar/.hermes` — no global config
3. Ollama as sole LLM provider — no cloud keys
4. No gateway, no cron, no systemd — manual runs only during pilot
5. Sidecar wrapper script strips all Trade AI secrets from environment
6. Phase P0 smoke test before any research generation

### What to watch during install

1. Verify `HERMES_HOME` override actually works (no `~/.hermes` created)
2. Verify no external API calls during `hermes doctor`
3. Verify gemma3:12b context window is recognized as ≥64K
4. Verify no systemd units are auto-created
5. Verify `hermes version` and `hermes doctor` run cleanly

### Next step

**Operator must explicitly approve install** with:

```text
Approve Hermes sidecar install.
```

The install will follow `docs/hermes/HERMES_INSTALL_EXECUTION_PLAN.md` exactly.
