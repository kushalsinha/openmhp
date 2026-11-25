#!/usr/bin/env node
/* openmhp: one command to run the OpenMHP MCP server in any agent harness.
 * Install it once with `npm install -g openmhp-cli`: that also puts `mhp` and `mhp-mcp` on PATH, the same
 * commands a pip install gives, so every `mhp ...` in the docs works as written. Without installing, start it
 * as `npx -y openmhp-cli@latest ...` (plain `npx openmhp-cli` reuses whatever launcher npx cached first).
 *
 * On the agent's machine (a scientist's laptop):
 *   setup                    install the Python runtime and the skills, register with Claude Code and Codex
 *   update                   upgrade the runtime and the skills
 *   demo                     add two simulated instruments to try things without hardware
 *   join <url> <code> --name <you>   use a lab gateway (code from `mhp gateway pair-agent` there)
 *   (no command)             start the MCP server on stdio: what harness configs run
 *   scan [host...] | add <target> | list | remove <id> | validate <folder> | device <folder> [--http PORT]
 *
 * On an instrument PC (no agent needed):
 *   node add [<package>]     list the ready-made packages, or fetch one, ask its questions, pair, keep it running
 *   node setup <package>     ask a package's questions again
 *   node [folder]            serve every package in a folder in the background, across reboots
 *   node --service-status | --uninstall-service | --check
 *
 * Anywhere:
 *   guide [topic | search <words>]   the user guide, shipped with the package (no web access needed)
 *   --version                this launcher, and the OpenMHP runtime it runs
 *
 * The lab gateway is set up with pip (`pip install -U openmhp`, then `mhp gateway init`); see openmhp.com/gateway.
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
const { HOME, KIND, log, ensureRuntime, recordKind, run, tool } = require("../lib/runtime");
const { nodeSetup } = require("../lib/node_setup");
const SELF = require("../package.json").version;

// npx keeps the first launcher it fetched for `npx openmhp-cli`, so an old one can linger for months.
// Ask the registry once (3 s at most) and say so, rather than set up with old instructions.
function newerLauncher() {
  return new Promise((resolve) => {
    if (process.env.OPENMHP_NO_UPDATE_CHECK) return resolve(null);
    const req = require("https").get("https://registry.npmjs.org/openmhp-cli/latest", { timeout: 3000 }, (res) => {
      let body = "";
      res.on("data", (c) => { body += c; });
      res.on("end", () => {
        try {
          const latest = JSON.parse(body).version;
          const n = (v) => v.split("-")[0].split(".").map(Number);
          const [a, b] = [n(latest), n(SELF)];
          const newer = a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
          resolve(newer > 0 ? latest : null);
        } catch { resolve(null); }
      });
    });
    req.on("timeout", () => { req.destroy(); resolve(null); });
    req.on("error", () => resolve(null));
  });
}

async function warnIfOld(verb) {
  const latest = await newerLauncher();
  if (latest && KIND === "npx") {
    log(`this is openmhp-cli ${SELF}, an old copy npx kept; ${latest} is out. Run instead:`);
    log(`  npx -y openmhp-cli@latest ${verb}`);
  } else if (latest) {
    log(`this is openmhp-cli ${SELF}; ${latest} is out. Update the command first, then run this again:`);
    log("  npm install -g openmhp-cli@latest");
    log(`  openmhp ${verb}`);
  }
  return latest;
}

function installedVersion() {
  const r = require("child_process").spawnSync(tool("python"), ["-I", "-c", "import openmhp;print(openmhp.__version__)"], { encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : null;
}

// A separate `pip install -U openmhp` puts its own `mhp` on PATH; this launcher's runtime does not, so a bare
// `mhp ...` typed afterwards runs that other copy, often an old one. Say so once, at setup.
function otherMhp() {
  const r = require("child_process").spawnSync(process.platform === "win32" ? "where" : "which", ["mhp"], { encoding: "utf8" });
  const found = (r.stdout || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
    .filter((p) => !path.resolve(p).startsWith(path.resolve(HOME)) && !ours(p));
  if (!found.length) return;
  const v = require("child_process").spawnSync(found[0].replace(/mhp(\.exe)?$/i, process.platform === "win32" ? "python.exe" : "python"),
    ["-I", "-c", "import openmhp;print(openmhp.__version__)"], { encoding: "utf8" });
  log("");
  log(`note: another OpenMHP is on your PATH: ${found[0]}${v.status === 0 ? ` (version ${v.stdout.trim()})` : ""}.`);
  log("a bare `mhp ...` runs that one, not this install. Either remove the other copy (pip uninstall openmhp)");
  log("and use this one (npm install -g openmhp-cli puts `mhp` on PATH), or keep only the pip one and update it");
  log("with  pip install -U \"openmhp[all]\".");
}

// The `mhp` that `npm install -g openmhp-cli` puts on PATH is this package's own forwarder, not another copy:
// a symlink to bin/mhp.js (macOS, Linux) or a small .cmd/.ps1/sh wrapper naming openmhp-cli (Windows).
function ours(p) {
  try {
    if (fs.realpathSync(p) === fs.realpathSync(path.join(__dirname, "mhp.js"))) return true;
    const head = Buffer.alloc(4096);
    const fd = fs.openSync(p, "r");
    const n = fs.readSync(fd, head, 0, head.length, 0);
    fs.closeSync(fd);
    return head.subarray(0, n).toString("latin1").includes("openmhp-cli");
  } catch { return false; }
}

async function update() {
  if (await warnIfOld("update")) process.exit(1);
  const before = installedVersion();
  ensureRuntime({ upgrade: true });
  log("refreshing Agent Skills in the harnesses found on this machine");
  run("mhp", ["skills", "install"]);
  const after = installedVersion();
  log(before && before !== after ? `updated ${before} -> ${after}` : `OpenMHP ${after} is current`);
  log("restart your agent (or reconnect the openmhp MCP server) so it loads the new version.");
}

async function setup() {
  if (await warnIfOld("setup")) process.exit(1);
  ensureRuntime({ upgrade: true });     // rerunning setup on an old install upgrades it instead of keeping it
  log("installing Agent Skills into the harnesses found on this machine");
  run("mhp", ["skills", "install"]);
  // a global install runs its own `mhp-mcp`, as a pip install does; npx fetches the launcher each time
  const win = process.platform === "win32";
  const [command, cargs] = KIND === "npm" ? [win ? "mhp-mcp.cmd" : "mhp-mcp", []] : [win ? "npx.cmd" : "npx", ["-y", "openmhp-cli"]];
  const registered = [];
  // Claude Code
  if (require("child_process").spawnSync("claude", ["--version"], { encoding: "utf8" }).status === 0) {
    const r = require("child_process").spawnSync("claude", ["mcp", "add", "--scope", "user", "openmhp", "--", command, ...cargs], { encoding: "utf8" });
    if (r.status === 0 || /already exists/i.test(r.stderr + r.stdout)) registered.push("Claude Code");
  }
  // Codex
  const codex = path.join(os.homedir(), ".codex", "config.toml");
  if (fs.existsSync(path.dirname(codex))) {
    const cur = fs.existsSync(codex) ? fs.readFileSync(codex, "utf8") : "";
    if (!/\[mcp_servers\.openmhp\]/.test(cur)) {
      fs.appendFileSync(codex, `\n[mcp_servers.openmhp]\ncommand = "${command}"\nargs = ${JSON.stringify(cargs)}\n`);
    }
    registered.push("Codex");
  }
  console.error("");
  log(registered.length ? `registered with: ${registered.join(", ")}` : "no harness config written automatically");
  log("for any other MCP-capable harness (OpenClaw, Hermes, Claude Science, Open Science, ...) add:");
  console.error(JSON.stringify({ mcpServers: { openmhp: KIND === "npm" ? { command: "mhp-mcp" } : { command: "npx", args: ["-y", "openmhp-cli"] } } }, null, 2));
  console.error("");
  log(KIND === "npm" ? "next: add two simulated instruments:  mhp lab demo"
                     : "next: add two simulated instruments:  npx -y openmhp-cli@latest demo");
  log("then restart your agent and say \"find a thermocycler\", \"find the instruments on my network\" or \"onboard my hotplate\".");
  log(KIND === "npm" ? "if your lab has a gateway:  mhp agent --join <gateway url> <code from mhp gateway pair-agent>"
                     : "if your lab has a gateway:  npx -y openmhp-cli@latest join <gateway url> <code from mhp gateway pair-agent>");
  otherMhp();
  log(`lab lives in ${HOME}`);
}

function main() {
  const [cmd = "serve", ...rest] = process.argv.slice(2);
  recordKind();
  switch (cmd) {
    case "serve": case "mcp":
      ensureRuntime();
      { const child = spawn(tool("mhp-mcp"), ["--fleet", path.join(HOME, "fleet.json"), ...rest], { stdio: "inherit" });
        child.on("exit", (c) => process.exit(c ?? 0)); }
      return;
    case "setup": return setup().catch((e) => { log(String(e)); process.exit(1); });
    case "node": return nodeSetup(rest).catch((e) => { log(String(e)); process.exit(1); });
    case "update": case "upgrade": return update().catch((e) => { log(String(e)); process.exit(1); });
    case "scan": case "add": case "remove": case "list": case "demo":
      ensureRuntime(); process.exit(run("mhp", ["lab", cmd, ...rest]));
    case "validate": ensureRuntime(); process.exit(run("mhp", ["validate", ...rest]));
    case "skills": ensureRuntime(); process.exit(run("mhp", ["skills", ...rest]));
    case "device": ensureRuntime(); process.exit(run("mhp", ["serve", `pkg:${path.resolve(rest[0])}`, ...rest.slice(1)]));
    case "mhp": ensureRuntime(); process.exit(run("mhp", rest));
    case "join":                                       // pair this machine with a lab gateway
      ensureRuntime();
      if (rest.length < 2) { log("usage: npx -y openmhp-cli@latest join https://<gateway>:<port> <code> --name <your name>"); process.exit(2); }
      process.exit(run("mhp", ["agent", "--join", rest[0], rest[1], ...rest.slice(2)]));
    case "guide": ensureRuntime(); process.exit(run("mhp", ["guide", ...rest]));
    case "-V": case "--version": case "version":
      console.log(`openmhp-cli ${require("../package.json").version} (launcher)`);
      ensureRuntime(); process.exit(run("mhp", ["--version", ...rest]));
    case "home": console.log(HOME); return;
    case "-h": case "--help": case "help":
      console.log(fs.readFileSync(__filename, "utf8").split("*/")[0].split("\n").slice(1).map((l) => l.replace(/^(\/\*| \*) ?/, "")).join("\n"));
      return;
    default:
      log(`unknown command ${cmd}; try --help`); process.exit(2);
  }
}

main();
