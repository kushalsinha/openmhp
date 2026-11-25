#!/usr/bin/env node
/* `mhp` from `npm install -g openmhp-cli`: the same command a pip install of OpenMHP gives, run on the
 * runtime this package keeps in ~/.openmhp/venv (installed or updated first, so the first run takes a minute). */
"use strict";
require("../lib/runtime").forward("mhp");
