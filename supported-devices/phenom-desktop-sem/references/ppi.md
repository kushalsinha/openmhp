# Phenom Programming Interface (PyPhenom) calls used

Sources read:
- Thermo Fisher Scientific, "Phenom XL G3 Desktop SEM" datasheet, DS0328-EN-07-2025: electron-optical
  magnification 160-200,000x, light-optical 3-16x; acceleration voltages 5/10/15/20 kV (2 kV option),
  advanced mode 4.8-20.5 kV; vacuum levels low/medium/high; resolution <9 nm; image sizes 960x600,
  1920x1200, 3840x2400, 7680x4800; sample up to 100 x 100 mm, 36 pin stubs, 40 mm high; electron-optical
  loading time <60 s; computer-controlled motorised X and Y stage; "standardly accessible via PPI".
- Thermo Fisher Scientific, "Phenom Programming Interface" product page: script-based control of stage,
  navigation camera and SEM imaging; a PC on the Phenom's network; Windows listed as the supported OS.
- Thermo Fisher Scientific, "The power of scripting with a desktop SEM" (webinar slides): names
  `phenom.Unload()`, `phenom.SemAcquireImage` and `phenom.SemAutoFocus()`; PPI sits between the Phenom
  workstation and a user PC; Python and C#.
- nanoScience Instruments (Thermo partner), technical note 23-SEM04 "Python programming for SEM
  automation": a screenshot of a PPI script showing `import PyPhenom as ppi`, a connection made from the
  instrument's address, instrument ID and PPI licence password, `ppi.Position(x, y)` and stage offsets
  in metres.

| Member (config key) | Meaning | Verified |
|---|---|---|
| `PyPhenom.Phenom(address, instrument_id, licence_password)` (`phenom`) | open a session | yes (technote screenshot) |
| `Position(x, y)` (`position`) | a stage position in metres | yes (technote screenshot) |
| `Unload()` (`unload`) | vent and present the holder | yes (webinar) |
| `SemAcquireImage(scan_params)` (`acquire`) | acquire an SEM image | name yes (webinar); argument unverified |
| `SemAutoFocus()` (`auto_focus`) | auto focus | yes (webinar) |
| `Load()` (`load`) | pump the holder in | unverified |
| `MoveTo(position)` (`move_to`), `GetStagePosition()` (`stage_position`) | absolute stage move, position read | unverified |
| `GetInstrumentMode()` (`instrument_mode`) -> Operational / Standby / Hibernate | source state | unverified |
| `GetOperationalMode()` (`operational_mode`) -> Loading / Unloading / Unloaded / LiveNavCam / LiveSem / ... | what the instrument is doing | unverified |
| `Activate()`, `Standby()` (`activate`, `standby`) | bring the source up / put it in standby (e-stop) | unverified |
| `GetSemHfw()`, `SetSemHfw(metres)` (`get_hfw`, `set_hfw`) | horizontal field width; magnification is set through it | unverified |
| `GetSemMagnification()` (`get_mag`) | magnification the instrument reports | unverified |
| `GetSemHighTension()`, `SetSemHighTension(volts)` (`get_ht`, `set_ht`) | acceleration voltage, negative volts | unverified |
| `ScanParams` with `size = Size(w, h)`, `nFrames`, `dwellTime`, `detector = DetectorMode.<All|TopoA|TopoB|Sed>` (`scan_params`) | acquisition parameters | unverified |
| `Save(acquisition, filename)` (`save`) | write the image file | unverified |

Units: PPI stage positions in metres (this package speaks mm), high tension in volts, field width in
metres; magnification here is converted with a reference width (`screen_width_m`, 0.1 m by default,
unverified) and the value reported back by the instrument is what the result carries.

## Unverified

- Every member marked unverified above, the `ScanParams` field names, the detector enum and the sign
  convention of the high tension. All come from config.json `ppi` (or one line of `driver.py` for the
  ScanParams fields) so a lab with the PPI reference corrects them without touching the logic.
- The operational mode words: the driver treats `LiveSem` / `AcquireSemImage` as "holder loaded under
  the SEM" (`vacuum_ready`) and `Unloaded` as "holder presented" (`robot_access_ready`); a different
  spelling makes loads time out and `robot_access_ready` read false, never true by mistake.
- `beam_on` is derived (Operational and live), as no beam query was found in the material read.
- Dwell time range (0.1-1000 us) is a placeholder; the datasheet's 1-500 ms range is the EDS
  mapping dwell, not the SEM pixel dwell.
- No automated loader: the datasheet describes a venting/loading mechanism and manual holders only.
