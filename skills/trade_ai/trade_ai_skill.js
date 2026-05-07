/**
 * trade_ai_skill.js — Trade AI v12 + Portfolio Intelligence Skill
 * Bible v7.4 | OpenClaw / ClawHub compatible | May 6, 2026
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
 *   DB:      PostgreSQL trade_ai — 164 tables (user: trade_ai)
 *   API:     116+ endpoints (api_v2.py)
 *   Agents:  7 registered (maria, steph, risk_agent, tax_agent, alex, aegis, iris)
 *   Models:  qwen3:14b (local, Intel Arc B50 Vulkan) + Claude Sonnet (alex/iris) + Grok fallback
 *   Crons:   75 entries (incl. tax-sweep 6:35, social 7:30, RAG 6:50)
 *   RAG:     5,610 items embedded (99.98%)
 *   Social:  443 posts (StockTwits 279, Reddit 161, X 3)
 *   Holdings: $1,193,911 / 47 positions
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
