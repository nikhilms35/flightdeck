# Changelog

## 0.4.0 – 2026-11-26
- Works with ArduPlane, ArduRover, ArduSub and PX4 as well as ArduCopter. The firmware is detected from the vehicle,
  and can be overridden from the new firmware pill in the top bar.
- Mode lists, the Return/Land buttons, the mode-switch page and parameter descriptions follow the firmware.
  Setup and the main pages show only what applies.
- Motor test and motor direction support Hexa X/+, Octa X and Quad + as well as Quad X, with a frame preview.
- Battery, failsafe and geofence options come from the firmware's own parameter descriptions.
- Logs decode flight modes for the vehicle that wrote the log.
- Parameter description files are now gzipped (four vehicles in less space than one before).

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
