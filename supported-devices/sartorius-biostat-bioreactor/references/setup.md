# Setting up

The package talks OPC UA over Ethernet to the Biobrain controller, so it can be served from any
Windows, Linux or macOS machine on the same network (not necessarily the Biobrain Supervise PC).

1. On the serving machine: `pip install openmhp asyncua keyring` (python-opcua also works).
2. In Biobrain, create a device user for the agent (for example `openmhp`) with the **Remote
   operation** permission, and note the unit name (Unit1, ...). Store the password in the OS keyring,
   never in config.json: `python -m keyring set Biobrain openmhp`.
3. Certificates: the Biobrain OPC UA server (port 4840) requires Sign and Encrypt with
   Basic256Sha256 and a trusted client certificate. Connect once with UaExpert, trust the server
   certificate and have the Biobrain administrator trust the client's; asyncua needs the same
   application certificate (`Client.set_security(...)`), which this driver reads from the default
   asyncua location. Until this works in UaExpert it will not work here.
4. Node ids: Sartorius supplies an "OPC UA interface report" per product listing every node. Browse
   the unit in UaExpert and copy the ids for the roles in `config.example.json` (`nodes`) into
   `config.json`. The shipped ids are placeholders; see `references/opcua.md`.
5. Copy `config.example.json` to `config.json`: `url`, `user`, `unit`, the `nodes` map, and the
   lab's own ceilings (`max_batch_hours`, `max_feed_hours`). Lower the setting limits in
   `descriptor.yaml` to what the vessel and culture tolerate (agitation above a few hundred rpm
   shears mammalian cells) and ship that as a package edit.
6. Recipes: written and validated in Biobrain. Save each as a method here
   (`methods/save {name, project, action: start_batch, params: {recipe: ...}, compounds: [...]}`).

## Eppendorf BioFlo 320

The BioFlo 320 has no OPC UA server of its own in public documentation: Eppendorf integrates it
through DASware connect (OPC DA / XML-DA) or OPC XML to DeltaV. With an OPC UA gateway in front of
DASware connect, this package applies with the node map replaced; without one it does not.

## DCU 4 without Biobrain

A DCU 4 tower without Biobrain exposes OPC Classic (DA) through the Sartorius "BioPAT DCU OPC
Server.NET" or the Matrikon OPC Server for Sartorius Biostat DCU. Put an OPC UA wrapper (for
example the one in UaGateway) in front of it, or adapt this package the way cytiva-akta-avant uses
OpenOPC.

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>` and read `connected`, `temperature`, `ph`, `do`,
   `agitation_rpm`, `gas_flow` and `phase`; compare each with the Biobrain screen.
2. With the vessel empty of culture (water, no cells), write `temperature_setpoint` 30 and watch
   `temperature` move toward it; check Biobrain shows the TEMP loop in Auto.
3. Write `gas_flow_setpoint` 0.2 and confirm the MFC responds; write 0.
4. Invoke `add_feed` with a small volume into a waste bottle (`volume_ml: 5, rate_ml_h: 60`) and weigh
   the delivered volume against the pump calibration.
5. Invoke `safety/estop` and confirm the stirrer, gas and feed stop and every loop shows Off in
   Biobrain; `safety/reset`, then put the loops back in Auto.
6. Only then run `start_batch` with a short test recipe.

## Status

Written from the Sartorius Biobrain integration datasheet, the Biobrain Supervise OPC UA
application note (Aug 2023) and the Biostat B-DCU operating manual (controller names and modes);
the node ids and the numeric mode coding are unverified. Not yet run on hardware: twin tested.
