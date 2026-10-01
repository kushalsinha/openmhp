# Setting up on the bench PC (Windows)

1. Install BioLogic's EC-Lab Development Package (it must match the SP-300 firmware; EC-Lab can
   update the firmware). Note its install folder.
2. In the Python environment that runs `mhp`: `pip install easy-biologic`. If it cannot find the
   development package, point it at the folder as its README describes.
3. Copy `config.example.json` to `config.json`:
   - `address`: `USB0`, or the instrument's IP address if it is on Ethernet.
   - `channel`: 0 for the first channel.
   - `ewe_abort_window_V`: the driver stops a run if the working-electrode potential leaves it.
   - `data_dir`: where CSV traces are written.
4. Close EC-Lab (it holds the instrument), then `mhp serve pkg:<this folder> --http <port>`.

Written against easy-biologic's BiologicDevice and its OCV, CP and CV programs; the pulsed
technique is the CP technique with two current steps and N_Cycles set. Not yet run against the
hardware. First hardware test: `ocv` for 10 s on a dummy cell.
