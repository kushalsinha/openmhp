# Setting up

The package does not need to run on the instrument PC: it talks HTTPS to the Empower Web API
server, so it can be served from any Windows, Linux or macOS machine that reaches it.

1. Ask the Empower administrator for the Web API address (Waters installs it as a service,
   commonly on port 3076), and an Empower user for the agent, for example `svc_openmhp`, with
   access to the project and to the project `Mobile` (the Web API needs both), and rights to
   create sample set methods and run samples on the system. Give it no right to edit or delete
   methods or results.
2. On the serving machine: `pip install openmhp opti-hplc-handler` (Novo Nordisk's BSD-licensed
   client for the Empower Web API).
3. Store the password in the OS keyring, never in config.json:
   `python -m keyring set Empower svc_openmhp`.
4. Copy `config.example.json` to `config.json`: address, project, username, the `node` and
   `system` names exactly as Empower shows them, default plate types, the injection volume range and maximum injections per sample
   for this system's loop, and `allowed_methods` (method set names an agent may use; empty means
   any in the project).
5. Optional results: give the processing method an export method that writes to a shared folder
   and set `export_dir` to that folder; the job result then includes the exported rows.
6. `mhp serve pkg:<this folder> --http <port>`, read `connected` and `system_status`, run
   `list_methods`, then run one blank injection.

Written against the Web API calls used by opti-hplc-handler 5.0 (see `references/web_api.md`).
Not yet run against an Empower server.
