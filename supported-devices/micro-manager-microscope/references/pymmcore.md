# MMCore calls used by this package

Source: pymmcore-plus API reference (pymmcore-plus.github.io/pymmcore-plus/api/cmmcoreplus/, read November 2026,
which lists the CMMCorePlus overrides and the inherited CMMCore methods) and the MMCore API that pymmcore wraps.
Micro-Manager's `MMConfig_demo.cfg` (DemoCamera, demo XY and Z stages, a `Channel` group with DAPI, FITC,
Rhodamine, Cy5) is the shape of the twin.

| Call | Used for | Status |
|---|---|---|
| `CMMCorePlus()` | one core per process | verified |
| `core.loadSystemConfiguration(path)` / `loadSystemConfiguration()` (no argument: the bundled demo config) | open | verified (CMMCorePlus override) |
| `core.unloadAllDevices()` | close | verified |
| `core.getCameraDevice()`, `getXYStageDevice()`, `getFocusDevice()` | device labels | verified |
| `core.getExposure()`, `core.setExposure(ms)` | exposure | verified |
| `core.snapImage()`, `core.getImage()` (numpy array) | snap | verified; that the array's dtype is uint8 or uint16 and C-ordered row-major is **unverified** for every camera |
| `core.getImageWidth()`, `getImageHeight()`, `getBytesPerPixel()` | TIFF header | verified |
| `core.getXYPosition()` -> (x, y), `core.setXYPosition(x, y)` | XY | verified |
| `core.getPosition()`, `core.setPosition(z)` | Z (focus device) | verified (listed without signature) |
| `core.waitForDevice(label)` | wait for a stage | verified |
| `core.getAvailableConfigGroups()`, `getAvailableConfigs(group)`, `getCurrentConfig(group)`, `setConfig(group, preset)` | channels | verified |
| `core.waitForConfig(group, preset)` | wait for the preset | **unverified** (an MMCore method as remembered; remove if the installed pymmcore lacks it) |
| `core.stop(label)` | e-stop on XY and focus stages | verified ("stops the XY or focus/Z stage motors") |

Not used: `core.snap()` (CMMCorePlus convenience), `getProperty`/`setProperty` (per-device properties),
`startSequenceAcquisition`, the MDA engine (`core.mda`), `setPixelSizeConfig`.

## TIFF

`write_tiff` in driver.py writes a baseline TIFF (little-endian, one strip, PhotometricInterpretation
BlackIsZero, 8 or 16 bits per sample, no compression) so no image library is needed on either side. Any
TIFF reader opens it; pixel size and stage position are in the job result, not in the file.
