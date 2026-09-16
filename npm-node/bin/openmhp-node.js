#!/usr/bin/env node
/* openmhp-node: turn THIS computer into a lightweight OpenMHP node.
 *
 * Run it on the computer that's actually wired to your instruments (USB, serial, vendor
 * software, a local network link) -- not on a scientist's laptop, which is what
 * `npx openmhp-cli setup` is for. This computer never needs to run an agent itself; it just
 * needs to keep answering when one asks.
 *
 *   npx openmhp-node setup           interactive: asks for a folder and a port, then installs
 *                                    a background service that serves every package in it
 *   npx openmhp-node setup <folder>  same, non-interactive if you also pass --http PORT
 *   npx openmhp-node status          is the service installed, and is it running
 *   npx openmhp-node stop            remove the background service
 *
 * All the real work (the Python runtime, the venv, the service itself) is shared with
 * openmhp-cli, which this package depends on.
 */
"use strict";
const fs = require("fs");
const { ensureRuntime, run, log } = require("openmhp-cli/lib/runtime");
const { nodeSetup } = require("openmhp-cli/lib/node_setup");

const NODE_SOURCE = process.env.OPENMHP_SOURCE || "openmhp[all]";

function main() {
  const [cmd = "setup", ...rest] = process.argv.slice(2);
  switch (cmd) {
    case "setup": return nodeSetup(rest).catch((e) => { log(String(e)); process.exit(1); });
    // force an upgrade: --service-status/--uninstall-service are newer than some installed venvs,
    // and failing with argparse's "unrecognized arguments" here would be a confusing way to find out.
    // Same extras as setup: a bench PC needs serial and MQTT, so never narrow it to [discovery] here.
    case "status": ensureRuntime({ upgrade: true, source: NODE_SOURCE }); process.exit(run("mhp", ["node", "--service-status"]));
    case "stop": ensureRuntime({ upgrade: true, source: NODE_SOURCE }); process.exit(run("mhp", ["node", "--uninstall-service"]));
    case "-h": case "--help": case "help":
      console.log(fs.readFileSync(__filename, "utf8").split("*/")[0].split("\n").slice(1).map((l) => l.replace(/^ \* ?/, "")).join("\n"));
      return;
    default:
      log(`unknown command ${cmd}; try --help`); process.exit(2);
  }
}

main();
