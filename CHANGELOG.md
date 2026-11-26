# Changelog

## 0.3.0 – 2026-11-26
- Claude tab: ask Claude (via a local Claude Code install) about the live vehicle, parameters and logs; read-only.
- Flight modes: INAV-style range sliders with a live switch marker.
- Ports page for serial port and receiver setup.
- Red and black theme, and a Glass slider for window transparency (Linux and macOS).
- Serial ports are detected on Windows (COM) and macOS (/dev/cu.usbmodem); flight controllers are listed first.
- Install instructions for Windows and macOS.

## 0.2.0 – 2026-11-18
- First public release: Fly, Plan, 3D, Setup, Tune, Params, Graphs, Logs and Messages pages.
- MAVLink 2 over USB serial.
- Installable Python package (`flightdeck` command); assets moved into the package.
- Offline-capable map tile cache (Esri, OSM, Sentinel-2, MapTiler).
