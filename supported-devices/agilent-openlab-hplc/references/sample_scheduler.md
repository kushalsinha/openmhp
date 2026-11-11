# Sample Scheduler for OpenLab: the LIMS file interface this package uses

Sources (Agilent online help, openlab.help.agilent.com, Sample Scheduler for OpenLab, no document number shown):
`SchedConf_Set_LIMS_ConfigParam.htm`, `SchedConf_Set_Commands.htm`, `SchedulerConfig_AutoFillingCommand_TablePopulation_XML.htm`,
`SampleSchedulerAnalysisParameters.htm`, `SampleSchedulerAnalysisManagement.htm`, `SampleSchedulerOnlineActions.htm`,
`SampleScheduler_WEBUI.htm`; OpenLab CDS Acquisition help `ImportFileToSeqTable.htm`, `Sequence_table_columns.htm`;
Agilent whitepaper 5994-7041EN (LIMS integration, cited from search snippets only).

## Confirmed

- Integration is **file or database based**: XML command files in a watched **Command folder** (default
  `C:\LIMS_Commands`, UNC allowed), or a SQL mode where the scheduler polls a LIMS database. If SQL is
  configured for a connection, XML for that connection is ignored.
- Invalid or incomplete commands go to `LIMS_Commands\trash`; processed XML files are moved to a manually
  created processed-command folder (kept 48 h by default).
- **Mandatory XML parameters** (names "correspond to the ones used in the XML command"): `SampleName`,
  `Project`, `Instrument`, `InjectionSource`, `AcquisitionMethod`, `ResultName`, `Vial`, `InjectionVolume`
  (or `UseMethodInjectionVolume`). Optional ones include `ProcessingMethod`, `InjectionsPerSample`,
  `SampleType` (Sample, Cal.Std., Blank, Double Blank, QC Check, Spike, Sys. Suit.), `Level`, `Dil. factor`,
  `Multiplier`, `ISTD amt`, `Sample amount`, `LIMS ID1-3`, `Priority`, `Planned start time`, custom
  parameters; `InjectionVolumeUnit` appears in the EZChrom comparison guide.
- Command files must validate against an XSD shipped in `<install>\Documentation` (file name not stated);
  examples live in `<install>\Documentation\xml`.
- Analysis states: Waiting, Scheduled, Holding, Submitted, In Progress, Not Available, Error, Waiting on
  error, Stopping, Stopped, Ended, Incomplete, Rollout Pending, Transferred.
- Results to the LIMS: "Review for LIMS" copies report files (csv, txt by default; pdf, docx, xlsx possible)
  to a **Result folder** (for example `C:\LIMS_Results`).
- Stop is a UI action (Stop, Stop instrument; needs the "Abort any running sample" privilege). The
  whitepaper mentions an XML cancel command without showing its schema.
- OpenLab CDS Acquisition can import a CSV/TSV sequence table (columns `Sample name, Vial, Volume, Inj/Vial,
  Acq. method, Proc. method, Data file, Sample type, ...`) but only as a manual UI action: no watched folder.
- No public REST API, OAuth2 endpoint or Swagger exists for OpenLab CDS 2.x, Shared Services or the Data
  Store; the Data Accessibility Tool exposes results as a SQL schema. An "OpenLab Acquisition SDK" (.NET,
  pythonnet, local only, SDK licence entitlement) exists in open-source code (NSLS2 lix-profile-collection,
  ethanbass/chromConverter, ombayley/ChromTroller): `InstrumentController.EstablishConnection`,
  `SubmitSingleRun`, `SubmitSequenceRun`, `AbortCurrentSingleOrSequenceRun`, run statuses
  Pending/Acquiring/Completed/Aborted. It is not used here.

## What this package writes

`<command_dir>/<sequence_name>.xml`:

```
<Command>                     <!-- root name: unverified -->
  <Analyses>                  <!-- grouping: unverified -->
    <Analysis>                <!-- one per sample: unverified -->
      <SampleName/> <Project/> <Instrument/> <InjectionSource/> <AcquisitionMethod/> <ProcessingMethod/>
      <ResultName/> <Vial/> <InjectionVolume/> <InjectionVolumeUnit>uL</InjectionVolumeUnit>
      <InjectionsPerSample/> <SampleType/> <LIMSID1>job id</LIMSID1>
    </Analysis>
  </Analyses>
</Command>
```

The parameter element names are the documented ones; the root, grouping and the spelling of multi-word
names (`InjectionsPerSample`, `LIMSID1`, `SampleType`) as XML elements are **unverified**: compare with the
XSD and the example files in `<install>\Documentation\xml` and adjust `command_xml()` in driver.py before
the first hardware test.

## Unverified

- The XML element layout above (root, grouping, attribute vs element, multi-word names).
- Whether the processed command file keeps its name (this package reads "gone from the folder and not
  in trash" as accepted).
- Method file extensions `.amx` / `.pmx` used by `list_methods` over a shared method folder.
- Result file naming: this package matches files whose name contains the ResultName.
- A status feedback file; none is documented, so analysis states are not read.
