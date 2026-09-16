/* Shared by openmhp-cli and openmhp-node: find or install a Python 3.10+ runtime in an
 * isolated venv under ~/.openmhp, and run the `mhp`/`mhp-mcp` it installs. Neither launcher
 * does any of the actual work itself -- this just makes sure the Python package exists.
 */
"use strict";
const { spawnSync, spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HOME = process.env.OPENMHP_HOME || path.join(os.homedir(), ".openmhp");
const VENV = path.join(HOME, "venv");
const BIN = path.join(VENV, process.platform === "win32" ? "Scripts" : "bin");
const SOURCE = process.env.OPENMHP_SOURCE || "openmhp[discovery]";   // PyPI name, or a path / git URL
const log = (...a) => console.error("[openmhp]", ...a);

function findPython() {
  for (const cmd of ["python3", "python", "py"]) {
    const r = spawnSync(cmd, ["-c", "import sys;print('%d.%d'%sys.version_info[:2])"], { encoding: "utf8" });
    if (r.status === 0) {
      const [maj, min] = r.stdout.trim().split(".").map(Number);
      if (maj > 3 || (maj === 3 && min >= 10)) return cmd;
    }
  }
  return null;
}

function tool(n) {
  return path.join(BIN, process.platform === "win32" ? n + ".exe" : n);
}

function ensureRuntime({ upgrade = false, source = SOURCE } = {}) {
  if (fs.existsSync(tool("mhp-mcp")) && !upgrade) return;
  const py = findPython();
  if (!py) {
    log("Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and run this again.");
    process.exit(1);
  }
  fs.mkdirSync(HOME, { recursive: true });
  if (!fs.existsSync(VENV)) {
    log(`creating ${VENV}`);
    if (spawnSync(py, ["-m", "venv", VENV], { stdio: ["ignore", "inherit", "inherit"] }).status !== 0) process.exit(1);
  }
  log(`installing ${source}`);
  const args = ["-m", "pip", "install", "--quiet", "--disable-pip-version-check"];
  if (upgrade) args.push("--upgrade");
  args.push(source);
  const r = spawnSync(tool("python"), args, { stdio: ["ignore", "inherit", "inherit"] });
  if (r.status !== 0) { log("install failed"); process.exit(1); }
  log("runtime ready");
}

function run(cmd, args, opts = {}) {
  const r = spawnSync(tool(cmd), args, { stdio: "inherit", ...opts });
  return r.status ?? 1;
}

function spawnBg(cmd, args, opts = {}) {
  return spawn(tool(cmd), args, { stdio: "inherit", ...opts });
}

module.exports = { HOME, VENV, BIN, SOURCE, log, findPython, ensureRuntime, run, spawnBg, tool };
