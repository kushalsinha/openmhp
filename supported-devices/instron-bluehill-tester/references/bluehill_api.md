# Bluehill Universal API and exports: what is documented, what this template assumes

Searched 2026-11-11. "unverified" means not read in an Instron document.

Sources read:

- Instron, "Bluehill Universal API - Application Programming Interface" datasheet
  (BluehillUniversalAPI_PodV1, 2017; instron.com/wp-content/uploads/2025/02/Bluehill-Universal-
  Application-Programming-Interface.pdf): included with the standard purchase; built with Visual
  Studio .NET; usable from VB, .NET, C# "or any programming language that's capable of connecting
  with Windows Communication Foundation"; use cases: import specimen dimensions and identifiers
  from a spreadsheet or database, open a method and start a test from an external device, write
  results to SQL/LIMS. No member names.
- Instron, "Upgrading from Bluehill 3 to Bluehill Universal" (BluehillUniversal_UpgradingfromBH3_
  PodV2): Universal no longer uses the legacy API, scripts must move to a WCF-compatible format;
  Load became Force and Extension became Displacement in Universal's wording; Bluehill 3 default
  `.CSV` results and raw exports are kept.
- Instron, Bluehill Universal product page and "Computer Requirements" page: Windows 10/11 64-bit;
  export of results, statistics, parameters and raw data as CSV or custom text, at finish, named
  from the sample; an executable can run after export (v4.06); Bluehill Universal brochure.
- Instron training manual M18-17146-EN Rev C (Test Method Development; university-hosted copy):
  Export File 1 and 2 contents (method parameters, results table, statistics, raw data), frequency
  (on demand, at finish, after each test), file naming, CSV or custom text options, default
  Outputs folder.
- Instron 6800 operator's guide M10-17547-EN Rev B and 5940 guide M10-16245-EN (manualslib):
  the E-stop removes drive power, opens pneumatic grips with an air kit, puts the frame in
  DISABLED, is reset by turning the button and pressing UNLOCK / re-enabling the frame; frame
  modes DISABLED, SET UP, CAUTION, TESTING; the interlock accessory (debris shield) disables the
  frame or limits motion when open. Instron 6800 and 3400 datasheets: crosshead speeds 0.00005
  (floor) / 0.001 (6800 table) / 0.05 (3400 table) to 1016-3048 mm/min; capacities 0.5 to 300 kN.
- National Instruments forum threads on the Bluehill 3 WCF API: assembly `BluehillWCF.dll`,
  method `APIHeartbeat`, class `BluehillAPI`, event `TestStart`. These are Bluehill 3 names;
  their survival in Universal is unverified.

## The assumed members (config.json `api`) -- every one unverified

| key | placeholder | role |
|---|---|---|
| assembly | BluehillWCF | the .NET client assembly loaded with pythonnet (Bluehill 3 name) |
| client | Instron.Bluehill.Api.BluehillApiClient | WCF client class taking the endpoint |
| connect | Connect() | open the channel |
| heartbeat | APIHeartbeat() | true when the service answers (Bluehill 3 name) |
| open_method | OpenMethod(path) | open a saved method |
| set_input | SetSpecimenInput(name, value) | specimen inputs: Sample name, Specimen label, Width, Thickness, Gauge length |
| set_rate | SetTestRate(mm/min) | crosshead rate for the test |
| set_limit | SetTestLimit("Force" or "Displacement", value) | stop limits |
| start | StartTest() | start (the 3400/6800 operator protection may still need the panel's Start) |
| stop | StopTest() | stop the crosshead and end the test |
| disable_frame | DisableFrame() | put the frame in DISABLED (e-stop) |
| frame_mode | FrameMode (property) | DISABLED / SETUP / CAUTION / TESTING |
| crosshead | CrossheadStatus (property) | moving / stopped / limit |
| load, extension | Load, Extension (properties) | N, mm live values |
| test_running | IsTestRunning (property) | polling |
| end_reason | TestEndReason (property) | break / limit / finished / stopped |

## The results export (read from `outputs_dir/<sample>_Results.csv`)

Layout from Bluehill 3-era exports (an R package's reader and a university lab's example): zero
or more `parameter,value,unit` rows, a blank row, a names row, a units row in parentheses, then
one row per specimen; comma-delimited. Universal keeps the same default CSV. The column names
read are configuration (`columns`): Maximum Force, Modulus (Automatic Young's), Tensile stress at
Maximum Force, Tensile strain at Break, Extension at Break; the Bluehill 3 names were Maximum
Load and Tensile stress at Maximum Load. A verbatim Universal default export was not found, so
the names row is located by the peak-load column and everything else is optional. The raw-data
export (`_RawData.csv`, Time / Extension / Load rows) is only named in the result.

## The twin

The fake frame starts in SET UP; a test stretches the specimen at the rate, elastic (2000 MPa) to
3 % strain, then a slow hardening to break at 12 % strain or at the load/extension limit, scaled
by OPENMHP_SIM_TIME_SCALE; it then writes the results CSV as laid out above and a short raw file.
StopTest ends the test with reason stopped; DisableFrame puts it in DISABLED.
