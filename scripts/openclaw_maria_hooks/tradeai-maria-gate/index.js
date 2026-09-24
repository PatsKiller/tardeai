"use strict";
/**
 * OpenClaw plugin entry: tradeai-maria-gate.
 * Registers one message_sending hook; all logic lives in gate-core.js.
 * Operator decision 2026-09-23: "hook Maria through the gateway".
 */
const core = require("./gate-core.js");

const configSchema = {
  safeParse(value) {
    if (value === undefined) return { success: true, data: undefined };
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { success: false, error: { issues: [{ path: [], message: "expected config object" }] } };
    }
    return { success: true, data: value };
  },
  jsonSchema: require("./openclaw.plugin.json").configSchema,
};

const entry = {
  id: "tradeai-maria-gate",
  name: "Trade-AI Maria Gate",
  description: "Trade-AI house gate on Maria's outbound messages.",
  configSchema,
  register(api) {
    const cfg = core.settings(api.pluginConfig);
    api.on(
      "message_sending",
      (event, ctx) => core.handleMessageSending(event, ctx, api.pluginConfig),
      // Runs first so later hooks see the gated text; budget above the bridge timeout.
      { priority: 1000, timeoutMs: cfg.timeoutMs + 2000 },
    );
    if (api.logger && typeof api.logger.info === "function") {
      api.logger.info(`tradeai-maria-gate registered (release ${cfg.releaseRoot})`);
    }
  },
};

module.exports = entry;
module.exports.default = entry;
