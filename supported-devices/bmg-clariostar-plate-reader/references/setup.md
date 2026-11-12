# Setting up

Three routes; pick one with `backend` in config.json. The BMG and SoftMax Pro routes run on the
reader's Windows PC (COM and .NET); the Spark route is network SiLA 2 and runs from any OS.

## bmg (CLARIOstar, PHERAstar, Omega, VANTAstar)

Windows only: the Remote Control component is a 32-bit in-process ActiveX server.

1. Install BMG Reader Control (CLARIOstar.exe / PHERAstar.exe / Omega.exe) with the Remote Control
   ActiveX component registered (it ships with the software; BMG support confirms the licence).
2. Use a **32-bit** Python: `pip install openmhp comtypes`.
3. Author the test protocols in Reader Control / SMART Control, each with an ASCII export (well table)
   configured, and note the user's Definit folder.
4. Copy `config.example.json` to `config.json`: `backend: bmg`, `control` (the software name,
   "CLARIOstar" also for a VANTAstar), `protocol_dir` (Definit), `data_dir`, `export_dir`.

## softmax (SpectraMax i3x, iD3, iD5, M series, Paradigm under SoftMax Pro 7.x)

Windows only: the automation client is a .NET assembly.

1. Install SoftMax Pro 7.x with the Automation SDK (`C:\Program Files (x86)\Molecular Devices\
   SoftMax Pro n.n Automation SDK`, assembly "SoftMax Pro AutomationClient.dll") and enable the
   automation server in SoftMax Pro (default port 9000; GxP editions start with `/R` and need Logon).
2. `pip install openmhp pythonnet`; put the SDK folder on the path or give `client_dll` the full path.
3. Save each protocol as a .spr file in `protocol_dir`.
4. config.json: `backend: softmax`, `host` (SoftMax Pro PC), `port`, `protocol_dir`, `export_dir`.

## spark (Tecan Spark)

1. Have Tecan install the SPARK SiLA 2 server (built on the Tecan SiLA2 SDK) next to SparkControl
   and note its host and port.
2. `pip install openmhp sila2`.
3. Ask Tecan for the feature definition (.sila.xml) and put the feature identifier in `feature`;
   the door and method command names in driver.py are placeholders (see references/automation.md).
4. config.json: `backend: spark`, `host`, `port`, `export_dir` (SparkControl's method export folder).

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>`; read `connected`, `status`, `plate_in`, `temperature`.
2. `plate_out`, confirm the carrier comes out and `robot_access_ready` reads true; `plate_in`.
3. Incubating readers: write `temperature_setpoint` 30, watch `temperature` rise; write null.
4. With an empty plate: `read` with a short absorbance protocol; open the export file the result names
   and compare `wells` with the vendor software's table.
5. Start a kinetic read and cancel the job; confirm the reader stops and the tray stays in.

## Status

Written from BMG's ActiveX usage in the AD-SDL bmg_module (MIT), the SoftMax Pro Automation API
Reference Guide 5049094 C and the Tecan SiLA2 SDK paper (SLAS Technology 2023). Several member
names are unverified (listed in references/automation.md). Not yet run on hardware: twin tested.
