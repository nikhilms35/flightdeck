# Contributing to FlightDeck

Thanks for helping! Bug reports, fixes, and new features are all welcome.

## Reporting a bug
Open an issue using the **Bug report** template. Please include your OS, Python
version, flight controller / ArduPilot firmware version, and how you connected
(USB serial port, baud rate). Logs or screenshots help a lot.

## Making a change
1. Fork the repo and create a branch from `main`.
2. Set up a dev environment:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ./run.sh
   ```
3. Keep changes focused; one feature or fix per pull request.
4. **Test safely:** use SITL (ArduPilot's simulator) or a vehicle with propellers removed.
5. Describe what you changed and how you tested it in the pull request.

## Licensing
By contributing you agree your code is released under the project's MIT license.
Do not add third-party files without listing them in `THIRD_PARTY.md`.
