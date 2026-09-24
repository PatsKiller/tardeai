"use strict";
// node --test gate-core.test.js  — offline; the bridge is stubbed.
const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("./gate-core.js");

const env = { MARIA_GATE_MODE_FILE: "/nonexistent" };
const ok = (content) => async () => ({ ok: true, out: { content, changed: true, cancel: false, receipt: {} } });
const bad = async () => ({ ok: false, error: "timeout:8000ms" });
const tg = { channelId: "telegram", conversationId: "8797974247" };
const ev = (content, to = "8797974247") => ({ to, content });
const cfg = (mode) => ({ mode, logPath: "/tmp/maria-gate-test.log" });

test("live applies the rewrite for Maria's chat", async () => {
  const r = await core.handleMessageSending(ev("hi"), tg, cfg("live"), { env, runBridge: ok("GATED") });
  assert.deepEqual(r, { content: "GATED" });
});
test("observe never changes delivery", async () => {
  const r = await core.handleMessageSending(ev("hi"), tg, cfg("observe"), { env, runBridge: ok("GATED") });
  assert.equal(r, undefined);
});
test("live bridge failure delivers original + unverified line", async () => {
  const r = await core.handleMessageSending(ev("hi"), tg, cfg("live"), { env, runBridge: bad });
  assert.equal(r.content, `hi\n\n${core.UNVERIFIED_LINE}`);
});
test("other chats, other agents, other channels are out of scope", async () => {
  let called = false;
  const spy = async () => { called = true; return { ok: true, out: { content: "X" } }; };
  await core.handleMessageSending(ev("hi", "780672608"), { channelId: "telegram" }, cfg("live"), { env, runBridge: spy });
  await core.handleMessageSending(ev("hi"), { ...tg, sessionKey: "agent:aegis:cron:1" }, cfg("live"), { env, runBridge: spy });
  await core.handleMessageSending(ev("hi"), { channelId: "whatsapp" }, cfg("live"), { env, runBridge: spy });
  assert.equal(called, false);
});
test("maria session key is in scope even for another recipient", () => {
  assert.equal(core.inScope(ev("x", "1"), { channelId: "telegram", sessionKey: "agent:maria:cron:9" }, core.settings({})), true);
});
test("mode: env > config > file > observe", () => {
  assert.equal(core.resolveMode(core.settings({}), { MARIA_GATE_MODE_FILE: "/nonexistent" }), "observe");
  assert.equal(core.resolveMode(core.settings({ mode: "live" }), {}), "live");
  assert.equal(core.resolveMode(core.settings({ mode: "live" }), { MARIA_GATE_MODE: "off" }), "off");
});
test("off mode and empty content do nothing", async () => {
  assert.equal(await core.handleMessageSending(ev("hi"), tg, cfg("off"), { env, runBridge: ok("X") }), undefined);
  assert.equal(await core.handleMessageSending(ev("  "), tg, cfg("live"), { env, runBridge: ok("X") }), undefined);
});
test("real bridge timeout is enforced", async () => {
  const fs = require("node:fs"); const os = require("node:os"); const path = require("node:path");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "maria-gate-"));
  fs.writeFileSync(path.join(dir, "hang.js"), "setTimeout(() => {}, 5000);");
  const r = await core.runBridge({ ...core.settings({}), pythonBin: process.execPath, releaseRoot: dir, bridgeRelPath: "hang.js", timeoutMs: 600 }, {});
  assert.equal(r.ok, false);
  assert.match(r.error, /^timeout/);
});
