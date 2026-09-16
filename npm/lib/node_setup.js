/* The interactive flow behind `npx openmhp-cli node` and `npx openmhp-node setup`: turn the
 * computer it runs on into a lightweight OpenMHP node that keeps serving its instruments in
 * the background, across reboots. Shared so openmhp-node (a thin, separately-named package for
 * a lab bench PC that will never run an agent itself) doesn't duplicate any of this.
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

async function nodeSetup(rest) {
  // this machine hosts instruments; it may never run an agent itself, so it wants serial + MQTT + mDNS.
  // `node`/`--install-service` are newer than some installed venvs (openmhp-cli only upgrades an
  // existing venv on request) -- force one here so this doesn't fail confusingly on a stale install.
  ensureRuntime({ source: process.env.OPENMHP_SOURCE || "openmhp[all]", upgrade: true });
  const args = [...rest];
  let folder = args.find((a) => !a.startsWith("-"));
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
    log("Add one first: point your agent at this machine and say \"onboard my <instrument>\",");
    log(`or copy/pull a package folder (with a DEVICE.md) into ${folder}, then run this again.`);
    process.exit(1);
  }
  log(`found ${existing.length} package(s): ${existing.join(", ")}`);
  const passthrough = args.filter((a) => a !== folder);
  const code = run("mhp", ["node", folder, ...httpArgs, ...passthrough, "--install-service"]);
  if (code === 0) {
    log("");
    log("this computer now serves its instruments in the background, across reboots.");
    log(`add more packages to ${folder} any time; restart the service to pick them up:`);
    log(`  mhp node --uninstall-service && npx openmhp-cli node ${folder}`);
    log("from the lab's main computer (or this one), find it with: mhp_lab op='scan', or say \"find the instruments on my network\".");
  }
  process.exit(code);
}

module.exports = { nodeSetup };
