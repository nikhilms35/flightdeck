# Third-party components

FlightDeck's own code is MIT licensed (see `LICENSE`). The `assets/` folder bundles
these third-party files, each under its own license:

| Component | Path | License |
|---|---|---|
| Leaflet 1.9.4 | `assets/leaflet/` | BSD-2-Clause |
| CesiumJS | `assets/cesium/` | Apache-2.0 (see `assets/cesium/LICENSE.md`) |
| Qt WebChannel JS | `assets/qwebchannel.js` | LGPL-3.0 / GPL-2.0 / GPL-3.0 (see file header) |
| Inter font | `assets/fonts/InterVariable.ttf` | SIL OFL 1.1 (see `assets/fonts/Inter-LICENSE.txt`) |
| JetBrains Mono font | `assets/fonts/JetBrainsMono-*.ttf` | SIL OFL 1.1 (see `assets/fonts/JetBrainsMono-OFL.txt`) |
| ArduCopter parameter metadata | `assets/ArduCopter.apm.pdef.xml` | GPL-3.0 (ArduPilot project) |

Python dependencies (installed via `requirements.txt`, not bundled): PySide6 (LGPL-3.0),
pymavlink (LGPL-3.0), pyserial (BSD-3-Clause), pyqtgraph (MIT), NumPy (BSD-3-Clause).

Map imagery is fetched at runtime from Esri, MapTiler, Sentinel-2 and OpenStreetMap,
each subject to its provider's terms of use.
