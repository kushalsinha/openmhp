# Setting up

Two routes into Empower. Leave `backend` on `auto` and the package picks: the Toolkit when it runs
on an Empower client PC that has it (and `database` is set), otherwise the Web API when `address` is
set. If an auto-chosen Toolkit does not log in and an address exists, it uses the Web API and says so
in the `backend` signal. Set `backend` to `toolkit` or `web_api` to insist. Everything above the
backend (limits, sample list, polling, the job result) is the same, so the lab installs whichever is
easier for it.

| | `web_api` | `toolkit` |
|---|---|---|
| What it talks to | Empower Web API server (HTTPS, commonly port 3076) | Empower Toolkit, Waters' COM SDK, on an Empower client PC |
| Runs where | any Windows, Linux or macOS machine that reaches the API | the Empower client PC itself |
| Needs | Web API installed and licensed; `pip install opti-hplc-handler` | Toolkit license and install; 32-bit Python; `pip install pywin32 keyring` |
| Stop a running sample set | no (a person, in Run Samples) | yes: `jobs/cancel` aborts it in Empower |
| Results in the job result | only through an export method and `export_dir` | fetched from the project directly |

Both need an Empower user for the agent, for example `svc_openmhp`, with access to the project
and rights to create sample set methods and run samples on the system, and no right to edit or
delete methods or results. The Web API also needs access to the project `Mobile`.

Store the password in the OS keyring on the serving machine, never in config.json:
`python -m keyring set Empower svc_openmhp`.

## Web API

1. Ask the Empower administrator for the Web API address.
2. `pip install openmhp opti-hplc-handler` (Novo Nordisk's BSD-licensed client for the Web API).
3. Copy `config.example.json` to `config.json`: `backend: "web_api"`, address, project, username,
   the `node` and `system` names exactly as Empower shows them, default plate types, the injection
   volume range and maximum injections per sample for this system's loop, and `allowed_methods`
   (method set names an agent may use; empty means any in the project).
4. Optional results: give the processing method an export method that writes to a shared folder and
   set `export_dir` to that folder; the job result then includes the exported rows.

The Web API calls used are in `references/web_api.md`.

## Toolkit

1. The Toolkit is a licensed Empower option, installed with the Empower client (Personal, Workgroup
   or Enterprise) on a Windows PC. Check the license is present in Configuration Manager.
2. Empower 3 and its Toolkit are 32-bit COM servers, so install 32-bit Python 3.11 on that PC (the
   same arrangement as the ÄKTA package's OpenOPC) and `pip install openmhp pywin32 keyring`.
3. Copy `config.example.json` to `config.json`: `database` (the Empower
   database name shown on the login dialog), project, username, node, system, plates and limits as
   above. `result_fields` are the Empower result fields the job result returns per peak.
4. Leave `export_dir` null unless you also want the export file picked up; the result rows come from
   the project.

The Toolkit objects and members used, and what to check against your release's Programmer's
Reference, are in `references/toolkit.md`.

## First test

`mhp serve pkg:<this folder> --http <port>`, read `connected`, `backend` and `system_status`, run
`list_methods`, then run one blank injection. On the Toolkit route also start a two-injection sample
set and cancel the job: Empower's Run Samples window should show the sample set aborted.

Written against the Web API calls used by opti-hplc-handler 5.0 and the Empower 3 Toolkit object
model. Neither route has yet been run against an Empower server.
