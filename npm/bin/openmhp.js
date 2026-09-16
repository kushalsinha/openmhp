#!/usr/bin/env node
/* openmhp: one command to run the OpenMHP MCP server in any agent harness.
 *
 *   npx openmhp-cli                 start the MCP server on stdio (what harness configs run)
 *   npx openmhp-cli setup           install the Python runtime, the skills, and register with your harnesses
 *   npx openmhp-cli node [folder]   turn THIS computer into a lightweight OpenMHP node for its instruments
 *   npx openmhp-cli scan [host...]  find MHP devices on the network
 *   npx openmhp-cli add <target>    add a device (http://host:port or a device package folder)
 *   npx openmhp-cli demo            add two simulated instruments to try things without hardware
 *   npx openmhp-cli list | remove <id> | validate <folder> | device <folder> [--http PORT] | update
 *
 * Everything lives in ~/.openmhp (venv, fleet.json, devices/). The Python package
 * does the work; this launcher only makes sure it exists. Logs go to stderr because
 * stdout is the MCP channel.
 */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const { HOME, log, ensureRuntime, run, tool } = require("../lib/runtime");
const { nodeSetup } = require("../lib/node_setup");

function setup() {
  ensureRuntime();
  log("installing Agent Skills into the harnesses found on this machine");
  run("mhp", ["skills", "install"]);
  const npx = process.platform === "win32" ? "npx.cmd" : "npx";
  const registered = [];
  // Claude Code
  if (require("child_process").spawnSync("claude", ["--version"], { encoding: "utf8" }).status === 0) {
    const r = require("child_process").spawnSync("claude", ["mcp", "add", "--scope", "user", "openmhp", "--", npx, "-y", "openmhp-cli"], { encoding: "utf8" });
    if (r.status === 0 || /already exists/i.test(r.stderr + r.stdout)) registered.push("Claude Code");
  }
  // Codex
  const codex = path.join(os.homedir(), ".codex", "config.toml");
  if (fs.existsSync(path.dirname(codex))) {
    const cur = fs.existsSync(codex) ? fs.readFileSync(codex, "utf8") : "";
    if (!/\[mcp_servers\.openmhp\]/.test(cur)) {
      fs.appendFileSync(codex, `\n[mcp_servers.openmhp]\ncommand = "${npx}"\nargs = ["-y", "openmhp-cli"]\n`);
    }
    registered.push("Codex");
  }
  console.error("");
  log(registered.length ? `registered with: ${registered.join(", ")}` : "no harness config written automatically");
  log("for any other MCP-capable harness (OpenClaw, Hermes, Claude Science, Open Science, ...) add:");
  console.error(JSON.stringify({ mcpServers: { openmhp: { command: "npx", args: ["-y", "openmhp-cli"] } } }, null, 2));
  console.error("");
  log("next: open your agent and say \"find the instruments on my network\" or \"onboard my hotplate\".");
  log(`lab lives in ${HOME}`);
}

function main() {
  const [cmd = "serve", ...rest] = process.argv.slice(2);
  switch (cmd) {
    case "serve": case "mcp":
      ensureRuntime();
      { const child = spawn(tool("mhp-mcp"), ["--fleet", path.join(HOME, "fleet.json"), ...rest], { stdio: "inherit" });
        child.on("exit", (c) => process.exit(c ?? 0)); }
      return;
    case "setup": return setup();
    case "node": return nodeSetup(rest).catch((e) => { log(String(e)); process.exit(1); });
    case "update": return ensureRuntime({ upgrade: true });
    case "scan": case "add": case "remove": case "list": case "demo":
      ensureRuntime(); process.exit(run("mhp", ["lab", cmd, ...rest]));
    case "validate": ensureRuntime(); process.exit(run("mhp", ["validate", ...rest]));
    case "skills": ensureRuntime(); process.exit(run("mhp", ["skills", ...rest]));
    case "device": ensureRuntime(); process.exit(run("mhp", ["serve", `pkg:${path.resolve(rest[0])}`, ...rest.slice(1)]));
    case "mhp": ensureRuntime(); process.exit(run("mhp", rest));
    case "home": console.log(HOME); return;
    case "-h": case "--help": case "help":
      console.log(fs.readFileSync(__filename, "utf8").split("*/")[0].split("\n").slice(1).map((l) => l.replace(/^ \* ?/, "")).join("\n"));
      return;
    default:
      log(`unknown command ${cmd}; try --help`); process.exit(2);
  }
}

main();
