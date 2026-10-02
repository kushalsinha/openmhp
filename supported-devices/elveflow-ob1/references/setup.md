# Setting up on the bench PC (Windows)

1. Install the Elveflow Smart Interface (ESI) and its SDK; note the SDK folder that contains
   `Elveflow64.py` (Python_64) and the one that contains `Elveflow64.dll` (DLL64).
2. Find the OB1's device name in NI MAX (National Instruments Measurement & Automation Explorer).
3. Copy `config.example.json` to `config.json` and fill in:
   - `device_name`: the NI MAX name.
   - `regulators`: one code per channel. 0 none, 1 = 0-200 mbar, 2 = 0-2000 mbar,
     3 = 0-8000 mbar, 4 = -1000..1000 mbar, 5 = -1000..6000 mbar.
   - `sensors`: channel -> sensor. `type` is the SDK sensor code for the MFS model (see the SDK
     user guide table), `digital` 1 for a digital MFS, `calibration` 0 water / 1 IPA,
     `resolution` 7 = 16 bit.
   - `calibration_file`: a saved OB1 calibration, or null for the default calibration.
4. Close ESI before serving: only one program can hold the OB1.
5. `mhp serve pkg:<this folder> --http <port>`, then `mhp http://localhost:<port> read connected`.

The driver was written against the SDK calls in Elveflow's Python tutorial
(OB1_Initialization, OB1_Add_Sens, OB1_Set_Press, OB1_Get_Press, OB1_Get_Sens_Data,
PID_Add_Remote, OB1_Start_Remote_Measurement, OB1_Set_Remote_Target, OB1_Get_Remote_Data).
It has not yet been run against the hardware.
