# Implementation Constraints

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

---

## Architecture Constraints

### Frontend
- **Framework:** React 18+ with React Router v6 (BrowserRouter, basename `/v2`)
- **Build:** Vite (tsconfig.json + vite.config.ts)
- **Styling:** CSS Modules (Shell.module.css) + global CSS (theme.css) + inline styles
- **State:** No global state management (no Redux, Zustand, etc.) -- data is per-page via `useApi` hook
- **Charting:** Chart.js (via react-chartjs-2) -- BarChartJS, DoughnutChart, LineChart
- **Lazy loading:** All page components are `React.lazy()` loaded
- **Error handling:** Per-page ErrorBoundary wrapper (SafePage)

### Backend
- **Server:** Plain Python HTTP server (`portfolio_server.py`) on port 7777
- **API:** Single-file dispatch (`api_v2.py`) with `handle(path, method, body, query)` function
- **Database:** PostgreSQL (via `db_adapter.py`)
- **No framework:** No Flask/FastAPI/Django -- raw BaseHTTPRequestHandler
- **Monolith:** ~18,000+ lines in api_v2.py

### Deployment
- **Single server:** Everything runs on one machine
- **No CDN:** Static assets served by the Python HTTP server
- **No CI/CD:** Manual builds via `npm run build` in `apps/command-center-v2/`
- **No auth:** Optional basic auth in portfolio_server.py

---

## What CANNOT Change Without Major Effort

1. **API envelope format** (`{ok, data}`) -- all pages depend on this
2. **Route structure under `/v2/`** -- external links and bookmarks
3. **useApi hook contract** -- 30+ pages depend on it
4. **Python HTTP server** -- rewriting to FastAPI would be a multi-day effort
5. **PostgreSQL schema** -- API queries depend on table structures

## What CAN Change Safely

1. **CSS tokens/theme** -- centralized in theme.css
2. **Nav structure** -- Shell.tsx NAV_GROUPS array
3. **Page consolidation** -- TabPage pattern already proven
4. **Component extraction** -- shared components already exist
5. **Route additions/removals** -- App.tsx is the single source
6. **Legacy redirect cleanup** -- can remove old routes anytime

---

## Performance Constraints

- **No SSR/ISR** -- fully client-rendered SPA
- **No service worker** -- no offline support
- **No API caching layer** -- each useApi call is independent
- **Overview page: 18 API calls** -- heaviest page
- **ATM page: 6 API calls at 15s polling** -- most frequent poller
- **api_v2.py: 18K+ lines** -- import time is non-trivial

---

## Browser Support

- Modern browsers only (no IE11)
- CSS custom properties used throughout
- `backdrop-filter: blur()` in header (requires Chrome 76+, Firefox 103+)
- Optional: Web Speech API (types/speech.d.ts)

---

## Development Workflow

1. Edit source in `apps/command-center-v2/src/`
2. Build: `cd apps/command-center-v2 && npm run build`
3. Dist goes to `apps/command-center-v2/dist/`
4. Server serves from dist directory
5. No hot-reload in production -- must rebuild

---

## Non-Negotiable Rules (from operator memory)

1. Every code/schema/pipeline change requires full doc audit
2. No silent failures -- errors must surface
3. Prop desk quality standard -- every page must justify itself
4. Intelligence must surface automatically
5. Paper trading pipeline is fully autonomous -- do not break safety gates
6. Stop v2 system is critical -- do not modify without explicit approval
