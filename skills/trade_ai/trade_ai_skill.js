/**
 * trade_ai_skill.js — Trade AI v12 + Portfolio Intelligence Skill
 * Bible v7.5 | OpenClaw / ClawHub compatible | May 8, 2026 | Session 24C
 *
 * Actions:
 *   run          — Full 23-stage Trade AI pipeline (Finviz → scoring → GO/WAIT)
 *   status       — Last run summary (with macro context on zero-GO days)
 *   brief        — One-paragraph summary of last run
 *   institutional — Run with institutional flag (generates _institutional.html)
 *   portfolio    — Run portfolio intelligence pipeline
 *
 * Parameters:
 *   action        : "run" | "status" | "brief" | "institutional" | "portfolio"
 *   runLabel      : e.g. "0700" (default) or "0900"
 *   macroContext  : true = force macro regime commentary on quiet days
 *   date          : "YYYY-MM-DD" (defaults to today)
 *   skipMarketCheck: true = run outside market hours (testing)
 *
 * ─── SYSTEM STATE (verified May 2, 2026) ───────────────────────────────────
 *
 *   Server:  ms01-openclaw (Ubuntu) | SSH johnclaw@192.168.50.16
 *   Root:    /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
 *   Port:    7777 (portfolio_server.py)
 *   DB:      PostgreSQL trade_ai — 219 tables (user: trade_ai)
 *   API:     ~125 endpoints (api_v2.py) — incl. strategy-configs, lifecycle, TCA, governance
 *   Agents:  7 registered (maria, steph, risk_agent, tax_agent, alex, aegis, iris)
 *   Models:  qwen3:14b (local, Intel Arc B50 Vulkan, 90s timeout) + Claude Sonnet + Grok fallback
 *   Crons:   127 entries (incl. proposal_monitor 4x/day, TCA, reconciler, governance)
 *   RAG:     5,610 items embedded (99.98%)
 *   Social:  443 posts (StockTwits 279, Reddit 161, X 3)
 *   Scripts: 290 Python files
 *   YAMLs:   23 strategy config files (20 strategies + schema + shared rules + recommendation)
 *   Holdings: $1,189,220 / 47 positions
 *
 * ─── SESSION 23D ADDITIONS ─────────────────────────────────────────────────
 *
 *   OHLCV Cache:  market_ohlcv_bars table (55K+ bars, yfinance + Polygon)
 *   EMA Engine:   EMA 8/21/50/200 from daily bars, alignment classification
 *   Fib Engine:   fib_swing_engine.py — 60-day swing high/low, 7 retracement/extension levels
 *   ORB Engine:   opening_range_engine.py — 5/15/30min ORB + premarket levels
 *   Tech Grade:   TECH_STRONG/OK/MIXED/WEAK/INCOMPLETE scoring
 *   Bracket:      Alpaca paper bracket dry-run + submit with full gate validation
 *   API:          6 new endpoints (run-fib, run-opening-range, run-technical-snapshot,
 *                 dry-run-alpaca-bracket, submit-alpaca-paper-bracket, technical-diagnostics)
 *   UI:           Tech Map tab (EMA stack, Fib, ORB/premarket), bracket controls
 *
 * ─── SESSION 23E ADDITIONS ─────────────────────────────────────────────────
 *
 *   Quote Provider: market_quote_provider.py — multi-provider hierarchy:
 *                   Alpaca snapshot > Polygon > Finnhub > FMP > yfinance > Finviz cache
 *   Quote Table:    market_quote_snapshots (bid/ask/spread/volume/exec_eligible per provider)
 *   Readiness Fix:  Finviz cache removed as execution quote source
 *                   Spread no longer defaults to pass when bid/ask missing
 *                   BLOCKED_SPREAD_UNKNOWN / BLOCKED_NO_QUOTE / BLOCKED_NO_VOLUME states
 *   Tech Primary:   proposal_technical_snapshots is now primary for indicators_ok
 *                   indicator_confluence_cache is fallback only
 *   Backtest Label: BACKTEST_SAMPLE_INSUFFICIENT_LEARNING_MODE (honest, no false pass)
 *   UI:             Quote Source section (provider, bid/ask, spread, exec eligible, volume)
 *   Git Hygiene:    Removed 82 tracked artifacts (reports/, .bak, docx_patch_)
 *
 * ─── SESSION 24A/24B/24B.1 ADDITIONS ──────────────────────────────────────
 *
 *   Lifecycle:      proposal_lifecycle.py — 20-strategy expiry map (8h-720h)
 *                   intraday (scalp/gap) expire EOD, swing/position monitored overnight
 *                   entry zone tracking, price drift, extension rules (max 2x, capped 720h)
 *   Monitor:        proposal_monitor.py — AH/PM/market checks (4:30PM, 6PM, 6AM, 6:30AM)
 *                   price drift, entry zone validity, expiry extension, lifecycle events
 *   TCA:            paper_execution_quality_analyzer.py — slippage, fill quality (EXCELLENT-UNKNOWN)
 *   Reconciler:     alpaca_paper_reconciler.py — Alpaca vs local paper_trades matching
 *   Thesis:         post_trade_thesis_reviewer.py — expected vs actual entry/exit/R comparison
 *   Governance:     paper_performance_governance.py — per-strategy win rate, expectancy, PF
 *                   States: PAPER_ONLY → WATCHLIST → CANDIDATE_FOR_REVIEW → LIVE_ELIGIBLE
 *                   Live always blocked: "Requires six months of validated paper results"
 *   Schema:         6 new tables (lifecycle_events, execution_quality, recon_runs/items,
 *                   thesis_outcomes, performance_governance) + 17 lifecycle columns
 *   API:            8 new endpoints (live-price, monitor, lifecycle-events, execution-quality,
 *                   broker-reconciliation, governance, reconciliation/run, execution-quality/run)
 *   UI:             Lifecycle bar on every proposal card (status, zone, drift, class, provider)
 *   Crons:          proposal_monitor 4x/day, reconciler 4:15PM, TCA 4:30PM, governance monthly
 *
 * ─── SESSION 24B: STRATEGY PLAYBOOK ────────────────────────────────────────
 *
 *   Playbook:       docs/project/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md + config/ copy
 *   YAMLs:          20 strategy configs in config/strategies/ + shared_risk_rules + schema
 *   Config Loader:  strategy_config_loader.py — validate, sync to DB, prompt context builder
 *   Multi-Setup:    multi_setup_router.py — evaluates all 20 strategies per symbol, setup stacks
 *   DB Tables:      strategy_config_versions, strategy_setup_matches, strategy_prompt_context_cache
 *   Agent Prompts:  Strategy context injected into Maria/Risk/Steph + qwen3:14b LLM prompts
 *   API:            GET /api/v2/strategy-configs, GET /api/v2/strategy-setup-matches,
 *                   POST /api/v2/strategy-configs/validate, POST /api/v2/strategy-configs/sync-db
 *   UI Pages:       Strategy Admin (/v2/strategy-admin), Live Governance (/v2/live-governance)
 *
 * ─── SESSION 24B.1: COMMAND CENTER REDESIGN ────────────────────────────────
 *
 *   PaperProposals: Complete rewrite as institutional command center (1465 lines)
 *   Normalizer:     normalizeProposal() computes actionState, topBlocker, nextActions, dataQuality
 *   Card Design:    Decision banner, 8 metric tiles, strategy-first header, color-coded states
 *   Data Fixes:     Strategy mismatch detection, EMA alignment guard, confidence clamping,
 *                   quote freshness override, spread unknown handling, missing data by section
 *   Filters:        Strategy dropdown, action state, symbol search, show all/top 5
 *   Enrich All:     Async 8-step pipeline with live status polling
 *   New Pages:      Execution Quality, Broker Reconciliation, Paper Outcomes
 *   Scroll Fix:     theme.css height:100% → min-height:100vh
 *   LLM Timeout:    llm_router LOCAL_TIMEOUT 30s → 90s for agent prompts
 *   Telegram:       WAIT/AVOID alerts suppressed (GO only)
 *
 * ─── KEY ENDPOINTS (verified working) ──────────────────────────────────────
 *
 *   POST /api/v2/proposals/decide    — approve/reject watchlist proposals
 *     Body: {id, decision: "approved"/"rejected", reason, reviewer}
 *     Updates: watchlist_proposals + agent_feedback_log
 *
 *   POST /api/v2/john/decide         — resolve tasks (john_decision_queue)
 *     Body: {id, status, decision, reasoning, revisit_on, followup}
 *     Valid statuses: decided_action, deferred, rejected, revisit_later, closed
 *     Updates: john_decision_queue + john_decision_history
 *
 *   GET /api/v2/weekly-report        — 7-day agent activity + decisions + social
 *   GET /api/v2/monthly-report       — 30-day summary
 *   GET /api/v2/debates              — agent_debate_log (conflict resolutions)
 *
 * ─── TELEGRAM COMMANDS (21 total) ──────────────────────────────────────────
 *
 *   approve proposal <id> [reason]   — approve watchlist proposal → feedback_log
 *   reject proposal <id> [reason]    — reject watchlist proposal → feedback_log
 *   approve task <id> [decision]     — resolve john_decision_queue item
 *   reject task <id> [reason]        — reject task
 *   proposals                        — list pending proposals
 *   tasks                            — list pending tasks
 *   debates                          — list agent debates
 *   (+ 14 existing: status, tax, intel, alex, iris, conflicts, etc.)
 *
 * ─── AUTONOMOUS PIPELINE ───────────────────────────────────────────────────
 *
 *   6:25 AM  — agent batch (maria + steph + risk on all holdings)
 *   6:35 AM  — tax sweep (harvest candidates + SSDI proposals)
 *   6:50 AM  — RAG indexer (news, FRED, social, SEC)
 *   7:30 AM  — social_ingest.py --source all (holdings + StockTwits discovery + Reddit discovery)
 *   8:00 PM  — aegis overnight (synthesis + stops + escalations + proposals)
 *   Conflict detected → auto-debate (run_agent_debate) → Telegram alert
 *
 * ─── SOCIAL DISCOVERY (two-way) ────────────────────────────────────────────
 *
 *   Mode 1: Portfolio holdings — fetch sentiment for current positions
 *   Mode 2: StockTwits trending — what's hot across all markets
 *   Mode 3: Strategy discovery — 5 watchlists:
 *     dividend_growth: SCHD, VYM, DGRO, VIG, HDV, DIVO, JEPI, JEPQ, O, MAIN
 *     defense_aerospace: LMT, NOC, RTX, LHX, GD, BA, HII, TDG, LDOS, BAH
 *     growth_tech: NVDA, MSFT, AAPL, GOOGL, META, AMZN, TSM, AVGO, AMD, CRM
 *     retirement_income: SCHD, VZ, T, MO, PM, KO, PEP, JNJ, PG, MMM
 *     sector_rotation: XLF, XLE, XLK, XLV, XLI, XLU, XLP, XLB, XLRE, XLC
 *   Mode 4: Reddit ticker extraction — finds $TICKER mentions in hot posts
 *     Subreddits: r/dividends, r/investing, r/retirement, r/financialindependence,
 *                 r/stocks, r/ValueInvesting
 *
 * ─── OPERATIONS ────────────────────────────────────────────────────────────
 *
 *   Bible: docs/project/TRADE_AI_V12_SYSTEM_BIBLE_V3.md (v7.3)
 *   Restart: pkill -f portfolio_server.py; nohup .venv/bin/python scripts/portfolio_server.py > logs/portfolio_server.log 2>&1 &
 *   Safety: python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); assert d['portfolio_totals']['total_value']>1000000"
 *   Preflight: python3 scripts/system_preflight_check.py
 *
 * Paths (Linux — ms01-openclaw):
 *   BASE    = /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
 *   PYTHON  = {BASE}/.venv/bin/python
 *   REPORTS = {BASE}/reports/{date}/{runLabel}/run_summary.json
 *
 * NOTE: The skill's BASE/PYTHON below still point to old Windows paths
 * (/home/john/) because OpenClaw gateway reads from that location.
 * The actual live system is at /home/johnclaw/... — see above.
 */

"use strict";

const { exec, execSync } = require("child_process");
const fs   = require("fs");
const path = require("path");

// ── Configuration ────────────────────────────────────────────────────────────
const BASE   = "/home/john/trade-ai-v12-rebuild";
const PYTHON = "/home/john/skills-env/venv/bin/python3";
const TIMEOUT_MS = 660000; // 11 minutes

// ── Helpers ───────────────────────────────────────────────────────────────────
function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function loadSummary(date, runLabel) {
  const p = path.join(BASE, "reports", date, runLabel, "run_summary.json");
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, "utf8")); }
  catch (e) { return null; }
}

function latestRunDate() {
  const reportsDir = path.join(BASE, "reports");
  if (!fs.existsSync(reportsDir)) return null;
  const dates = fs.readdirSync(reportsDir)
    .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d))
    .sort()
    .reverse();
  return dates[0] || null;
}

function formatSummary(s, macroContext) {
  if (!s) return "No recent run data found.";

  const go    = s.go_count || 0;
  const wait  = s.wait_count || 0;
  const total = s.ticker_count || 0;
  const top   = s.top_ticker || "—";
  const vix   = s.vix ? s.vix.toFixed(1) : "N/A";
  const bread = s.breadth || "Neutral";
  const date  = s.date || s.run_label || "—";

  let out = `⚡ Trade AI v12 | ${date} ${s.run_label || ""}\n`;
  out += `📊 ${total} scanned · GO: ${go} · WAIT: ${wait} · VIX ${vix} · ${bread}\n`;

  if (go > 0) {
    out += `🎯 Top: ${top} (score ${s.top_score || "—"})\n`;
  }

  if (go === 0 && macroContext) {
    const vixDesc = parseFloat(vix) > 25 ? "elevated fear"
                  : parseFloat(vix) > 18 ? "moderate caution"
                  : "low fear";
    out += `\n📉 Market Regime: Quiet consolidation — 0 GO setups.\n`;
    out += `VIX ${vix} (${vixDesc}), breadth ${bread}.\n`;
    out += `No high-conviction scalp setups this run. `;
    out += `Watch for catalyst rotation or VIX compression.\n`;
  }

  return out.trim();
}

// ── Main skill entry point ────────────────────────────────────────────────────
module.exports = {
  name: "trade-ai-v12",
  description: [
    "Institutional-grade Trade AI v12 + Portfolio Intelligence runner.",
    "Supports --brief, --institutional, --macro-context.",
    "Actions: run | status | brief | institutional | portfolio"
  ].join(" "),

  parameters: {
    type: "object",
    properties: {
      action: {
        type: "string",
        enum: ["run", "status", "brief", "institutional", "portfolio"],
        description: "run=full pipeline · brief=1-para summary · institutional=hedge-fund format · portfolio=portfolio pipeline"
      },
      runLabel: {
        type: "string",
        description: "Run label (e.g. 0700, 0900). Default: 0700"
      },
      macroContext: {
        type: "boolean",
        description: "Force macro regime commentary on zero-GO days"
      },
      date: {
        type: "string",
        description: "Date override YYYY-MM-DD (default: today)"
      },
      skipMarketCheck: {
        type: "boolean",
        description: "Skip market hours check (for testing)"
      }
    },
    required: []
  },

  async run({
    action        = "status",
    runLabel      = "0700",
    macroContext  = false,
    date          = todayStr(),
    skipMarketCheck = false
  } = {}) {

    // ── STATUS ──────────────────────────────────────────────────────────────
    if (action === "status") {
      const useDate = date || latestRunDate() || todayStr();
      const s = loadSummary(useDate, runLabel)
             || loadSummary(todayStr(), runLabel)
             || (() => {
               const d = latestRunDate();
               return d ? loadSummary(d, runLabel) : null;
             })();
      return formatSummary(s, macroContext);
    }

    // ── BRIEF ───────────────────────────────────────────────────────────────
    if (action === "brief") {
      const s = loadSummary(date, runLabel) || loadSummary(todayStr(), runLabel);
      if (!s) return "No run data found for today. Run 'run' action first.";
      const go  = s.go_count || 0;
      const top = s.top_ticker;
      if (go === 0) {
        return `Trade AI ${s.date} ${runLabel}: 0 GO setups. VIX ${(s.vix||0).toFixed(1)}, breadth ${s.breadth||"Neutral"}. Quiet session — no scalp opportunities today.`;
      }
      return `Trade AI ${s.date} ${runLabel}: ${go} GO | ${s.wait_count||0} WAIT | ${s.ticker_count||0} scanned. Top: ${top} (${s.top_score}). VIX ${(s.vix||0).toFixed(1)}.`;
    }

    // ── RUN / INSTITUTIONAL ─────────────────────────────────────────────────
    if (action === "run" || action === "institutional") {
      return new Promise((resolve) => {
        const flags = [
          `--run-label ${runLabel}`,
          `--date ${date}`,
          action === "institutional" ? "--institutional" : "",
          skipMarketCheck ? "--skip-market-check" : "",
        ].filter(Boolean).join(" ");

        const cmd = `cd "${BASE}" && "${PYTHON}" scripts/trade_ai_orchestrator.py ${flags}`;

        exec(cmd, { timeout: TIMEOUT_MS }, (err, stdout, stderr) => {
          // Parse run summary regardless of error
          const s = loadSummary(date, runLabel);

          if (err && !s) {
            return resolve(`❌ Trade AI run failed:\n${stderr || err.message}`);
          }

          const go   = s ? (s.go_count || 0) : "?";
          const top  = s ? (s.top_ticker || "—") : "—";
          const mode = action === "institutional" ? " [INSTITUTIONAL]" : "";

          let out = `✅ Trade AI${mode} ${runLabel} completed | ${date}\n`;
          out += `GO: ${go} · Top: ${top}\n`;
          if (s && s.html_path) out += `Dashboard: ${s.html_path}\n`;
          if (action === "institutional") {
            const instPath = (s?.html_path || "").replace(".html", "_institutional.html");
            if (fs.existsSync(instPath)) out += `Institutional: ${instPath}\n`;
          }
          resolve(out.trim());
        });
      });
    }

    // ── PORTFOLIO ──────────────────────────────────────────────────────────
    if (action === "portfolio") {
      return new Promise((resolve) => {
        const cmd = `cd "${BASE}" && "${PYTHON}" scripts/portfolio_orchestrator.py`;
        exec(cmd, { timeout: TIMEOUT_MS }, (err, stdout, stderr) => {
          if (err && err.code !== 0) {
            // Check if dashboard was still generated
            const dashPath = path.join(BASE, "reports", "portfolio_live.html");
            if (fs.existsSync(dashPath)) {
              return resolve(`⚠️ Portfolio pipeline completed with warnings.\nDashboard: ${dashPath}\n\nStderr: ${(stderr||"").slice(0,200)}`);
            }
            return resolve(`❌ Portfolio pipeline failed:\n${(stderr||err.message||"").slice(0,300)}`);
          }
          resolve(`✅ Portfolio pipeline complete.\nDashboard: ${path.join(BASE, "reports", "portfolio_live.html")}`);
        });
      });
    }

    return `Unknown action: ${action}. Valid actions: run, status, brief, institutional, portfolio`;
  }
};
