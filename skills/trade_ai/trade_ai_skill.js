/**
 * trade_ai_skill.js — Trade AI v12 + Portfolio Intelligence Skill
 * OpenClaw / ClawHub compatible
 *
 * Actions:
 *   run          — Full 23-stage Trade AI pipeline
 *   status       — Last run summary (with macro context on zero-GO days)
 *   brief        — One-paragraph summary of last run
 *   institutional — Run with institutional flag (generates _institutional.html alongside)
 *   portfolio    — Run portfolio intelligence pipeline
 *
 * Parameters:
 *   action        : "run" | "status" | "brief" | "institutional" | "portfolio"
 *   runLabel      : e.g. "0700" (default) or "0900"
 *   macroContext  : true = force macro regime commentary on quiet days
 *   date          : "YYYY-MM-DD" (defaults to today)
 *   skipMarketCheck: true = run outside market hours (testing)
 *
 * Paths:
 *   BASE    = /home/john/trade-ai-v12-rebuild
 *   PYTHON  = /home/john/skills-env/venv/bin/python3
 *   REPORTS = {BASE}/reports/{date}/{runLabel}/run_summary.json
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
