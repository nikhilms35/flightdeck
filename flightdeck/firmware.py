"""What FlightDeck knows about each autopilot firmware it can talk to over MAVLink.

The firmware is detected from the vehicle's HEARTBEAT (autopilot + vehicle type) and can be overridden by the user.
Everything firmware-specific - mode names and numbers, which buttons and Setup pages make sense, which parameter
descriptions to load - lives here, so pages ask `link.firmware` instead of assuming ArduCopter.
"""
import os
from dataclasses import dataclass, field

os.environ.setdefault("MAVLINK20", "1")
from pymavlink import mavutil  # noqa: E402

mavlink = mavutil.mavlink

# PX4's own flight-mode-switch slot values (COM_FLTMODE1..6), which are not the same as its custom_mode numbers
PX4_SWITCH_MODES = {-1: "Unassigned", 0: "Manual", 8: "Stabilized", 6: "Acro", 1: "Altitude", 2: "Position",
                    4: "Hold", 3: "Mission", 5: "Return", 11: "Land", 10: "Takeoff", 12: "Follow Me",
                    13: "Precision Land", 7: "Offboard"}


@dataclass(frozen=True)
class Firmware:
    key: str                     # copter | plane | rover | sub | px4
    name: str                    # shown to the user
    family: str                  # ardupilot | px4
    vehicle: str                 # "drone", "plane", "rover", "sub" - used in help text
    modes: dict                  # ArduPilot: custom_mode number -> name.  PX4: name -> (base, main, sub)
    quick_modes: tuple           # shown first in mode lists
    pdef: str | None             # bundled parameter-description file (ArduPilot only)
    rtl: str | None = None       # mode for the Return button
    land: tuple | None = None    # (mode, button text) for the Land/Surface button
    guided: str | None = None    # mode used for "fly here" on the map (None = not offered)
    # flight-mode switch: (channel param, slot param format, slot values {value: name}) or None
    mode_switch: tuple | None = None
    setup_pages: tuple = ()      # which Setup sub-pages apply
    pages: tuple = ()            # which main pages apply (beyond the always-on ones)
    notes: str = ""              # shown on Setup when support is partial
    suggested: str = ""          # suggested mode-switch layout, HTML
    extra: dict = field(default_factory=dict)

    # ---------- modes ----------
    def mode_name(self, base_mode, custom_mode):
        if self.family == "px4":
            return mavutil.interpret_px4_mode(base_mode, custom_mode)
        return self.modes.get(custom_mode, f"MODE {custom_mode}")

    def mode_names(self):
        names = list(self.modes) if self.family == "px4" else list(self.modes.values())
        quick = [m for m in self.quick_modes if m in names]
        return quick + sorted(set(names) - set(quick))

    def has_mode(self, name):
        return name in (self.modes if self.family == "px4" else self.modes.values())

    def set_mode_params(self, name):
        """Parameters for MAV_CMD_DO_SET_MODE, or None if this firmware has no such mode."""
        if self.family == "px4":
            if name not in self.modes:
                return None
            base, main, sub = self.modes[name]
            return (base, main, sub)
        num = next((k for k, v in self.modes.items() if v == name), None)
        if num is None:
            return None
        return (mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, num)

    def log_mode_name(self, num):
        """Mode name for the number stored in ArduPilot dataflash MODE messages."""
        if self.family == "px4":
            return str(num)
        return self.modes.get(num, "?")


ARDU_SETUP = ("Accelerometer", "Compass", "Radio", "Flight modes", "Battery & failsafe", "Geofence")
COPTER = Firmware(
    key="copter", name="ArduCopter", family="ardupilot", vehicle="drone",
    modes=dict(mavutil.mode_mapping_acm), pdef="ArduCopter.apm.pdef.xml.gz",
    quick_modes=("STABILIZE", "ALT_HOLD", "LOITER", "POSHOLD", "RTL", "LAND", "ACRO", "AUTO", "GUIDED", "BRAKE"),
    rtl="RTL", land=("LAND", "Land"), guided="GUIDED",
    mode_switch=("FLTMODE_CH", "FLTMODE{}", None),
    setup_pages=("Frame",) + ARDU_SETUP[:4] + ("Motor test", "Motor direction") + ARDU_SETUP[4:],
    pages=("Plan", "Ports", "Tune", "Params", "Logs"),
    suggested="Suggested for a first flight: <b>STABILIZE</b> / <b>ALT_HOLD</b> / <b>LOITER</b> on a 3-position "
              "switch, and put <b>RTL</b> within easy reach.",
)
PLANE = Firmware(
    key="plane", name="ArduPlane", family="ardupilot", vehicle="plane",
    modes=dict(mavutil.mode_mapping_apm), pdef="ArduPlane.apm.pdef.xml.gz",
    quick_modes=("MANUAL", "FBWA", "FBWB", "CRUISE", "STABILIZE", "LOITER", "CIRCLE", "RTL", "AUTO", "TAKEOFF",
                 "AUTOTUNE", "QSTABILIZE", "QHOVER", "QLOITER", "QLAND", "QRTL"),
    rtl="RTL",
    mode_switch=("FLTMODE_CH", "FLTMODE{}", None),
    setup_pages=ARDU_SETUP,
    pages=("Plan", "Ports", "Params", "Logs"),
    notes="ArduPlane: motor test, motor direction and the Tune page are for multirotors and are hidden. "
          "Check control surfaces move the right way in <b>MANUAL</b> before every first flight.",
    suggested="Suggested: <b>MANUAL</b> / <b>FBWA</b> / <b>AUTO</b> or <b>RTL</b> on a 3-position switch. "
              "FBWA is the easiest mode to fly a plane in.",
)
ROVER = Firmware(
    key="rover", name="ArduRover", family="ardupilot", vehicle="rover",
    modes=dict(mavutil.mode_mapping_rover), pdef="Rover.apm.pdef.xml.gz",
    quick_modes=("MANUAL", "ACRO", "STEERING", "HOLD", "LOITER", "AUTO", "RTL", "SMART_RTL", "GUIDED"),
    rtl="RTL", land=("HOLD", "Hold"), guided="GUIDED",
    mode_switch=("MODE_CH", "MODE{}", None),
    setup_pages=ARDU_SETUP,
    pages=("Plan", "Ports", "Params", "Logs"),
    notes="ArduRover / boat: the multirotor motor pages and the Tune page are hidden.",
    suggested="Suggested: <b>MANUAL</b> / <b>HOLD</b> / <b>AUTO</b> on a 3-position switch, with <b>RTL</b> "
              "within reach.",
)
SUB = Firmware(
    key="sub", name="ArduSub", family="ardupilot", vehicle="sub",
    modes=dict(mavutil.mode_mapping_sub), pdef="ArduSub.apm.pdef.xml.gz",
    quick_modes=("MANUAL", "STABILIZE", "ALT_HOLD", "POSHOLD", "ACRO", "SURFACE", "AUTO", "GUIDED", "CIRCLE"),
    land=("SURFACE", "Surface"),
    setup_pages=("Accelerometer", "Compass", "Battery & failsafe"),
    pages=("Ports", "Params", "Logs"),
    notes="ArduSub support is basic: telemetry, modes, parameters, logs and sensor calibration. ArduSub is "
          "flown with a joystick, so there is no mode-switch page; thruster setup is done in QGroundControl.",
)
PX4 = Firmware(
    key="px4", name="PX4", family="px4", vehicle="vehicle",
    modes=dict(mavutil.px4_map), pdef=None,
    quick_modes=("MANUAL", "STABILIZED", "ALTCTL", "POSCTL", "LOITER", "MISSION", "RTL", "LAND", "TAKEOFF", "ACRO"),
    rtl="RTL", land=("LAND", "Land"),
    mode_switch=("RC_MAP_FLTMODE", "COM_FLTMODE{}", PX4_SWITCH_MODES),
    setup_pages=("Radio", "Flight modes"),
    pages=("Params",),
    notes="PX4 support is basic: telemetry, map, mode changes, arming, radio check, the mode switch and the "
          "raw parameter list (without descriptions). Do sensor calibration, airframe and failsafe setup in "
          "QGroundControl.",
    suggested="Suggested: <b>Position</b> / <b>Altitude</b> / <b>Manual</b> (or <b>Stabilized</b>) on a "
              "3-position switch, with <b>Return</b> within reach.",
)

ALL = {f.key: f for f in (COPTER, PLANE, ROVER, SUB, PX4)}
DEFAULT = COPTER

_TYPE_TO_KEY = {}
for _t, _m in mavutil.AP_MAV_TYPE_MODE_MAP.items():
    if _m is mavutil.mode_mapping_acm:
        _TYPE_TO_KEY[_t] = "copter"
    elif _m is mavutil.mode_mapping_apm:
        _TYPE_TO_KEY[_t] = "plane"
    elif _m is mavutil.mode_mapping_rover:
        _TYPE_TO_KEY[_t] = "rover"
    elif _m is mavutil.mode_mapping_sub:
        _TYPE_TO_KEY[_t] = "sub"
# VTOL types ArduPlane can report that older pymavlink tables may miss
for _name in ("MAV_TYPE_VTOL_TAILSITTER_DUOROTOR", "MAV_TYPE_VTOL_TAILSITTER_QUADROTOR", "MAV_TYPE_VTOL_TILTWING",
              "MAV_TYPE_VTOL_FIXEDROTOR", "MAV_TYPE_VTOL_TAILSITTER", "MAV_TYPE_VTOL_RESERVED2"):
    if hasattr(mavlink, _name):
        _TYPE_TO_KEY.setdefault(getattr(mavlink, _name), "plane")


def detect(autopilot, mav_type):
    """(Firmware or None, description). None means FlightDeck can't tell, and keeps the current choice."""
    if autopilot == mavlink.MAV_AUTOPILOT_PX4:
        return PX4, "PX4"
    if autopilot == mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
        key = _TYPE_TO_KEY.get(mav_type)
        if key:
            return ALL[key], ALL[key].name
        return None, f"ArduPilot (vehicle type {mav_type} not supported)"
    names = mavlink.enums["MAV_AUTOPILOT"]
    return None, (names[autopilot].name.replace("MAV_AUTOPILOT_", "") if autopilot in names else f"autopilot {autopilot}")
