/* The interactive flow behind `npx -y openmhp-cli@latest node`: turn the computer it runs on into a
 * lightweight OpenMHP node that keeps serving its instruments in the background, across reboots.
 * A lab bench PC that will never run an agent itself is the intended user.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const readline = require("readline");
const { HOME, log, ensureRuntime, run } = require("./runtime");

function ask(question, fallback) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stderr });
  return new Promise((resolve) => rl.question(`${question}${fallback ? ` [${fallback}]` : ""}: `, (a) => {
    rl.close();
    resolve(a.trim() || fallback);
  }));
}

// what `mhp node` does on its own: fetch and set up a package, check, and manage the service
const PASSTHROUGH = new Set(["add", "setup", "--check", "--service-status", "--uninstall-service"]);

async function nodeSetup(rest) {
  // this machine hosts instruments; it may never run an agent itself, so it wants serial + MQTT + mDNS
  // (the `node` extra). Upgrade too, so a stale install does not fail confusingly on newer verbs.
  ensureRuntime({ source: process.env.OPENMHP_SOURCE || "openmhp[node]", upgrade: true });
  if (rest.length && PASSTHROUGH.has(rest[0])) process.exit(run("mhp", ["node", ...rest]));
  const args = [...rest];
  const takes = { "--join": 2, "--http": 1, "--name": 1, "--host": 1, "--token": 1 };   // options and their values
  const values = new Set();
  args.forEach((a, i) => { for (let k = 1; k <= (takes[a] || 0); k++) values.add(i + k); });
  let folder = args.find((a, i) => !a.startsWith("-") && !values.has(i));
  if (!folder && args.includes("--join")) {
    // pairing a PC set up with `node add`: its packages are in the default folder, served by the background service
    process.exit(run("mhp", ["node", ...args, "--install-service"]));
  }
  if (!folder) {
    folder = await ask("Folder with your device packages (one subfolder per instrument)", path.join(HOME, "devices"));
  }
  folder = path.resolve(folder);
  fs.mkdirSync(folder, { recursive: true });
  const hasPortFlag = args.includes("--http");
  let httpArgs = [];
  if (!hasPortFlag) {
    const port = await ask("Base port (each instrument gets the next one up)", "18900");
    httpArgs = ["--http", port];
  }
  const existing = fs.readdirSync(folder).filter((n) => fs.existsSync(path.join(folder, n, "DEVICE.md")));
  if (existing.length === 0) {
    log(`no device packages in ${folder} yet.`);
    log("Add one first: `npx -y openmhp-cli@latest node add` lists the supported instruments, and");
    log("`npx -y openmhp-cli@latest node add <name>` fetches and sets one up. Or point your agent at this machine and say");
    log(`"onboard my <instrument>", or copy a package folder (with a DEVICE.md) into ${folder}; then run this again.`);
    process.exit(1);
  }
  log(`found ${existing.length} package(s): ${existing.join(", ")}`);
  const passthrough = args.filter((a, i) => !(a === folder && !values.has(i)));
  const code = run("mhp", ["node", folder, ...httpArgs, ...passthrough, "--install-service"]);
  if (code === 0) {
    log("");
    log("this computer now serves its instruments in the background, across reboots.");
    log(`add more packages to ${folder} any time, or update OpenMHP; this restarts the service on them:`);
    log(`  npx -y openmhp-cli@latest node ${folder}`);
    log("from the lab's main computer (or this one), find it with: mhp_lab op='scan', or say \"find the instruments on my network\".");
  }
  process.exit(code);
}

module.exports = { nodeSetup };
