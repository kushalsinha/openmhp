# Setting up on the bench PC (Windows)

1. Install the Elveflow Smart Interface and SDK (same install as the OB1).
2. Find the valve's COM port in Device Manager; the SDK wants it as `ASRL<n>::INSTR` (COM5 -> ASRL5::INSTR).
3. Copy `config.example.json` to `config.json`; set `visa_com`, `ports` (6, 10 or 12) and
   `port_map` (what is plumbed to each port).
4. Close ESI, then `mhp serve pkg:<this folder> --http <port>` and read `connected`.

Written against the SDK calls MUX_DRI_Initialization, MUX_DRI_Set_Valve, MUX_DRI_Get_Valve,
MUX_DRI_Send_Command and MUX_DRI_Destructor. Not yet run against the hardware.
