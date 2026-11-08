import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
                               QScrollArea, QSplitter, QVBoxLayout, QWidget)

from ..link import COPTER_MODES
from ..mapview import MapView
from ..theme import T
from ..widgets import HUD, Card, Tile, button, label

# PreArm text fragment -> what to do about it
PREARM_HINTS = [
    ("RC not calibrated", "Calibrate your radio: Setup › Radio."),
    ("RC not found", "No receiver signal. Check ELRS bind (solid LED) and wiring on UART2."),
    ("Radio failsafe", "No receiver signal. Turn on the Pocket and check the ELRS link."),
    ("Throttle below failsafe", "Throttle channel is below FS_THR_VALUE. Calibrate the radio."),
    ("3D Accel calibration needed", "Run the accelerometer calibration: Setup › Accelerometer."),
    ("Accels inconsistent", "Accels disagree. Re-run accel calibration and keep the FC still."),
    ("Compass not calibrated", "Calibrate compass outdoors: Setup › Compass."),
    ("Compass offsets too high", "Compass picking up interference. Move GPS mast away from power wires."),
    ("compasses inconsistent", "Internal and external compass disagree. Check GPS orientation."),
    ("GPS", "Waiting for GPS. Go outside with clear sky view."),
    ("Need Position Estimate", "EKF has no position yet. Wait for GPS 3D fix (~1–2 min)."),
    ("EKF", "EKF still settling. Keep the drone still for a minute."),
    ("Battery", "Battery below arming voltage, or not connected (USB only)."),
    ("Logging", "No log storage. Insert a microSD card or set LOG_BACKEND_TYPE."),
    ("Hardware safety switch", "Press the safety switch or set BRD_SAFETY_DEFLT = 0."),
    ("Motors", "Check the motor/ESC setup (MOT_PWM_TYPE, outputs)."),
    ("Check fence", "Geofence is enabled but has no valid position yet."),
    ("High GPS HDOP", "GPS accuracy is poor. Wait for more satellites."),
    ("Gyros", "Gyros not settled. Keep the drone completely still."),
]

QUICK_MODES = ["STABILIZE", "ALT_HOLD", "LOITER", "POSHOLD", "RTL", "LAND", "ACRO", "AUTO", "GUIDED", "BRAKE"]


def hint_for(text):
    for frag, hint in PREARM_HINTS:
        if frag.lower() in text.lower():
            return hint
    return ""


class FlyPage(QWidget):
    preview3d = Signal(float, float, float)

    def __init__(self, link):
        super().__init__()
        self.link = link
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        root.addWidget(split)

        # ---------- left column ----------
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(16, 16, 12, 16)
        lv.setSpacing(12)

        self.hud = HUD()
        self.hud.setMinimumHeight(250)
        lv.addWidget(self.hud, 3)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.t_alt = Tile("Altitude", "m")
        self.t_spd = Tile("Ground speed", "m/s")
        self.t_climb = Tile("Climb", "m/s")
        self.t_home = Tile("Home", "m")
        self.t_batt = Tile("Battery", "V")
        self.t_curr = Tile("Current", "A")
        self.t_gps = Tile("GPS", "sats")
        self.t_rc = Tile("RC link", "%")
        for i, t in enumerate([self.t_alt, self.t_spd, self.t_climb, self.t_home,
                               self.t_batt, self.t_curr, self.t_gps, self.t_rc]):
            grid.addWidget(t, i // 4, i % 4)
        lv.addLayout(grid)

        # controls
        ctl = Card("Flight control")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.mode_box = QComboBox()
        names = QUICK_MODES + sorted(set(COPTER_MODES.values()) - set(QUICK_MODES))
        self.mode_box.addItems(names)
        self.mode_box.setMinimumWidth(140)
        row.addWidget(self.mode_box)
        row.addWidget(button("Set mode", None, lambda: self.link.set_mode(self.mode_box.currentText())))
        row.addStretch()
        row.addWidget(button("RTL", "ghost", lambda: self.link.set_mode("RTL")))
        row.addWidget(button("Land", "ghost", lambda: self.link.set_mode("LAND")))
        self.arm_btn = button("Arm", "danger", self._toggle_arm)
        self.arm_btn.setMinimumWidth(110)
        row.addWidget(self.arm_btn)
        ctl.add(row)
        lv.addWidget(ctl)

        # pre-arm
        pa = Card("Ready to arm?")
        self.prearm_lbl = label("", wrap=True)
        self.prearm_lbl.setTextFormat(Qt.RichText)
        self.prearm_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.prearm_lbl)
        sc.setMinimumHeight(110)
        pa.add(sc, 1)
        lv.addWidget(pa, 2)

        split.addWidget(left)

        # ---------- map ----------
        self.map = MapView()
        self.map.bridge.context.connect(self._map_menu)
        split.addWidget(self.map)
        split.setSizes([620, 900])
        split.setStretchFactor(1, 1)

    # ---------- map right-click ----------
    def _map_menu(self, lat, lon):
        st = self.link.state
        menu = QMenu(self)
        fly = menu.addAction("✈  Fly here (Guided)…")
        home = menu.addAction("⌂  Set home here")
        prev = menu.addAction("◎  Preview this spot in 3D")
        menu.addSeparator()
        menu.addAction(f"{lat:.6f}, {lon:.6f}").setEnabled(False)
        fly.setEnabled(st.connected and st.armed)
        if not st.armed:
            fly.setText("✈  Fly here (Guided) — arm and take off first")
        home.setEnabled(st.connected)
        act = menu.exec(QCursor.pos())
        if act is fly:
            self._fly_here(lat, lon)
        elif act is home:
            if QMessageBox.question(self, "Set home?", "Move the home / RTL point here?\nThe drone will return to "
                                    "this spot on RTL.") == QMessageBox.Yes:
                self.link.set_home(lat, lon, st.alt_msl - st.alt_rel)
        elif act is prev:
            self.preview3d.emit(lat, lon, max(st.alt_rel, 30))

    def _fly_here(self, lat, lon):
        st = self.link.state
        alt, ok = QInputDialog.getDouble(self, "Fly here", "Altitude above home (m):",
                                         max(round(st.alt_rel), 15), 2, 120, 0)
        if not ok:
            return
        if st.mode != "GUIDED":
            if QMessageBox.question(self, "Switch to Guided?",
                                    f"The drone is in {st.mode}. Switch to GUIDED and fly to this point at "
                                    f"{alt:.0f} m?") != QMessageBox.Yes:
                return
            self.link.set_mode("GUIDED")
        self.link.guided_goto(lat, lon, alt)
        self.map.set_target(lat, lon)

    def _toggle_arm(self):
        st = self.link.state
        if st.armed:
            self.link.arm(False)
            return
        r = QMessageBox.warning(self, "Arm motors?",
                                "Motors will spin when armed.\n\nAre props clear of people and objects?",
                                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if r == QMessageBox.Yes:
            self.link.arm(True)

    def tick(self):
        st = self.link.state
        self.hud.set_attitude(st.roll, st.pitch, st.heading, st.armed, st.mode if st.connected else "")
        if not st.connected:
            return
        self.t_alt.set(f"{st.alt_rel:.1f}")
        self.t_spd.set(f"{st.groundspeed:.1f}")
        self.t_climb.set(f"{st.climb:+.1f}")
        d = st.dist_home()
        self.t_home.set(f"{d:.0f}" if d is not None else "—")
        cells = round(st.batt_v / 4.2) if st.batt_v > 5 else 0
        per = st.batt_v / cells if cells else 0
        bcol = T["danger"] if cells and per < 3.5 else T["warn"] if cells and per < 3.7 else None
        self.t_batt.set(f"{st.batt_v:.2f}", bcol,
                        f"{cells}S · {per:.2f} V/cell · {st.batt_mah:.0f} mAh" if cells else "no battery")
        self.t_curr.set(f"{st.batt_a:.1f}" if st.batt_a >= 0 else "—")
        fix = {0: "no GPS", 1: "no fix", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK float", 6: "RTK fixed"}.get(st.gps_fix, "?")
        gcol = T["ok"] if st.gps_fix >= 3 and st.sats >= 8 else T["warn"] if st.gps_fix >= 2 else T["danger"]
        self.t_gps.set(f"{st.sats}", gcol, f"{fix} · HDOP {st.hdop:.1f}")
        if st.rc_count == 0:
            self.t_rc.set("—", T["danger"], "no receiver")
        else:
            pct = round(st.rc_rssi / 2.54) if st.rc_rssi != 255 else None
            self.t_rc.set(f"{pct}" if pct is not None else "?",
                          T["ok"] if (pct or 0) > 60 else T["warn"] if (pct or 0) > 30 else T["danger"],
                          f"{st.rc_count} channels")

        self.arm_btn.setText("Disarm" if st.armed else "Arm")
        self.arm_btn.setProperty("kind", "ok" if st.armed else "danger")
        self.arm_btn.style().polish(self.arm_btn)

        now = time.time()
        live = {k: v for k, v in st.prearm.items() if now - v < 35}
        if live:
            rows = []
            for text in sorted(live):
                h = hint_for(text)
                rows.append(f"<div style='margin-bottom:8px'><span style='color:{T['danger']};font-weight:700'>●</span> "
                            f"<b>{text}</b>" + (f"<br><span style='color:{T['muted']}'>{h}</span>" if h else "") + "</div>")
            self.prearm_lbl.setText("".join(rows))
        else:
            self.prearm_lbl.setText(f"<span style='color:{T['ok']};font-weight:700'>●</span> "
                                    f"No pre-arm problems reported.")

        if st.lat is not None:
            self.map.set_vehicle(st.lat, st.lon, st.heading)
        if st.home_lat is not None:
            self.map.set_home(st.home_lat, st.home_lon)
            P = self.link.params
            on = int(P.get("FENCE_ENABLE", 0)) and int(P.get("FENCE_TYPE", 0)) & 2
            self.map.set_fence(st.home_lat, st.home_lon, float(P.get("FENCE_RADIUS", 0)) if on else 0)
