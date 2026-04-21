# Phase 8 Investigation — Personal Situation Modal Editor
**Read-only system inventory for Command Center modal design**

---

## SECTION A: Server Architecture

### Server process
- **Python HTTP server**: `scripts/portfolio_server.py` running on port 7777 (pid 1355125)
- **No Flask/FastAPI/Express** — pure `http.server.BaseHTTPRequestHandler` subclass
- **Systemd managed**: `portfolio-server.service` (auto-restart enabled)
- **No nginx/apache proxy** — Python serves directly

### API endpoints (existing)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Redirect to command_center.html |
| GET | `/data/portfolios/state/*` | Serve state JSON files |
| GET | `/reports/*` | Serve HTML reports |
| GET | `/assets/*` | Serve YAML/config |
| GET | `/api/health` | Health check |
| GET | `/api/env/read` | Read .env fields (allowlisted) |
| POST | `/api/import` | Import positions → holdings.json |
| POST | `/api/import-transactions` | Append transactions → trade_journal.json |
| POST | `/api/run-portfolio` | Trigger daily pipeline |
| POST | `/api/run-trade-ai` | Trigger continuous runner |
| POST | `/api/run-pipeline` | Whitelisted pipeline trigger |
| POST | `/api/env/write` | Update .env (with backup) |
| POST | `/api/yaml-apply` | Apply YAML advisor suggestions |

---

## SECTION B: .env Modal Pattern (Template)

### Flow
1. **Trigger**: Button in CC Zone 4 → `onclick="openEnvModal()"`
2. **Load**: `fetch('/api/env/read')` → returns `{ok: true, fields: [{key, value, masked, sensitive}]}`
3. **Render**: Creates overlay div, iterates fields, renders input/textarea per field
4. **Save**: `saveEnvChanges(keys)` → collects values from DOM → `fetch('/api/env/write', {method:'POST', body: {updates: {key:val}}})` 
5. **Server**: Backs up `.env` to `file_backups/env_{timestamp}/`, rewrites file line-by-line, returns `{ok: true, backup: path}`

### Key design decisions in .env modal
- Modal is pure vanilla JS (no React) — createElement + innerHTML
- Fixed overlay with 560px centered card
- Fields rendered dynamically from server response
- Large fields (COOKIE/KEY/TOKEN) get `<textarea>`, others get `<input>`
- Server handles backup before write
- Confirmation dialog before save
- Allowlist (`_SHOW`) controls which values are visible vs masked

### Server endpoints involved
- `GET /api/env/read` — line 320 in portfolio_server.py
- `POST /api/env/write` — line 475 in portfolio_server.py

---

## SECTION C: Hardcoded Personal Values in AI Prompts

### Full inventory of hardcoded personal data in `scripts/portfolio_ai_analyst.py`

#### Income
| Value | Line(s) | Context |
|-------|---------|---------|
| $45,600/yr SSDI | 126, 284, 301, 360, 364, 383 | Monthly brief, Roth prompts, exec summary |
| $3,800/month SSDI | 284 | Roth conversion prompt |
| ~$20,000/yr Schedule C gross | 285, 301, 384, 411 | Tax math, income context |

#### Tax
| Value | Line(s) | Context |
|-------|---------|---------|
| MFS filing status | 289, 364 | Tax bracket calculation |
| 22% current bracket | 308, 393-394 | Conversion room math |
| 24% next bracket ceiling ~$94,300 | 308, 393 | Bracket overflow warning |
| $35K already converted 2026 | 309, 365, 387, 394 | Remaining room calculation |
| ~$16K remaining room | 309, 394 | Action recommendation |
| SE tax deduction ~$1,413/yr | 293, 306 | Income calculation |

#### Housing / Deductions
| Value | Line(s) | Context |
|-------|---------|---------|
| Mortgage interest ~$16,011/yr | 290, 391 | Itemized deductions |
| Property tax ~$7,670 | 391 | Itemized deductions |
| Federal itemized ~$21,011 | 292, 307, 391 | Taxable income calc |
| NY itemized ~$23,681 | 292 | State taxes |
| Mortgage balance ~$408,347 @ 4% | 296 | Retirement planning |
| Mortgage maturity 09/2042 | 296 | Timeline |

#### Retirement / Age
| Value | Line(s) | Context |
|-------|---------|---------|
| Age 58 (turns 59 Aug 2026) | 126, 360 | Profile context |
| Disability ends age 68.5 | 286-287, 302, 385, 406, 409 | Golden Window |
| FRA / SS at age 67 | 284, 383 | Income transition |
| RMDs at age 73 | 303, 409 | Conversion deadline |
| 401k rollover 2027 | 316 | IRA consolidation |
| Fidelity 401k $501,155 | 319 | Account balance (STALE) |
| Account numbers ...258, ...415, ...469 | 320-322 | Account IDs (STALE) |

#### Roth Strategy
| Value | Line(s) | Context |
|-------|---------|---------|
| $25K/yr sweet spot | 313, 365 | Optimal conversion |
| $50K/yr upper model | 314 | Aggressive scenario |
| $25-50K/yr during SSDI years | 301, 406 | Conversion range |
| $500K Roth by 2035 at $25K/yr | 313 | Projection |

### Existing config files
- `assets/portfolio_accounts.yaml` — has account structure, tax methods, DRIP settings, allocation targets. Does NOT contain personal income/tax/age/mortgage data.
- `config/thesis.json` — investment thesis tags
- `config/manual_beta_overrides.json` — beta values
- **No `personal_situation.yaml` or equivalent exists.**

### Proposed modal fields (grouped)

**Income (5 fields)**
- SSDI annual income
- Schedule C gross income
- Filing status (MFS/MFJ/Single)
- Private disability insurance (yes/no + end date)
- Other income sources

**Tax (6 fields)**
- Current tax bracket %
- Next bracket ceiling $
- 2026 Roth conversion done $
- Federal itemized deductions $
- SE tax deduction $
- State (NY) itemized $

**Housing (4 fields)**
- Mortgage balance $
- Mortgage rate %
- Mortgage maturity date
- Property tax annual $
- Mortgage interest annual $

**Retirement (5 fields)**
- Current age
- Date of birth
- FRA age
- Disability end age
- RMD start age

**Accounts (informational — may already be in portfolio_accounts.yaml)**
- 401k rollover year
- Account notes

---

## SECTION D: Data Storage Patterns

### Existing UI → server → file write patterns

1. **`.env` modal**: `POST /api/env/write` → reads .env, backs up, rewrites line-by-line, returns success
2. **Import positions**: `POST /api/import` → writes to `data/portfolios/state/holdings.json` via `HOLDINGS_PATH.write_text(json.dumps(data))`
3. **Import transactions**: `POST /api/import-transactions` → appends to `data/portfolios/state/trade_journal.json`
4. **YAML apply**: `POST /api/yaml-apply` → runs `portfolio_yaml_writer.py` to modify `assets/portfolio_accounts.yaml`

All writes go through `portfolio_server.py` do_POST handler. All create backups before writing. All return JSON responses.

### No separate API server
Strategy Center fetches from the same `portfolio_server.py` via `/data/portfolios/state/*` GET routes. There is no separate Express/Flask server.

---

## SECTION E: Recommendations

### 1. Where to add the API endpoint
**Extend `scripts/portfolio_server.py`** — add `GET /api/personal/read` and `POST /api/personal/write` alongside the existing `/api/env/read` and `/api/env/write`. Same pattern, same backup logic.

### 2. Where to store the data
**`config/personal_situation.json`** — NOT in `data/portfolios/state/` (which is gitignored). The personal situation is configuration, not pipeline output. Store in `config/` alongside `thesis.json` and `manual_beta_overrides.json`. This keeps it version-controlled and recoverable.

However, it contains PII (income, mortgage, age). Options:
- **(A)** `config/personal_situation.json` — tracked in git, simple, but PII in repo
- **(B)** `.personal_situation.json` in project root — gitignored like .env, more secure but needs manual backup
- **(C)** Add to `.env` as structured keys — consistent with existing secrets pattern but awkward for complex data

**Recommendation: (A)** with a `.gitignore` entry if the user prefers, or (B) if PII sensitivity is high. The data isn't truly secret (no passwords/keys), just personal.

### 3. Whether to follow the .env modal pattern
**Yes, follow it exactly** but with improvements:
- Same overlay/modal/save flow
- Add field grouping (Income / Tax / Housing / Retirement tabs or sections)
- Add field types (number, date, percentage, dropdown for filing status)
- Add validation (age must be number, dates must be valid, etc.)
- Add a "last updated" timestamp

### 4. Architectural risks
- **Stale values**: Account balances ($501K Fidelity, $531K Rollover) are hardcoded in prompts but change daily. These should NOT be in the personal situation config — they should come from live `holdings.json`. Only truly stable personal facts belong in the modal.
- **Prompt injection**: The personal values get interpolated into AI prompts. Sanitize inputs (strip special characters, validate types).
- **Multiple prompt locations**: The same values appear in 6+ prompt templates across `portfolio_ai_analyst.py`. The fix should define a single `_personal_context()` function that reads from the config file, replacing all scattered hardcoded values.
