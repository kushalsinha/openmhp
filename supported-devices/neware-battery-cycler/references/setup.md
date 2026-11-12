# Setting up

The BTS server and client 8.0 run on a Windows PC; this package talks TCP to that PC and only needs
the Python standard library, so it can be served from that PC or from any Windows, Linux or macOS
machine on the network that can also write into the step folder. The simulated twin runs anywhere.

1. In the BTS client: Help > Mode settings, enable the API (Neware may have to supply an activation
   key for the server). Note the API port (502 by default).
2. Make a folder on the BTS PC for step files (for example `D:\OpenMHP\steps`) and share it so the
   serving machine can write there; `step_dir` is the path from the serving machine, `step_dir_on_server`
   the Windows path the server uses to open the file.
3. `pip install openmhp` on the serving machine.
4. Copy `config.example.json` to `config.json`: `host`, `port`, `user`, `password` (kept in the
   keyring by `mhp node setup`), `step_dir`, `step_dir_on_server`, `backup_dir`, and the chemistry caps
   `voltage_max_v`, `voltage_min_v`, `current_max_a` for the cells on the bench.
5. `mhp serve pkg:<this folder> --http <port>` and read `connected` and `channels`.

## First hardware test

1. Read `channels` and compare with the BTS client's channel tree; write `channel` to a free one and
   read `channel_state`, `voltage` (an unconnected channel reads near 0 V).
2. Export a step file from the BTS client for a short protocol and compare it with
   `references/bts_api.md`; adjust `render_step_file` in `driver.py` until the layouts match.
3. With a dummy load or a well-characterised cell: invoke `start_protocol` with the first example
   shortened (`time_limit_s` 60 on each step, `cycles` 1) and confirm it. The BTS client should show
   the channel start with the barcode; `channel_state` reads `working`.
4. Read `voltage`, `current`, `capacity`, `step` and `cycle` while it runs and compare with the
   client; check `current_scale` and `capacity_scale` from the numbers.
5. Cancel the job (the channel stops) and run `safety/estop` with two channels working: both stop.

## Status

Driver written from an open-source (MIT) BTS 8.0 client's message set and Neware's public client
documentation; the inquire reply attribute names, the status words beyond finish/stop/protect, the
API's units and the step-file XML layout are marked unverified in `references/bts_api.md`. Not yet run
on hardware. Status: template, because the step-file layout the BTS server expects is not published; a real start is expected to answer false until a BTS-client export has been compared.
