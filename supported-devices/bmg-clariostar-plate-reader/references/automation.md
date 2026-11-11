# The three automation interfaces this package calls

## BMG LABTECH Remote Control ActiveX (backend: bmg)

Sources: AD-SDL `bmg_module` (github.com/AD-SDL/bmg_module, `sidecar/bmg_interface.py`, MIT; a
MADSci node run on a VANTAstar through the CLARIOstar control), and search-visible fragments of the
BMG "ActiveX and DDE Interface Manual, Omega series" (doc 0415N0006J, 2014), which could not be
read in full. BMG's software page confirms ActiveX, DDE and SiLA control.

| Member | Meaning | Verified |
|---|---|---|
| `CreateObject("BMG_ActiveX.BMGRemoteControl")` (comtypes, 32-bit) | the component | yes (bmg_module) |
| `OpenConnection(controlName)` -> 0 ok | attach to the running Reader Control ("CLARIOstar" also for a VANTAstar) | yes |
| `CloseConnection()`, `GetVersion()` | | yes |
| `GetInfo("Status")` -> "Ready" / "Busy" / "Error"; `GetInfo("Error")`; `GetInfo("Temp1" / "Temp2" / "Temp3")` tenths of Cel | status, error text, incubator temperatures | yes |
| `GetInfo("PlateOut")` | tray position | **unverified** item name; the driver treats "0"/"False" as in |
| `ExecuteAndWait(["Init"])` | initialise | yes |
| `ExecuteAndWait(["PlateIn"])`, `["PlateOut"]` | tray | yes |
| `ExecuteAndWait(["Temp", "30.0"])`; "0.0" off, "0.1" monitor only | incubator | yes |
| `ExecuteAndWait(["Run", test, definitDir, dataDir, id1, id2, id3, exportDir, exportFile])` | run a protocol | partly: the call is bmg_module's; the positional meaning of the folder arguments is inferred from its code, **unverified** against the manual |
| `ExecuteAndWait(["Terminate"])` | abort | **unverified** (named in the manual's table of contents per search snippets) |

## SoftMax Pro Automation API (backend: softmax)

Source: Molecular Devices, "SoftMax Pro Data Acquisition and Analysis Software: Automation API
Reference Guide", doc 5049094 C (March 2021, SoftMax Pro 7.1.x); also 5049094 A (2016).

| Member | Meaning | Verified |
|---|---|---|
| assembly `SoftMax Pro AutomationClient.dll`, class `SoftMaxPro.AutomationClient.SMPAutomationClient` | WCF client of the automation server | yes |
| `Initialize()`, `Initialize(server)`, `Initialize(server, port)` -> bool; default localhost:9000 | connect | yes |
| commands return an Int32 queue id; results arrive on `CommandCompleted` (`QueueId`, `StringResult`, `IntResult`, `DoubleResult`); `ErrorReport` flushes the queue | async model | yes (event wiring from pythonnet **unverified**) |
| `GetInstrumentStatus()` -> IDLE, INITIALIZING, BUSY, STOPPING, ERROR, TIMEOUT, OFFLINE | status | yes |
| `OpenDrawer()`, `CloseDrawer()`, `GetDrawerStatus()` | tray | yes (the status string values are **unverified**) |
| `GetTemperature()` -> double, `SetTemperature(double)`; 0 = incubator off; drawer cannot open with the incubator on | incubator | yes |
| `OpenFile(path)` (protocol or data document), `SelectSection(name)`, `SetTitle`, `StartRead()`, `StopRead()` (not queued) | run | yes; the `SetTitle` argument the driver passes for the plate id is **unverified** |
| `ExportAs(path, ExportAsFormat {TIME, COLUMNS, PLATE, XML})` | export | yes (the enum's .NET path as written in driver.py is **unverified**) |
| `SetReader(port, instrument)`, `Logon/Logoff`, `Dispose()` | not used | yes |

Legacy SoftMax Pro 5.x used Win32 messages (`SOFTMaxPROMsg`, commands Read, OpenDrawer, ...); the
`!Open`/`!Read` style command names were not found in any document.

## Tecan Spark SiLA 2 server (backend: spark)

Source: Hinkel, Kunert, Meredith, "The Tecan SiLA2 SDK", SLAS Technology 28(5), 2023 (open access);
Tecan FluentControl compatibility list (SiLA2 client drives the Spark); gitlab.com/SiLA2/vendors/sila_tecan.

| Member | Meaning | Verified |
|---|---|---|
| a Reader Service feature with two door commands and `ExecuteMethod(MethodName)` (observable, cancellable through CancelController, MethodName constrained to SparkControl's methods) | the whole surface | the shape yes; the feature identifier `ReaderService`, `OpenDoor`, `CloseDoor` and a `DoorOpen` property are **unverified** placeholders |
| temperature | none in the feature | yes (not exposed) |
| results | SparkControl's own export (Excel/ASCII per method); `export_dir` is where the method writes | **unverified** |

Ask Tecan for the server's `.sila.xml` feature definitions and replace the placeholders in
`SparkBackend` before use.
