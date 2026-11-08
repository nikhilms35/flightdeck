# FlightDeck

A lightweight desktop ground control station for ArduPilot (ArduCopter), written in Python with Qt (PySide6).

## Features

- **Fly**: live telemetry, flight modes, and a satellite map with the vehicle's position
- **Plan**: mission planning on the map
- **3D**: 3D view of the vehicle and terrain (CesiumJS)
- **Setup**: vehicle setup and flight-mode configuration
- **Tune**: tuning helpers
- **Params**: full parameter list with ArduPilot descriptions
- **Graphs**: real-time telemetry plots
- **Logs**: list and download dataflash logs from the vehicle
- **Messages**: status text and MAVLink messages

Connects over USB serial using MAVLink 2.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/nikhilms35/flightdeck.git
cd flightdeck
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

On Linux, add your user to the `dialout` group to access the serial port: `sudo usermod -aG dialout $USER`, then log out and back in.

## Maps

Esri satellite imagery, Sentinel-2, and OpenStreetMap work without setup. For sharper
imagery, add a free [MapTiler](https://www.maptiler.com/) API key from the map status pill
in the app. The key is stored in your local settings, never in the repository.

## Safety

This is hobby software and comes with no warranty. Always keep a way to take manual control,
and test with propellers removed.

## License

MIT. See [LICENSE](LICENSE). Bundled third-party assets keep their own licenses, listed in [THIRD_PARTY.md](THIRD_PARTY.md).
