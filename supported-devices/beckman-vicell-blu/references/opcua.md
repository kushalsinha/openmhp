# Vi-CELL BLU OPC UA automation interface

Source: Beckman Coulter, "Vi-CELL BLU Automation Software Integration Guide for Developer Use",
doc 21.09.2613.PCC Rev A, 2021 (public PDF on media.beckman.com). Transport OPC UA over Ethernet
(port configurable in the instrument software), username/password plus X.509 security; a .NET
wrapper DLL exposes the same members.

## Properties (read)

| Property | Type | Used as |
|---|---|---|
| CurrentStatus | ViCellStatus {Unknown, Idle, Initializing, Cleaning, Running, Error, Warning, RequiresUserInteraction} | status, robot_access_ready |
| CurrentLockState | LockState {Unknown=0, Locked, Unlocked} | not read (lock handled by call results) |
| ReagentUsesRemaining | uint32 | reagent_remaining |
| WasteTubeRemainingCapacityRemaining, DiskSpaceAvailable | uint32 | not read |
| CellTypes | List<CellType> (Name, MinDiameter, MaxDiameter, ...) | discover("cell_types") |
| QualityControls | List<QualityControl> | not read |
| CurrentRunningSampleName, CurrentSamplePosition | string, SamplePosition {Row, Column} | not read |

## Methods (all return VcbResult {Error=0, Success, NoConnection, NotLocked})

| Method | Used as |
|---|---|
| Connect(Username, Password, IpAddr, Port, discoverTimeout, cnxTimeout) / Disconnect() | the .NET wrapper's; the OPC UA session replaces them here |
| RequestLock() -> LockState / ReleaseLock() | around every count, prime and clean |
| StartSample(SampleConfig {Name, Position, Dilution, Tag, CellTypeName, QCName, SaveEveryNthImage, WashType}) | count |
| StartSampleSet(SampleSetConfig) | not used (96-well plate) |
| Pause() / Resume() / Stop() | Stop on cancel and e-stop |
| EjectStage() | not used (a person or robot loads while Idle) |
| GetSampleResults(FilterType, FromDate, ToDate, Username, SearchString, SampleTag, CellTypeOrQCName) -> List<SampleResult> | result by sample name |
| RetrieveSampleExport, DeleteSampleResults, CreateCellType, DeleteCellType, CreateQualityControl, ImportConfig, ExportConfig | not used |

SampleResult (Rev A): Configuration, SummaryResultUuid, Date, CellCount, ViableCellCount,
ViabilityPercent, AverageDiameter, AverageViableDiameter, AverageCircularity, AverageCellsPerImage,
AverageBackgroundIntensity, BubbleCount, ClusterCount. Enums: WashType {Normal, Fast}.

## What this package assumes beyond the guide (unverified)

- The OPC UA node ids of every property and method (`config.json: nodes`; placeholders ship).
- `StartSample` taking the SampleConfig fields as positional scalars (Name, Row, Column, Dilution,
  Tag, CellTypeName, QCName, SaveEveryNthImage, WashType); the structure encoding is in the kit's SDK.
- Carousel positions as Row "Z", Column 1..24 (the guide only says Position is ignored for the cup).
- A `CarouselPresent` property for `carousel_present`.
- `Prime` and `Clean` methods: the guide lists neither; the instrument has both functions in its UI.
- `ViableCellsPerMl`, `TotalCellsPerMl` and `ImagePath` on SampleResult: Rev A lists counts, not
  concentrations, so the result fields are nullable and null on a server that lacks them.
- A liquid handler delivers 200 +/- 20 uL to the bottom of the automation cup (Beckman automation page).
