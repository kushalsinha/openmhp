<!-- generated from openmhp/registry.json by scripts/build_guide.py -->

# Instruments supported

81 ready-made device packages. Every one ships inside the OpenMHP package, so installing one needs no web or git access.

- On the instrument PC (the computer wired to the instrument): `mhp node add <package>` copies the package, asks its questions, pairs with the gateway and keeps it running. `mhp node add` alone lists them.
- On an agent machine, to rehearse with the simulated twin: `mhp lab add <package> --sim`, or in an agent, `mhp_lab op='add' target='<package>' sim=true`.
- With npx: `npx -y openmhp-cli@latest node add <package>`.

**twin tested**: the package and its simulated twin pass the checks; not yet run against the hardware. **template**: the vendor's protocol is not public, so commands are placeholders to fill in from the manual. Host *Windows* means the vendor software it drives runs only on Windows. For an instrument not listed, see `mhp guide add-a-device`.

## Pharma, small molecule

| Package | Instrument | Class | Talks through | Host | Status |
|---|---|---|---|---|---|
| `agilent-cary-uvvis-ftir` | Agilent Cary 60/3500 UV-Vis (Cary WinUV) and Cary 630 FTIR (MicroLab) | spectrometer | watched folder + CSV export (Cary WinUV / MicroLab) | Windows | twin tested |
| `agilent-dissolution-708ds` | Agilent Technologies (Varian / VanKel) 708-DS dissolution apparatus (template; VK 7000 / 7010 / 7025 family) | dissolution_tester | serial, 10-digit Comm-ID frames (placeholders) | any | template |
| `agilent-openlab-hplc` | Agilent 1260/1290 Infinity II under OpenLab CDS 2.x with Sample Scheduler | chromatograph | Sample Scheduler LIMS command/result folders | any | twin tested |
| `bruker-d8-pxrd` | Bruker AXS D8 Advance / D8 Discover under DIFFRAC.SUITE | diffractometer | DIFFRAC.SUITE job folder + .brml results folder | Windows | twin tested |
| `bruker-nmr-iconnmr` | Bruker Avance NEO / III HD under TopSpin with ICON-NMR | nuclear_magnetic_resonance_spectrometer | ICON-NMR automation import folder + TopSpin data dir | any | twin tested |
| `buchi-rotavapor-r300` | Büchi Rotavapor R-300 with Interface I-300 Pro, VacuBox and V-300 pump | rotary_evaporator | BUCHI OpenInterface REST /api/v1 (basic auth) | any | twin tested |
| `crystal16-solubility` | Technobis Crystal16 under CrystalClear | reactor | CrystalClear program and export folders | Windows | twin tested |
| `metrohm-titrino-kf` | Metrohm 870 KF Titrino plus (or 758 KFD / 784 KFP / 787 KF Titrino) over RS-232 | titrator | RS-232 ($G/$S/$D/$L/$Q or Titrino object tree) | any | twin tested |
| `mettler-easymax-reactor` | Mettler Toledo EasyMax 102/402 or OptiMax 1001 under iControl | reactor | iControl OPC UA server (node ids per lab) | Windows | twin tested |
| `mettler-toledo-balance` | Mettler Toledo MT-SICS balances (Excellence XP/XS/XA, XPR/XSR, MS, ML and others) | balance | serial, MT-SICS level 0/1 | any | twin tested |
| `sartorius-balance` | Sartorius SBI balances (Entris II, Secura, Quintix, Practum, Cubis, Cubis II in SBI mode) | balance | serial, Sartorius SBI (ESC commands) | any | twin tested |
| `sp-lyostar-freeze-dryer` | SP Scientific LyoStar 3 / LyoStar 4 (Martin Christ Epsilon 2-4 LSCplus via notes) | lyophilizer | Modbus TCP to the control PLC, placeholder map | any | template |
| `ta-dsc-tga` | TA Instruments Discovery / Q-series DSC and TGA under TRIOS | thermal_analyzer | TRIOS run-list folder + text export folder | Windows | twin tested |
| `thermo-chromeleon-hplc` | Thermo Fisher Scientific Vanquish or UltiMate 3000 under Chromeleon 7.x | chromatograph | Chromeleon SDK (.NET) through pythonnet | Windows | twin tested |
| `vapourtec-rseries` | Vapourtec R-Series (R2 pump module, R4 reactor heater) under Flow Commander | reactor | Flow Commander OPC UA server (node ids per lab) | Windows | twin tested |
| `waters-empower-hplc` | Waters HPLC/UPLC system under Empower 3 | chromatograph | Empower Web API (opti-hplc-handler) or Empower Toolkit (COM, pywin32) | any | twin tested |

## Pharma, biologics

| Package | Instrument | Class | Talks through | Host | Status |
|---|---|---|---|---|---|
| `beckman-vicell-blu` | Beckman Coulter Vi-CELL BLU | cell_counter | Vi-CELL BLU OPC UA automation, asyncua | any | twin tested |
| `binder-stability-chamber` | BINDER KBF / KBF P / KMF (MB2 controller); Memmert ICH / HPP via notes | environmental_chamber | Modbus TCP on the MB2 Ethernet port, placeholder map | any | template |
| `bmg-clariostar-plate-reader` | BMG LABTECH (also Molecular Devices, Tecan) CLARIOstar / PHERAstar (SpectraMax via SoftMax Pro, Spark via SiLA 2) | microplate_reader | BMG ActiveX / SoftMax Pro .NET / Spark SiLA 2 (config) | Windows | twin tested |
| `cytek-aurora-flow-cytometer` | Cytek Biosciences Aurora / Northern Lights under SpectroFlo | flow_cytometer | watched folder + FCS 3.1 export (SpectroFlo) | Windows | twin tested |
| `cytiva-akta-avant` | Cytiva (GE Healthcare) ÄKTA avant 25/150 with UNICORN 6/7 | chromatograph | UNICORN OPC Data Access, OpenOPC | Windows | twin tested |
| `eppendorf-innova-shaker` | Eppendorf (New Brunswick Scientific) Innova 44 / 44R (Innova 40, 42, 43 compatible) | shaker | serial, Innova two-letter remote-programming commands | any | twin tested |
| `hamilton-star` | Hamilton Microlab STAR / STARlet (Vantage via the STAR backend) | liquid_handler | PyLabRobot STAR backend (USB) | any | twin tested |
| `malvern-zetasizer-dls` | Malvern Panalytical Zetasizer Ultra / Pro (ZS Xplorer); Nano ZS by the same shape | particle_analyzer | ZS Xplorer SDK (.NET), pythonnet | Windows | twin tested |
| `protein-simple-maurice-ce` | ProteinSimple (Bio-Techne) Maurice (cIEF and CE-SDS) under Compass for iCE | capillary_electrophoresis_instrument | watched folder + peak-table CSV (Compass for iCE) | Windows | twin tested |
| `sartorius-biostat-bioreactor` | Sartorius Biostat B / Biostat STR (DCU 4, Biobrain) | bioreactor | Biobrain OPC UA server, asyncua | any | twin tested |
| `sartorius-octet-bli` | Sartorius (ForteBio) Octet RH16 / RH96 (R8 unverified) | biosensor | Octet automation interface, TCP/IP socket | any | twin tested |
| `sigma-4-16ks-centrifuge` | Sigma Laborzentrifugen 4-16KS (Spincontrol serial interface; 3-18KS, 4-5KRL, 4-16KR and other Spincontrol models) | centrifuge | serial, Sigma Spincontrol word commands at 9600 baud | any | twin tested |
| `thermo-heracell-co2-incubator` | Thermo Scientific Heracell VIOS 160i / 250i (also Steri-Cycle i160 / i250) | incubator | Modbus TCP/RTU, placeholder register map | any | template |
| `thermo-quantstudio-qpcr` | Applied Biosystems (Thermo Fisher Scientific) QuantStudio 5/7 under QuantStudio Design & Analysis Software 2 | real_time_pcr_machine | plate setup TXT import + Results CSV export (D&A 2) | any | twin tested |

## Chemistry

| Package | Instrument | Class | Talks through | Host | Status |
|---|---|---|---|---|---|
| `biologic-sp300` | BioLogic SP-300 | potentiostat | EC-Lab Development Package, easy-biologic | Windows | twin tested |
| `elveflow-mux-distributor` | Elveflow MUX Distributor (rotary selection valve) | valve | Elveflow SDK | Windows | twin tested |
| `elveflow-ob1` | Elveflow OB1 pressure controller | pump | Elveflow SDK | Windows | twin tested |
| `globalfia-flopro-sampler` | Global FIA (Zone Fluidics) FloPro Sampler, run by FloZF | sampler | FloZF serial handshake (virtual COM pair) | Windows | twin tested |
| `ika-c-mag-hs7` | IKA C-MAG HS 7 | hotplate | serial, NAMUR commands | any | twin tested |
| `ika-eurostar-overhead` | IKA EUROSTAR 60 control / EUROSTAR 100 control | stirrer | serial, NAMUR commands | any | twin tested |
| `julabo-corio-circulator` | JULABO CORIO CD / CP, MAGIO, DYNEO | circulator | serial, JULABO interface commands | any | twin tested |
| `lcms-worklist` | Waters, SCIEX, Agilent or Thermo LC-MS sample queue under MassLynx, SCIEX OS, MassHunter or Xcalibur | mass_spectrometer | vendor import file written to a folder | any | twin tested |
| `ocean-insight-spectrometer` | Ocean Insight (Ocean Optics) USB2000+, USB4000, Flame, QE Pro, HR series (python-seabreeze) | spectrometer | python-seabreeze over USB | any | twin tested |
| `palmsens-potentiostat` | PalmSens EmStat Pico, EmStat4 LR/HR, Sensit (MethodSCRIPT over USB virtual COM) | potentiostat | MethodSCRIPT text over pyserial (USB CDC) | any | twin tested |
| `sri-8610c-gc` | SRI Instruments 8610C (PeakSimple) | chromatograph | PeakSimple .NET connector, pythonnet | Windows | twin tested |
| `thermo-orbitrap-iapi` | Thermo Fisher Scientific Orbitrap Fusion / Lumos / Eclipse / Ascend (Tribrid) via IAPI | mass_spectrometer | Thermo IAPI .NET assemblies via pythonnet | Windows | twin tested |
| `wasatch-raman-blaze` | BlazeMetrics / Wasatch Photonics Blaze Raman probe on a Wasatch spectrometer | spectrometer | Wasatch.PY | Windows | twin tested |

## Biology

| Package | Instrument | Class | Talks through | Host | Status |
|---|---|---|---|---|---|
| `atlas-ezo-sensors` | Atlas Scientific EZO-pH / EZO-ORP / EZO-DO / EZO-EC / EZO-RTD (UART mode) | sensor | serial, EZO UART commands | any | twin tested |
| `manual-benchtop-centrifuge` | generic benchtop | centrifuge | operator prompts | any | template |
| `micro-manager-microscope` | any (Micro-Manager) Micro-Manager hardware configuration via pymmcore-plus | microscope | pymmcore-plus (CMMCorePlus) in-process | any | twin tested |
| `new-era-syringe-pump` | New Era Pump Systems NE-1000 / NE-4000 (NE-1000 series) | pump | serial, NE-1000 pump network protocol | any | twin tested |
| `opentrons-flex` | Opentrons Flex | liquid_handler | PyLabRobot | any | twin tested |
| `opentrons-ot2` | Opentrons OT-2 | liquid_handler | PyLabRobot OT-2 backend (HTTP API) | any | twin tested |
| `tecan-cavro-pump` | Tecan Cavro XLP 6000 / XCalibur (DT protocol) | pump | serial, Cavro DT protocol | any | twin tested |

## Physics and optics

| Package | Instrument | Class | Talks through | Host | Status |
|---|---|---|---|---|---|
| `keithley-smu` | Keithley (Tektronix) 2400 series SourceMeter (2400, 2401, 2410, 2420) | source_meter | SCPI over VISA (GPIB) or RS-232, pyvisa | any | twin tested |
| `lakeshore-temperature` | Lake Shore Cryotronics 335 / 336 / 350 cryogenic temperature controller | temperature_controller | Lake Shore ASCII over TCP 7777 or GPIB (VISA) | any | twin tested |
| `pfeiffer-tpg-gauge` | Pfeiffer Vacuum TPG 361 / 362 / 366 (TPG 261 / 262 compatible) | vacuum_gauge | serial, Pfeiffer mnemonic protocol with ENQ/ACK | any | twin tested |
| `srs-lockin` | Stanford Research Systems SR830 DSP lock-in amplifier (SR810; SR860/SR865A with notes) | lock_in_amplifier | SRS ASCII commands over VISA (GPIB) or RS-232 | any | twin tested |
| `srs-rga` | Stanford Research Systems RGA100 / RGA200 / RGA300 | mass_spectrometer | serial, SRS RGA ASCII commands at 28800 baud | any | twin tested |
| `thorlabs-power-meter` | Thorlabs PM100D optical power meter console (PM100A, PM100USB, PM400) | sensor | SCPI over USBTMC (pyvisa-py + pyusb) | any | twin tested |

## Materials, synthesis and processing

| Package | Instrument | Class | Talks through | Host | Status |
|---|---|---|---|---|---|
| `aja-sputter-system` | AJA International ATC Orion (Phase II control); Kurt J. Lesker PVD 75 and Moorfield nanoPVD via notes | deposition_system | Modbus TCP to the control PLC (placeholder map) | any | template |
| `eurotherm-tube-furnace` | Eurotherm (Carbolite Gero, MTI, Thermcraft furnaces) 2416 / 2404 / 2408 programmer-controllers (2400 series Modbus map); 3216 / 3508 / nanodac need their own map | furnace | Modbus RTU (EIA-485/232) or TCP gateway, HA026230 map | any | twin tested |
| `laurell-spin-coater` | Laurell Technologies WS-650 and WS-400 series spin processors with the 650 controller (RS-232 / USB to Spin 3000) | spin_coater | RS-232/USB to the 650 controller (Spin 3000 port) | any | template |
| `mbraun-glovebox` | MBRAUN LABstar / UNIlab / LABmaster / MB200 with the PLC Ethernet (Modbus TCP) option | glovebox | Modbus TCP to the MBRAUN/Siemens PLC Ethernet option | any | template |
| `mettler-quantos-dosing` | Mettler Toledo Quantos QB1 / QS30 and XPR automatic powder dosing (XPR/XSR balance with a dosing module) over MT-SICS | dispenser | RS-232/USB, MT-SICS on the XPR/XSR balance | any | template |
| `nabertherm-furnace` | Nabertherm B400 / B410 / C440 / C450 / P470 / P480 (and series 500) controllers with the Modbus TCP communication module | furnace | Modbus TCP port 502, Nabertherm communication module (M03.0021) | any | twin tested |
| `ossila-spin-coater` | Ossila Spin Coater L2001A3 (120-6,000 rpm) and L2001B1 (500-10,000 rpm) | spin_coater | USB virtual COM port on the unit | any | template |
| `retsch-planetary-mill` | Retsch PM 100 / PM 200 / PM 400 (serial interface) | mill | RS-232/RS-485 serial (placeholder commands) | any | template |

## Materials, characterization

| Package | Instrument | Class | Talks through | Host | Status |
|---|---|---|---|---|---|
| `anton-paar-rheometer` | Anton Paar MCR 72 / 92 / 102e / 302e / 502e under RheoCompass | rheometer | RheoCompass job folder + ASCII export folder | Windows | twin tested |
| `instron-bluehill-tester` | Instron 3400 / 5900 / 6800 series under Bluehill Universal | mechanical_tester | Bluehill Universal API (WCF) through pythonnet + results CSV export | Windows | template |
| `kla-dektak-profilometer` | Bruker Dektak XT / XT-A under Vision64 (KLA Alpha-Step D-500/D-600 by the same shape) | profilometer | Vision64 TCP/IP control server + .OPDx auto-save + database CSV | Windows | template |
| `panalytical-empyrean-xrd` | Malvern Panalytical Empyrean / Aeris under Data Collector | diffractometer | Data Collector job folder + .xrdml results folder | Windows | twin tested |
| `phenom-desktop-sem` | Thermo Fisher Scientific (Phenom-World) Phenom XL G2 / G3 (Pharos, ProX by the same interface) | electron_microscope | Phenom Programming Interface (PyPhenom), network | any | template |
| `quantum-design-ppms` | Quantum Design PPMS / DynaCool / MPMS3 (VersaLab and OptiCool by the same shape) | cryostat | MultiPyVu client to the MultiVu socket server (port 27183) | any | twin tested |
| `rigaku-smartlab-xrd` | Rigaku SmartLab / SmartLab SE / MiniFlex under SmartLab Studio II | diffractometer | Studio II job folder + .rasx/.ras results folder | Windows | twin tested |
| `tescan-sem` | TESCAN VEGA / MIRA / CLARA (SharkSEM remote control) | electron_microscope | SharkSEM TCP remote control, TESCAN client library | any | template |
| `zeiss-sem` | ZEISS EVO / Sigma / GeminiSEM under SmartSEM (Remote API) | electron_microscope | SmartSEM Remote API (COM), pywin32 | Windows | template |

## Energy storage

| Package | Instrument | Class | Talks through | Host | Status |
|---|---|---|---|---|---|
| `arbin-battery-cycler` | Arbin Instruments LBT / BT-2000 under MITS Pro (results-folder route) | battery_cycler | MITS Pro request folder + CSV export | Windows | template |
| `gamry-potentiostat` | Gamry Instruments Interface 1010 / Reference 620 (Electrochemistry Toolkit, GamryCOM) | potentiostat | GamryCOM (Electrochemistry Toolkit) via pywin32 | Windows | twin tested |
| `neware-battery-cycler` | Neware CT-4008 / BTS 8.0 (BTS server TCP interface) | battery_cycler | BTS server TCP API (XML, port 502) | any | template |

## Engineering and data acquisition

| Package | Instrument | Class | Talks through | Host | Status |
|---|---|---|---|---|---|
| `alicat-flow-controller` | Alicat Scientific MC / MCR mass flow controller (PC / PCD pressure controller compatible) | mass_flow_controller | serial, Alicat ASCII polling protocol (unit id) | any | twin tested |
| `bench-power-supply` | Rigol DP832 programmable DC power supply (DP831, DP821, DP811; Siglent and Aim-TTi by notes) | power_supply | SCPI over TCP 5555, VISA or USBTMC | any | twin tested |
| `labjack-t-series` | LabJack T4 / T7 / T8 (LJM library) | data_acquisition_device | labjack-ljm (LJM library) over USB or Ethernet | any | twin tested |
| `ni-daqmx` | National Instruments USB-6001/6008/6009, USB-621x, 63xx (NI-DAQmx) | data_acquisition_device | nidaqmx Python package on the NI-DAQmx runtime | any | twin tested |
| `rigol-oscilloscope` | Rigol DS1000Z / MSO1000Z oscilloscope (DS1054Z, DS1104Z; MSO5000 and DHO800/900 by notes) | oscilloscope | SCPI over TCP 5555, VISA or USBTMC | any | twin tested |
