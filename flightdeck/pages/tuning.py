import math

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QListWidget, QMessageBox, QScrollArea,
                               QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..theme import T
from ..widgets import Card, ParamForm, button, label

AXES = [("RLL", "Roll"), ("PIT", "Pitch"), ("YAW", "Yaw")]


def page(title, intro):
    w = QWidget()
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 0, 0, 0)
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    inner = QWidget()
    v = QVBoxLayout(inner)
    v.setContentsMargins(24, 20, 24, 24)
    v.setSpacing(14)
    v.addWidget(label(title, "H1"))
    if intro:
        v.addWidget(label(intro, "Muted", True))
    sc.setWidget(inner)
    outer.addWidget(sc)
    return w, v


def initial_params(prop_in, cells, hover=None):
    """ArduPilot 'initial tuning parameters' formulas (same as Mission Planner's calculator)."""
    gyro = max(20, round(289.22 * prop_in ** -0.838))
    out = {
        "MOT_THST_EXPO": round(min(max(0.15686 * math.log(prop_in) + 0.23693, 0.15), 0.80), 2),
        "INS_GYRO_FILTER": gyro,
        "ATC_RAT_RLL_FLTD": max(10, gyro / 2), "ATC_RAT_RLL_FLTT": max(10, gyro / 2),
        "ATC_RAT_PIT_FLTD": max(10, gyro / 2), "ATC_RAT_PIT_FLTT": max(10, gyro / 2),
        "ATC_RAT_YAW_FLTT": max(10, gyro / 2), "ATC_RAT_YAW_FLTE": 2,
        "INS_ACCEL_FILTER": 10,
        "MOT_BAT_VOLT_MAX": round(4.2 * cells, 2), "MOT_BAT_VOLT_MIN": round(3.3 * cells, 2),
        "ATC_THR_MIX_MAN": 0.1,
    }
    if hover:
        out["PSC_ACCZ_P"] = round(hover, 3)
        out["PSC_ACCZ_I"] = round(2 * hover, 3)
    return out


class TuningPage(QWidget):
    def __init__(self, link, meta, status):
        super().__init__()
        self.link = link
        self.meta = meta
        self.status = status
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        navw = QWidget()
        navw.setFixedWidth(210)
        nv = QVBoxLayout(navw)
        nv.setContentsMargins(12, 20, 8, 12)
        nv.addWidget(label("TUNING", "CardTitle"))
        self.nav = QListWidget()
        self.nav.setObjectName("SubNav")
        nv.addWidget(self.nav)
        root.addWidget(navw)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        for name, b in [("Starting point (5\")", self._initial), ("Rate PIDs", self._rates),
                        ("Angle & response", self._angle), ("Filters & notch", self._filters),
                        ("AutoTune", self._autotune), ("Motors & hover", self._motors)]:
            self.nav.addItem(name)
            self.stack.addWidget(b())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        link.params_loaded.connect(self._recalc)

    def form(self, rows, columns=1):
        return ParamForm(self.link, rows, self.meta, columns)

    # ---------- initial ----------
    def _initial(self):
        w, v = page("Starting point for your quad",
                    "ArduPilot's recommended first-flight values, calculated from prop size and battery. "
                    "Do this before the first hover, then run AutoTune.")
        c = Card("Your setup")
        r = QHBoxLayout()
        r.addWidget(label("Prop size"))
        self.prop = QDoubleSpinBox()
        self.prop.setRange(2, 30)
        self.prop.setDecimals(1)
        self.prop.setValue(5)
        self.prop.setSuffix(" in")
        r.addWidget(self.prop)
        r.addSpacing(20)
        r.addWidget(label("Battery"))
        self.cells = QSpinBox()
        self.cells.setRange(1, 14)
        self.cells.setValue(4)
        self.cells.setSuffix(" S")
        r.addWidget(self.cells)
        r.addStretch()
        c.add(r)
        self.prop.valueChanged.connect(self._recalc)
        self.cells.valueChanged.connect(self._recalc)
        v.addWidget(c)
        tc = Card("Suggested changes")
        self.sug = QTableWidget(0, 3)
        self.sug.setHorizontalHeaderLabels(["Parameter", "Now", "Suggested"])
        self.sug.verticalHeader().hide()
        self.sug.horizontalHeader().setStretchLastSection(True)
        self.sug.setMinimumHeight(330)
        tc.add(self.sug)
        rr = QHBoxLayout()
        self.sug_lbl = label("", "Faint")
        rr.addWidget(self.sug_lbl, 1)
        rr.addWidget(button("Apply suggestions", "primary", self._apply_initial))
        tc.add(rr)
        v.addWidget(tc)
        v.addWidget(label("These are conservative starting values, not a finished tune. Hover in Stabilize first; "
                          "if it oscillates, lower ATC_RAT_RLL_P / PIT_P by 25% before trying AutoTune.",
                          "Callout", True))
        v.addStretch()
        self._recalc()
        return w

    def _recalc(self, *_):
        P = self.link.params
        sug = initial_params(self.prop.value(), self.cells.value(), P.get("MOT_THST_HOVER"))
        self._sug = sug
        self.sug.setRowCount(len(sug))
        n_diff = 0
        for i, (k, val) in enumerate(sug.items()):
            cur = P.get(k)
            diff = cur is None or abs(cur - val) > 1e-3
            n_diff += diff and cur is not None
            items = [QTableWidgetItem(k), QTableWidgetItem("—" if cur is None else f"{cur:g}"),
                     QTableWidgetItem(f"{val:g}")]
            if diff and cur is not None:
                items[2].setForeground(QColor(T["warn"]))
            for c, it in enumerate(items):
                self.sug.setItem(i, c, it)
        self.sug_lbl.setText(f"{n_diff} differ from the drone" if P else "Connect to compare with the drone")

    def _apply_initial(self):
        P = self.link.params
        ch = {k: v for k, v in self._sug.items() if k in P and abs(P[k] - v) > 1e-3}
        if not ch:
            self.status("Nothing to change")
            return
        if QMessageBox.question(self, "Apply starting values?", f"Write {len(ch)} parameters?\n\n"
                                + "\n".join(f"{k}: {P[k]:g} → {v:g}" for k, v in ch.items())) == QMessageBox.Yes:
            self.link.write_params(ch, job="form")

    # ---------- rates ----------
    def _rates(self):
        w, v = page("Rate PIDs", "The inner loop that holds the drone's rotation rate. AutoTune sets these for you; "
                                 "edit by hand only for small adjustments.")
        for ax, name in AXES:
            c = Card(f"{name} rate")
            rows = [(f"ATC_RAT_{ax}_P", "P", 4, 0.005), (f"ATC_RAT_{ax}_I", "I", 4, 0.005),
                    (f"ATC_RAT_{ax}_D", "D", 5, 0.0005), (f"ATC_RAT_{ax}_FF", "Feed-forward", 4, 0.005),
                    (f"ATC_RAT_{ax}_IMAX", "I max", 3, 0.05), (f"ATC_RAT_{ax}_FLTT", "Target filter", 1, 1),
                    (f"ATC_RAT_{ax}_FLTD", "D filter", 1, 1), (f"ATC_RAT_{ax}_FLTE", "Error filter", 1, 1)]
            c.add(self.form(rows, columns=2))
            v.addWidget(c)
        v.addStretch()
        return w

    # ---------- angle ----------
    def _angle(self):
        w, v = page("Angle & response", "How strongly the drone levels itself, and how snappy stick input feels.")
        c = Card("Angle controller")
        c.add(self.form([("ATC_ANG_RLL_P", "Roll angle P", 2, 0.5), ("ATC_ANG_PIT_P", "Pitch angle P", 2, 0.5),
                         ("ATC_ANG_YAW_P", "Yaw angle P", 2, 0.5), ("ATC_INPUT_TC", "Stick response time", 2, 0.01),
                         ("ATC_ACCEL_R_MAX", "Roll accel max", 0, 1000), ("ATC_ACCEL_P_MAX", "Pitch accel max", 0, 1000),
                         ("ATC_ACCEL_Y_MAX", "Yaw accel max", 0, 1000), ("ANGLE_MAX", "Max lean angle (cdeg)", 0, 100)],
                        columns=2))
        v.addWidget(c)
        c2 = Card("Acro (rate mode)")
        c2.add(self.form([("ACRO_RP_RATE", "Roll/pitch rate °/s", 0, 10), ("ACRO_Y_RATE", "Yaw rate °/s", 0, 10),
                          ("ACRO_RP_EXPO", "Roll/pitch expo", 2, 0.05), ("ACRO_Y_EXPO", "Yaw expo", 2, 0.05),
                          ("ACRO_TRAINER", "Trainer", {0: "Off", 1: "Leveling", 2: "Leveling + limited"})],
                         columns=2))
        v.addWidget(c2)
        v.addStretch()
        return w

    # ---------- filters ----------
    def _filters(self):
        w, v = page("Filters & harmonic notch",
                    "The notch removes motor noise from the gyro. On a 5\" quad it is the biggest single improvement. "
                    "With bidirectional DShot, use ESC telemetry mode — it tracks motor RPM exactly.")
        c = Card("Low-pass filters")
        c.add(self.form([("INS_GYRO_FILTER", "Gyro filter (Hz)", 0, 5), ("INS_ACCEL_FILTER", "Accel filter (Hz)", 0, 1)],
                        columns=2))
        v.addWidget(c)
        c2 = Card("Harmonic notch")
        c2.add(self.form([("INS_HNTCH_ENABLE", "Enable", {0: "Off", 1: "On (reboot, then reload)"}),
                          ("INS_HNTCH_MODE", "Tracking", {0: "Fixed", 1: "Throttle", 2: "RPM sensor",
                                                          3: "ESC telemetry (bidir DShot)", 4: "In-flight FFT"}),
                          ("INS_HNTCH_FREQ", "Base frequency (Hz)", 0, 5), ("INS_HNTCH_BW", "Bandwidth (Hz)", 0, 5),
                          ("INS_HNTCH_REF", "Reference", 3, 0.01), ("INS_HNTCH_ATT", "Attenuation (dB)", 0, 5),
                          ("INS_HNTCH_HMNCS", "Harmonics (bitmask)", 0, 1), ("INS_HNTCH_OPTS", "Options (bitmask)", 0, 1)],
                         columns=2))
        v.addWidget(c2)
        v.addWidget(label("To use ESC-telemetry tracking: set SERVO_BLH_BDMASK = 15 (motors 1–4) and SERVO_BLH_POLES = "
                          "your motor's magnet poles (usually 14), make sure the ESC runs Bluejay/BLHeli_32, reboot, "
                          "then set mode 3, frequency ≈ 80 Hz and bandwidth ≈ 40 Hz as a start.", "Callout", True))
        v.addStretch()
        return w

    # ---------- autotune ----------
    def _autotune(self):
        w, v = page("AutoTune", "The drone tunes itself in flight with a series of small twitches on each axis.")
        c = Card("Settings")
        c.add(self.form([("AUTOTUNE_AXES", "Axes", {7: "Roll + pitch + yaw", 3: "Roll + pitch", 1: "Roll", 2: "Pitch",
                                                    4: "Yaw"}),
                         ("AUTOTUNE_AGGR", "Aggressiveness (0.05–0.10)", 3, 0.005)]))
        v.addWidget(c)
        c2 = Card("Switch")
        r = QHBoxLayout()
        r.addWidget(label("Put AutoTune on channel"))
        self.at_ch = QComboBox()
        for i in range(6, 13):
            self.at_ch.addItem(f"Channel {i}", i)
        self.at_ch.setCurrentIndex(1)
        r.addWidget(self.at_ch)
        r.addStretch()
        r.addWidget(button("Assign switch", "primary", self._assign_at))
        c2.add(r)
        c2.add(label("Sets RCx_OPTION = 17 (AutoTune) on that channel. Use a 2-position switch.", "Faint"))
        v.addWidget(c2)
        v.addWidget(label(
            "<b>How to run it</b><br>1. Calm day, open field, full battery.<br>2. Take off in <b>AltHold</b>, climb "
            "to about 10–15 m.<br>3. Flip the AutoTune switch on. Let it twitch; only nudge sticks to stay in place "
            "(moving sticks pauses it).<br>4. Takes 5–10 min for roll + pitch. When done it holds the new tune.<br>"
            "5. Land <b>with the switch still on</b> and disarm — that saves the tune. Landing with the switch off "
            "discards it.", "Callout", True))
        v.addStretch()
        return w

    def _assign_at(self):
        ch = self.at_ch.currentData()
        name = f"RC{ch}_OPTION"
        if name not in self.link.params:
            self.status("Parameters not loaded yet")
            return
        self.link.write_params({name: 17}, job="form")

    # ---------- motors ----------
    def _motors(self):
        w, v = page("Motors & hover", "Idle speeds and hover throttle. MOT_SPIN_ARM must stay below MOT_SPIN_MIN.")
        c = Card("Motor output")
        c.add(self.form([("MOT_SPIN_ARM", "Spin when armed", 3, 0.01), ("MOT_SPIN_MIN", "Minimum in flight", 3, 0.01),
                         ("MOT_SPIN_MAX", "Maximum", 3, 0.01), ("MOT_THST_EXPO", "Thrust curve expo", 2, 0.01),
                         ("MOT_THST_HOVER", "Hover throttle (learned)", 3, 0.01),
                         ("MOT_HOVER_LEARN", "Learn hover", {0: "Off", 1: "Learn", 2: "Learn and save"}),
                         ("MOT_PWM_TYPE", "ESC protocol", {0: "Normal PWM", 1: "OneShot", 2: "OneShot125", 4: "DShot150",
                                                           5: "DShot300", 6: "DShot600", 7: "DShot1200"})],
                        columns=2))
        v.addWidget(c)
        v.addStretch()
        return w
