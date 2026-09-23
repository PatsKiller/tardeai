"use strict";
/**
 * tradeai-maria-gate — pure logic (testable without the gateway).
 *
 * Scope: Maria's outbound only. OpenClaw's Telegram delivery path calls
 * message_sending with ctx {channelId, accountId, conversationId} and NO
 * sessionKey, so scope is: channel allowed AND (sessionKey starts with the
 * Maria prefix, or — when no sessionKey — the recipient chat is Maria's).
 * Any other agent's session key is skipped. The CIO Telegram desk is a separate
 * Python bot and never passes through OpenClaw.
 *
 * AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
 */
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

const HOME = os.homedir();
const DEFAULTS = Object.freeze({
  mode: "",
  modeFile: path.join(HOME, ".config", "tradeai", "maria_gate_mode"),
  pythonBin: path.join(HOME, "trade-ai-v12-rebuild", "trade-ai-v12-rebuild", ".venv", "bin", "python"),
  releaseRoot: path.join(HOME, "trade-ai-releases", "portfolio-server", "CURRENT"),
  bridgeRelPath: path.join("scripts", "maria_outbound_gate.py"),
  timeoutMs: 8000,
  channels: ["telegram"],
  chatIds: ["8797974247"],
  sessionKeyPrefix: "agent:maria:",
  logPath: path.join(HOME, ".local", "state", "tradeai", "maria_gate_plugin.log"),
});
const UNVERIFIED_LINE = "⚠️ unverified — house gate unavailable";
const MODES = new Set(["off", "observe", "live"]);

function settings(pluginConfig, env = process.env) {
  const c = { ...DEFAULTS, ...(pluginConfig || {}) };
  if (env.MARIA_GATE_PYTHON) c.pythonBin = env.MARIA_GATE_PYTHON;
  if (env.MARIA_GATE_RELEASE_ROOT) c.releaseRoot = env.MARIA_GATE_RELEASE_ROOT;
  if (env.MARIA_GATE_MODE_FILE) c.modeFile = env.MARIA_GATE_MODE_FILE;
  return c;
}

/** env MARIA_GATE_MODE > config.mode > mode file > "observe". */
function resolveMode(cfg, env = process.env) {
  const pick = (v) => String(v || "").trim().toLowerCase();
  const fromEnv = pick(env.MARIA_GATE_MODE);
  if (MODES.has(fromEnv)) return fromEnv;
  const fromCfg = pick(cfg.mode);
  if (MODES.has(fromCfg)) return fromCfg;
  try {
    const first = pick(fs.readFileSync(cfg.modeFile, "utf8").split(/\r?\n/)[0]);
    if (MODES.has(first)) return first;
  } catch (_e) {
    /* missing file → default */
  }
  return "observe";
}

function inScope(event, ctx, cfg) {
  const channel = String((ctx && ctx.channelId) || (event && event.metadata && event.metadata.channel) || "");
  if (!cfg.channels.includes(channel)) return false;
  const sk = String((ctx && ctx.sessionKey) || "");
  if (sk) return sk.startsWith(cfg.sessionKeyPrefix);
  const to = String((event && event.to) || (ctx && ctx.conversationId) || "").replace(/^tg:/, "");
  return cfg.chatIds.includes(to);
}

function log(cfg, row) {
  try {
    fs.mkdirSync(path.dirname(cfg.logPath), { recursive: true });
    fs.appendFileSync(cfg.logPath, JSON.stringify({ ts: new Date().toISOString(), ...row }) + "\n");
  } catch (_e) {
    /* logging never blocks delivery */
  }
}

/** Run the bridge. Resolves {ok, out|error}. Never rejects. */
function runBridge(cfg, payload) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (r) => {
      if (!done) {
        done = true;
        resolve(r);
      }
    };
    let child;
    try {
      child = spawn(cfg.pythonBin, [path.join(cfg.releaseRoot, cfg.bridgeRelPath)], {
        cwd: cfg.releaseRoot,
        env: { ...process.env, TRADEAI_ROOT: cfg.releaseRoot },
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (e) {
      finish({ ok: false, error: `spawn:${e && e.message}` });
      return;
    }
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch (_e) {
        /* already gone */
      }
      finish({ ok: false, error: `timeout:${cfg.timeoutMs}ms` });
    }, cfg.timeoutMs);
    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));
    child.on("error", (e) => {
      clearTimeout(timer);
      finish({ ok: false, error: `spawn:${e && e.message}` });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      let parsed = null;
      try {
        parsed = JSON.parse(stdout.trim().split(/\r?\n/).pop() || "null");
      } catch (_e) {
        parsed = null;
      }
      if (code === 0 && parsed && typeof parsed.content === "string") {
        finish({ ok: true, out: parsed });
      } else {
        const why = (parsed && parsed.error) || stderr.trim().slice(-300) || `exit:${code}`;
        finish({ ok: false, error: String(why) });
      }
    });
    child.stdin.on("error", () => {});
    child.stdin.end(JSON.stringify(payload));
  });
}

/**
 * The message_sending handler. Returns undefined (no decision) or
 * {content} / {cancel, cancelReason}. Never throws; never drops silently.
 */
async function handleMessageSending(event, ctx, pluginConfig, deps = {}) {
  const cfg = settings(pluginConfig, deps.env || process.env);
  const content = event && typeof event.content === "string" ? event.content : "";
  if (!content.trim()) return undefined;
  if (!inScope(event, ctx, cfg)) return undefined;
  const mode = resolveMode(cfg, deps.env || process.env);
  if (mode === "off") return undefined;
  const payload = {
    content,
    sessionKey: (ctx && ctx.sessionKey) || "",
    channel: (ctx && ctx.channelId) || "",
    to: String((event && event.to) || ""),
    mode,
  };
  const r = await (deps.runBridge || runBridge)(cfg, payload);
  if (!r.ok) {
    log(cfg, { event: "bridge_error", mode, error: r.error, to: payload.to });
    if (mode === "live") return { content: `${content}\n\n${UNVERIFIED_LINE}` };
    return undefined;
  }
  const out = r.out;
  log(cfg, {
    event: "gated", mode, to: payload.to, changed: !!out.changed,
    held: !!(out.receipt && out.receipt.held), guid: out.receipt && out.receipt.message_guid,
  });
  if (mode !== "live") return undefined;
  if (out.cancel) return { cancel: true, cancelReason: out.cancel_reason || "tradeai_maria_gate" };
  if (out.content !== content) return { content: out.content };
  return undefined;
}

module.exports = {
  DEFAULTS,
  UNVERIFIED_LINE,
  handleMessageSending,
  inScope,
  resolveMode,
  runBridge,
  settings,
};
