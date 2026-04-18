

---

## 2026-04-15 — CC v48 Root Cause Analysis

### Root Cause: Dual portfolio_server.py + Cross-Version ast.parse Failure

**Incident:** Command Center v48 required 20+ iterations to deploy successfully.
Two compounding root causes were identified.

**Root Cause 1: Two copies of portfolio_server.py**

The MS-01 machine had two copies:
- `scripts/portfolio_server.py` (patched, 523 lines) — served via /scripts/* endpoint
- `portfolio_server.py` at project root (original, 242 lines)

The running process was launched via `.venv/bin/python scripts/portfolio_server.py`.
Every pkill+restart attempt killed the process, but a race condition caused the new
process to fail to bind port 7777 (old process hadn't fully released it), or the new
process started but the health check cache returned the old response.

**Resolution:** `fuser -k 7777/tcp` to force-kill the port listener, then restart with
`nohup .venv/bin/python scripts/portfolio_server.py & disown`.

**Root Cause 2: ast.parse() cross-version failure blocking all deploys**

The patch script validated `portfolio_server.py` syntax using `ast.parse()` on the
build machine (Python 3.11). The live server file contained existing f-strings with
escaped double quotes inside single-quoted f-strings (e.g., `f'...\"...'`) — valid
Python 3.12+ but rejected by Python 3.11's AST parser.

Every deploy attempt: 15 HTML patches = DONE, server write = ABORT. Files never written.
This persisted for ~15 iterations before the root cause was identified.

**Resolution:** Replace `ast.parse(full_server_file)` with targeted validation of only
the new code being added, or run validation on the target Python version (3.13 on MS-01).

**Prevention:**
- NEVER validate Python files against a different version than the target runtime
- When deploying to MS-01, always run fix scripts ON MS-01 via SSH, not from build machine
- Add `lsof -i :7777` check to deploy scripts before restart
- Use `fuser -k PORT/tcp` instead of `pkill` for port-specific kills
- Add assertion: `assert len(scripts/portfolio_server.py only ONE on system`

**Documentation updated:** CHANGES_cc_v48.md, engineering_log.md, trade-ai-v12 SKILL.md

