# openmhp-node

Turn a lab bench computer into an [OpenMHP](https://openmhp.com) node: it keeps serving
whatever instruments are wired into it — in the background, across reboots — so any AI agent
elsewhere in the lab can find them and operate them safely.

Run this on the computer actually connected to the instrument (its USB port, its vendor
software, its own network link). It's the companion to
[`openmhp-cli`](https://www.npmjs.com/package/openmhp-cli), which you run instead on the
computer where an agent lives — a scientist's laptop, say. This machine doesn't need an agent
on it at all.

```bash
npx openmhp-node setup
```

It asks two questions — which folder holds your instruments' device packages, and which port
to start counting from — installs a small background service, and starts it. From then on this
computer answers automatically.

If there's nothing in that folder yet, point an agent at this machine and say *"onboard my
\<instrument>"* first; it writes the package for you. Then run `setup` again.

```bash
npx openmhp-node status   # is it installed, is it running
npx openmhp-node stop     # remove the service
```

Requires Node 18+ and Python 3.10+. Everything lives in `~/.openmhp`. The background service
uses systemd on Linux, a LaunchAgent on macOS, and your Startup folder on Windows (so on
Windows it starts once you log in, not before).
