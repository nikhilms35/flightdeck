# FlightDeck

A lightweight desktop ground control station for ArduPilot (Copter, Plane, Rover, Sub) and PX4, written in Python with Qt (PySide6).

## Features

- **Fly**: live telemetry, flight modes, and a satellite map with the vehicle's position
- **Plan**: mission planning on the map
- **3D**: 3D view of the vehicle and terrain (CesiumJS)
- **Setup**: vehicle setup and flight-mode configuration
- **Tune**: tuning helpers
- **Params**: full parameter list with ArduPilot descriptions
- **Graphs**: real-time telemetry plots
- **Logs**: list and download dataflash logs from the vehicle
- **Ports**: serial port and receiver setup
- **Messages**: status text and MAVLink messages
- **Claude**: ask Claude about your drone, parameters and logs from inside the app (optional, see below)

Connects over USB serial using MAVLink 2.

## Supported flight controllers

FlightDeck works with **any flight controller board** running a firmware that speaks MAVLink. When you connect, it
reads the firmware and vehicle type from the vehicle and adapts. To override that, click the firmware pill at the
left of the top bar.

| Firmware | Support |
|---|---|
| **ArduCopter** (quad, hexa, octa, tri, Y6, heli) | Full: every page. Motor test and motor direction diagrams for Quad X/+, Hexa X/+ and Octa X |
| **ArduPlane** (including QuadPlane) | Full except the multirotor pages (motor test, motor direction, Tune) |
| **ArduRover** (rovers and boats) | Full except the multirotor pages |
| **ArduSub** | Basic: telemetry, modes, parameters with descriptions, logs, sensor calibration and battery failsafe |
| **PX4** | Basic: telemetry, map, modes, arming, radio check, mode switch and the raw parameter list. Use QGroundControl for PX4 sensor calibration and airframe setup |
| **Betaflight, INAV** | Not supported. They use their own MSP protocol, not MAVLink |

Most F4, F7 and H7 boards sold for Betaflight or INAV can be flashed with ArduPilot. Check the
[ArduPilot firmware list](https://firmware.ardupilot.org/) for your board.

## Install

FlightDeck runs on **Windows 10/11, macOS 12+ and Linux**. You need **Python 3.10 or newer**.

First download `flightdeck_gcs-…-py3-none-any.whl` from the
[latest release](https://github.com/nikhilms35/flightdeck/releases/latest). The same file works on every system.

### Windows

1. Install Python from [python.org/downloads](https://www.python.org/downloads/). On the installer's
   first screen, tick **"Add python.exe to PATH"**.
2. Open **PowerShell** in your Downloads folder and run:

   ```powershell
   py -m venv $HOME\flightdeck-venv
   & $HOME\flightdeck-venv\Scripts\pip install (Get-Item flightdeck_gcs-*.whl).FullName
   & $HOME\flightdeck-venv\Scripts\flightdeck
   ```

3. Plug in the flight controller. It shows up as a `COM` port (for example `COM3`) in the port list at the top
   right. Windows 10 and 11 need no driver for ArduPilot boards.

To start it again later, run `& $HOME\flightdeck-venv\Scripts\flightdeck`.

### macOS

1. Install Python from [python.org/downloads](https://www.python.org/downloads/), or with Homebrew:
   `brew install python`.
2. Open **Terminal** in your Downloads folder and run:

   ```bash
   python3 -m venv ~/flightdeck-venv
   ~/flightdeck-venv/bin/pip install flightdeck_gcs-*.whl
   ~/flightdeck-venv/bin/flightdeck
   ```

3. Plug in the flight controller. It appears as `/dev/cu.usbmodem…` in the port list. No driver is needed.

To start it again later, run `~/flightdeck-venv/bin/flightdeck`.

### Linux

```bash
python3 -m venv ~/flightdeck-venv
~/flightdeck-venv/bin/pip install flightdeck_gcs-*.whl
~/flightdeck-venv/bin/flightdeck
```

To access the serial port, add your user to the `dialout` group: `sudo usermod -aG dialout $USER`,
then log out and back in. The board appears as `/dev/ttyACM0`.

### From source (any system)

```bash
git clone https://github.com/nikhilms35/flightdeck.git
cd flightdeck
python3 -m venv .venv
.venv/bin/pip install -e .        # Windows: .venv\Scripts\pip install -e .
.venv/bin/flightdeck              # Windows: .venv\Scripts\flightdeck
```

USB telemetry radios (FTDI, CP210x and CH340 chips) are listed after flight controllers in the port list. Some
of those chips need a driver on Windows or macOS from the chip maker's website.

## Maps

Esri satellite imagery, Sentinel-2, and OpenStreetMap work without setup. For sharper
imagery, add a free [MapTiler](https://www.maptiler.com/) API key from the map status pill
in the app. The key is stored in your local settings, never in the repository.

## Claude assistant (optional)

The **Claude** tab lets you ask questions like *"Why won't it arm?"* or *"Are my failsafes sensible
for 4S?"* and get answers based on your live vehicle. It runs the
[Claude Code](https://claude.com/claude-code) command-line tool on your computer, under your own
Claude account. FlightDeck holds no API key and has no account of its own.

To use it:

1. Install Claude Code:
   - macOS / Linux: `curl -fsSL https://claude.ai/install.sh | bash`
   - Windows (PowerShell): `irm https://claude.ai/install.ps1 | iex`

   Other options are on [claude.com/claude-code](https://claude.com/claude-code).
2. Run `claude` once in a terminal and sign in with a Claude Pro or Max plan, or with an
   Anthropic API key (billed per use).
3. Start FlightDeck (restart it if it was open) and open the **Claude** tab.

Everything else in FlightDeck works without it. If `claude` isn't installed, the tab explains how to set it up.

**What Claude sees:** each time you press Send, a snapshot of the vehicle is sent with your question:
mode, armed state, attitude, altitude, GPS fix and satellite count, battery, RC channels, vibration and
recent pre-arm messages. The GPS position is not included. When parameters are loaded, the full list is
written to `~/.cache/flightdeck/params.txt` so Claude can read it. Claude can also read FlightDeck's own code.

**What Claude can't do:** it has read-only tools. It can't arm, change modes, write parameters or send
any command to the vehicle. It tells you what to change, and you change it yourself.

## Appearance

The **Glass** slider in the status bar makes the window see-through (needs a desktop with compositing,
which is the default on GNOME, KDE and macOS). Maps and the 3D view stay solid. It is turned off on Windows,
where Qt can't draw a see-through window together with the maps.

## Safety

This is hobby software and comes with no warranty. Always keep a way to take manual control,
and test with propellers removed.

## License

MIT. See [LICENSE](LICENSE). Bundled third-party assets keep their own licenses, listed in [THIRD_PARTY.md](THIRD_PARTY.md).
