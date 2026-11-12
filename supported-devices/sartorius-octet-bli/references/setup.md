# Setting up

Octet BLI Discovery runs on the instrument's Windows PC; its automation interface is a TCP/IP socket
(or RS-232), so this package can be served from that PC or from any Windows, Linux or macOS machine on
the network. Only the Python standard library is needed: `pip install openmhp`.

1. In Octet BLI Discovery: File > Options > Automation; choose TCP/IP and a port (or RS-232), and
   "Localhost" only when the client runs on the same PC. The software must stay open with the
   instrument initialised; `AutomationClient.exe` in `C:\Program Files\ForteBio\DataAcquisition`
   is the vendor's test client for the same protocol.
2. Keep the methods (.fmf) agents may run in one folder on the Octet PC and name it in
   `config.json: method_dir` as a Windows path. Set the data repository to a UNC share so the
   experiment paths from `GetRunInfo` resolve from other machines.
3. Copy `config.example.json` to `config.json`: `host`, `port`, `method_dir`, optionally
   `allowed_methods`.
4. RH16/RH96 only: `Present`/`Close` (plate_out/plate_in) move the stage; the R8 has no automation
   interface in the documents read (unverified), so on an R8 expect plate_in/plate_out to fail.

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>`; read `connected` and `status` (expect OK).
2. `plate_out`: the door opens and the stage comes out; `robot_access_ready` reads true. `plate_in`.
3. Write `temperature_setpoint` 30 and watch the plate temperature on the instrument screen.
4. With a buffer-only plate and a used sensor tray: `run_experiment` with a short quantitation method;
   confirm the experiment folder named in the result exists.
5. Start the same run again and cancel the job; confirm the instrument reports Stopped then OK.

## Status

Written from the Octet System Data Acquisition User Guide Release 11.0, Appendix A (AutomationAPI.h,
API 1.1) and the Sartorius Octet software version 10 datasheet (RH16/RH96 support). The sensor-tray
switch mapping (-l), R8 support and the port default are unverified. Not yet run on hardware: twin tested.
