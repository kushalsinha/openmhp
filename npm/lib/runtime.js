/* Used by openmhp-cli: find or install a Python 3.10+ runtime in an isolated venv under
 * ~/.openmhp, and run the `mhp`/`mhp-mcp` it installs. The launcher does none of the actual
 * work itself -- this just makes sure the Python package exists.
 */
"use strict";
const { spawnSync, spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HOME = process.env.OPENMHP_HOME || path.join(os.homedir(), ".openmhp");
const VENV = path.join(HOME, "venv");
const BIN = path.join(VENV, process.platform === "win32" ? "Scripts" : "bin");
const SOURCE = process.env.OPENMHP_SOURCE || "openmhp[all]";   // PyPI name, or a path / git URL; [all] serves an
                                                                // agent machine and an instrument PC alike
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

const LAUNCHER = require("../package.json").version;
const MARKER = path.join(HOME, ".upgraded-for");     // the launcher version pip last installed for, successfully

function older(a, b) {                      // is version a older than b (x.y.z, any suffix ignored)?
  const n = (v) => String(v).split("-")[0].split(".").map(Number);
  const [x, y] = [n(a), n(b)];
  for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) < (y[i] || 0);
  return false;
}

function runtimeVersion() {
  const r = spawnSync(tool("python"), ["-I", "-c", "import openmhp;print(openmhp.__version__)"], { encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : null;
}

function ensureRuntime({ upgrade = false, source = SOURCE } = {}) {
  if (fs.existsSync(tool("mhp-mcp")) && fs.existsSync(tool("python")) && !upgrade) {
    // a runtime older than this launcher (left by an earlier, older setup) lacks commands the launcher's
    // instructions use, such as `mhp agent --join`: bring it up to date first
    const have = runtimeVersion();
    if (have && !older(have, LAUNCHER)) return;
    // the marker says "pip already got everything the package index has for this launcher": written only after an
    // install that worked, so a failed or interrupted one is tried again next time, and a broken runtime is never
    // mistaken for a lagging mirror
    try {
      if (have && fs.readFileSync(MARKER, "utf8").trim() === LAUNCHER) {
        log(`OpenMHP ${have} here, older than this launcher (${LAUNCHER}): your package index has nothing newer yet.`);
        return;
      }
    } catch { /* never installed for this launcher */ }
    log(have ? `the runtime in ${VENV} is OpenMHP ${have}; this launcher is ${LAUNCHER}. Updating it.`
             : `the runtime in ${VENV} cannot load OpenMHP; installing it again.`);
    upgrade = true;
  }
  const py = findPython();
  if (!py) {
    log("Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and run this again.");
    process.exit(1);
  }
  fs.mkdirSync(HOME, { recursive: true });
  if (fs.existsSync(VENV) && !fs.existsSync(tool("python"))) {
    // the Python this runtime was made from is gone (uninstalled, or a conda env removed): start it again
    log(`${VENV} lost its Python; making it again`);
    fs.rmSync(VENV, { recursive: true, force: true });
  }
  if (!fs.existsSync(VENV)) {
    log(`creating ${VENV}`);
    if (spawnSync(py, ["-m", "venv", VENV], { stdio: ["ignore", "inherit", "inherit"] }).status !== 0) process.exit(1);
  }
  log(`installing ${source}`);
  const args = ["-m", "pip", "install", "--quiet", "--disable-pip-version-check"];
  if (upgrade) args.push("--upgrade");
  args.push(source);
  const r = spawnSync(tool("python"), args, { stdio: ["ignore", "inherit", "inherit"] });
  if (r.status !== 0) {
    log("install failed (see pip's message above). Nothing was marked as done: the next run tries again.");
    process.exit(1);
  }
  const got = runtimeVersion();
  if (!got) { log("installed, but OpenMHP still does not load in this runtime; see the messages above"); process.exit(1); }
  try { fs.writeFileSync(MARKER, LAUNCHER); } catch { /* read-only home: try again next time */ }
  if (older(got, LAUNCHER) && /^openmhp(\[|$)/.test(source)) mirrorBehind(got);
  log("runtime ready");
}

// Where pip looks for packages, as a host name only: an index URL can carry a user and token.
function indexHost() {
  let url = process.env.PIP_INDEX_URL || "";
  if (!url) {
    const r = spawnSync(tool("python"), ["-m", "pip", "config", "list"], { encoding: "utf8" });
    const m = /index-url\s*=\s*'?([^'\s]+)/.exec(r.stdout || "");
    url = m ? m[1] : "";
  }
  try { return url ? new URL(url).host : null; } catch { return null; }
}

// pip upgraded as far as it could and is still behind: the package index offers nothing newer. In an
// enterprise that is usually an internal mirror; say what to ask for instead of carrying on silently.
function mirrorBehind(got) {
  const host = indexHost();
  log("");
  log(`the newest OpenMHP your Python package index offers is ${got}; this launcher is ${LAUNCHER}.`);
  log(host && host !== "pypi.org"
    ? `pip installs from ${host}, which looks like an internal mirror: ask whoever runs it to add openmhp ${LAUNCHER}`
    : `ask whoever manages Python packages on this machine for openmhp ${LAUNCHER}`);
  log("  (https://pypi.org/project/openmhp/, with pyyaml, zeroconf, pyserial and paho-mqtt).");
  log(`until then OpenMHP ${got} runs here, without what came later (joining a gateway needs 0.10.0 or newer).`);
  log("");
}

// How this launcher was started: `npx ...` (a copy in npx's cache) or `npm install -g` (a command on PATH).
// Written to ~/.openmhp/launcher so the Python side can print the update command that fits this install.
const KIND = /[\\/]_npx[\\/]/.test(__dirname) ? "npx" : "npm";
function recordKind() {
  try {
    const f = path.join(HOME, "launcher");
    if (!fs.existsSync(f) || fs.readFileSync(f, "utf8").trim() !== KIND) {
      fs.mkdirSync(HOME, { recursive: true });
      fs.writeFileSync(f, KIND + "\n");
    }
  } catch { /* read-only home: the Python side then assumes npx */ }
}

// `mhp` and `mhp-mcp` installed by `npm install -g openmhp-cli`: the same commands a pip install gives,
// forwarded to the runtime in ~/.openmhp/venv, which is installed or brought up to date first.
function forward(cmd) {
  ensureRuntime();
  recordKind();
  const child = spawn(tool(cmd), process.argv.slice(2), { stdio: "inherit" });
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => { try { child.kill(sig); } catch { /* gone */ } });
  child.on("error", (e) => { log(`could not start ${tool(cmd)}: ${e.message}`); process.exit(1); });
  child.on("exit", (code, sig) => process.exit(code ?? (sig ? 1 : 0)));
}

function run(cmd, args, opts = {}) {
  const r = spawnSync(tool(cmd), args, { stdio: "inherit", ...opts });
  return r.status ?? 1;
}

function spawnBg(cmd, args, opts = {}) {
  return spawn(tool(cmd), args, { stdio: "inherit", ...opts });
}

module.exports = { HOME, VENV, BIN, SOURCE, KIND, log, findPython, ensureRuntime, recordKind, forward, run, spawnBg, tool };
