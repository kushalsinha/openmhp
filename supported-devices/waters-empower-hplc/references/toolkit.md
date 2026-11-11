# Empower Toolkit objects used (backend `toolkit`)

The Toolkit is Waters' COM automation interface to Empower, installed with the Empower client under a
Toolkit license. It exposes what an Empower user can do in the client: log in, open a project, read
and write methods and sample sets, run them on a system, and fetch results. Object ProgIDs start with
`MillenniumToolkit.` (the historic name); `toolkit_progid` in config.json changes the prefix.

Every call the backend makes is one line in `ToolkitBackend` in `driver.py`, in the methods between
`_login` and `_fetch`, with the object and member named in a trailing comment. The table below is
that list. Written from the Empower 3 Toolkit object model; member spellings must be checked against
the Toolkit Programmer's Reference for your Empower release before the first run, and corrected in
`driver.py` where they differ. Nothing else in the package depends on them.

| Purpose | Object | Member |
|---|---|---|
| Log in | `Login` | `Login(user, password, database)`, `Logout()` |
| Open the project | `Project` | `Login = login`, `Open(name)` |
| Method names | `Project` | `GetMethodList(type)` for `Instrument`, `MethodSet`, `SampleSet` |
| Plate types | `Project` | `GetPlateTypeList()` |
| Attach to the system | `Instrument` | `Login = login`, `Connect(node, system)`, `Disconnect()` |
| System status | `Instrument` | `Status` (string), `SampleSetName` |
| Build a sample set method | `SampleSetMethod` | `Project = project`, `New()`, `SetPlateType(pos, type)`, `AddRow("Inject Samples")`, `SetField(row, field, value)`, `Save(name, auditComment)` |
| Run it | `Instrument` | `RunSampleSet(ssmName, sampleSetName, runMode)` with RunOnly 0, RunAndProcess 1, RunAndReport 2 |
| Stop it | `Instrument` | `Abort()` |
| Results | `DataFetch` | `Project = project`, `Fields`, `Criteria = "SampleSetName = '...'"`, `Fetch()`, `RowCount`, `GetValue(row, field)` |

Sample set lines use the Empower fields `SampleName`, `Vial`, `InjVol` and `MethodSetOrReportMethod`,
the same four the Web API route fills.

## Threads

pywin32 COM objects belong to the thread that created them. The driver is called from the HTTP
server's request threads and from job threads, so `ToolkitBackend` runs every Toolkit call on one
dedicated thread (`_ComThread`) that calls `CoInitialize` once and owns all the objects. Status reads
and the abort have a 30 s timeout; method listing, sample set creation and result fetching 120 s.

## What the Toolkit gives over the Web API

- `Instrument.Abort()`: `jobs/cancel` on a running `run_samples` stops the sample set in Empower and
  the job ends `cancelled` only after Empower reports the system idle again.
- `DataFetch`: result rows per peak land in the job result (`results_from: "toolkit"`) without an
  export method or shared folder.
- No Web API server to install or license; the Toolkit license is per client.

What it costs: the package must run on the Empower client PC under 32-bit Python, and the lab's
Toolkit license must cover a non-interactive user.
