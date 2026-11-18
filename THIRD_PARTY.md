# Third-party components

FlightDeck's own code is MIT licensed (see `LICENSE`). The `flightdeck/assets/` folder bundles
these third-party files, each under its own license:

| Component | Path | License |
|---|---|---|
| Leaflet 1.9.4 | `flightdeck/assets/leaflet/` | BSD-2-Clause |
| CesiumJS | `flightdeck/assets/cesium/` | Apache-2.0 (see `flightdeck/assets/cesium/LICENSE.md`) |
| Qt WebChannel JS | `flightdeck/assets/qwebchannel.js` | LGPL-3.0 / GPL-2.0 / GPL-3.0 (see file header) |
| Inter font | `flightdeck/assets/fonts/InterVariable.ttf` | SIL OFL 1.1 (see `flightdeck/assets/fonts/Inter-LICENSE.txt`) |
| JetBrains Mono font | `flightdeck/assets/fonts/JetBrainsMono-*.ttf` | SIL OFL 1.1 (see `flightdeck/assets/fonts/JetBrainsMono-OFL.txt`) |
| ArduCopter parameter metadata | `flightdeck/assets/ArduCopter.apm.pdef.xml` | GPL-3.0 (ArduPilot project) |

Python dependencies (installed via `requirements.txt`, not bundled): PySide6 (LGPL-3.0),
pymavlink (LGPL-3.0), pyserial (BSD-3-Clause), pyqtgraph (MIT), NumPy (BSD-3-Clause).

Map imagery is fetched at runtime from Esri, MapTiler, Sentinel-2 and OpenStreetMap,
each subject to its provider's terms of use.
