# Setting up on the UNICORN instrument PC (Windows)

1. UNICORN's OPC server is a licensed option. In UNICORN Administration, System Properties →
   Edit → Advanced Settings, enable the OPC Data Access server for the ÄKTA avant system and,
   if wanted, "Take Control" for OPC. Decide whether OPC logon security is on; if it is, the
   driver logs in as a UNICORN user (set `opc_user` in config.json and store the password with
   `keyring set UNICORN <user>`).
2. Install 32-bit Python 3.11 on the same PC (the UNICORN OPC server is a 32-bit COM server;
   32-bit Python is the combination reported to work reliably with OpenOPC). Then:
   `pip install openmhp OpenOPC-Python3x pywin32`, and register the OPC automation wrapper
   (`regsvr32 gbda_aut.dll`, shipped with OpenOPC).
3. Copy `config.example.json` to `config.json`:
   - `progid`: `UNICORN_DAServer30.System1.1` (DA 3.0) or `UNICORN_DAServer20.System1.1` (DA 2.05a).
     "System1" is the first system UNICORN knows; use System2 for the second.
   - `method_root`: the OPC branch that holds the methods (`\Method\DefaultHome` by default).
     Browse it once with `list_methods`.
   - `allowed_methods`: the method names an agent may run. Empty means every method in the branch.
   - `items`: the OPC item for each signal. Names follow the ÄKTA's instrument configuration
     (e.g. UV1 or "UV 1_280"); browse `Event\Analog Picture` and `Event\Rundata` and copy them.
4. In each method you want the agent to adjust, put the adjustable values in the Start Protocol
   as method variables with sensible min/max; only those are writable over OPC.
5. `mhp serve pkg:<this folder> --http <port>`, read `connected` and `run_state`, then run
   `list_methods`. First real test: a short water wash method with no column.

Written against the UNICORN 7.6 OPC Manual (Cytiva 29503109 AA). Not yet run against an ÄKTA.
UNICORN versions with OPC: 6.x and 7.x; UNICORN 7.10 also ships an OPC UA server (OPC Server 1.2),
which this package does not use yet.
