import sys
import time

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QMainWindow, QSlider,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from . import theme
from .link import Link, serial_ports
from .tileserver import TILES

TILES.start()  # before any map page is created

from .pages.claude import ClaudePage  # noqa: E402
from .pages.fly import FlyPage  # noqa: E402
from .pages.graphs import GraphsPage  # noqa: E402
from .pages.logs import LogsPage  # noqa: E402
from .pages.messages import MessagesPage  # noqa: E402
from .pages.params import ParamsPage  # noqa: E402
from .pages.plan import PlanPage  # noqa: E402
from .pages.ports import PortsPage  # noqa: E402
from .pages.setup import SetupPage  # noqa: E402
from .pages.tuning import TuningPage  # noqa: E402
from .pages.view3d import View3DPage  # noqa: E402
from .widgets import Pill, button, label  # noqa: E402

def mavutil_geofence_bit():
    from .link import mavlink
    return mavlink.MAV_SYS_STATUS_GEOFENCE


BAUDS = ["115200", "57600", "921600", "460800", "230400", "38400"]


def list_serial():
    return [(dev, label) for dev, label, _ in serial_ports()]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FlightDeck")
        # Glass (see-through window) works on Linux and macOS; on Windows a translucent framed window with
        # embedded web views renders black, so it is turned off there.
        self.glass_ok = sys.platform != "win32"
        if self.glass_ok:
            self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1480, 920)
        self.settings = QSettings("FlightDeck", "FlightDeck")
        key = self.settings.value("maptiler_key", "")
        if key:
            TILES.set_key("maptiler", key)
        self.link = Link()

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._topbar())
        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)

        self.stack = QStackedWidget()
        self.fly = FlyPage(self.link)
        self.plan = PlanPage(self.link, self.show_status)
        self.view3d = View3DPage(self.link, self.plan, self.show_status)
        self.setup = SetupPage(self.link, self.show_status)
        self.params = ParamsPage(self.link, self.show_status)
        self.tuning = TuningPage(self.link, self.params.meta, self.show_status)
        self.ports = PortsPage(self.link, self.params.meta, self.show_status)
        self.graphs = GraphsPage(self.link)
        self.logs = LogsPage(self.link, self.show_status)
        self.msgs = MessagesPage(self.link)
        self.claude = ClaudePage(self.link)
        pages = [("Fly", self.fly), ("Plan", self.plan), ("3D", self.view3d), ("Setup", self.setup),
                 ("Ports", self.ports), ("Tune", self.tuning), ("Params", self.params), ("Graphs", self.graphs), ("Logs", self.logs),
                 ("Messages", self.msgs), ("Claude", self.claude)]
        body.addWidget(self._sidebar(pages))
        self.plan.preview3d.connect(self._open_3d)
        self.fly.preview3d.connect(self._open_3d)
        for _, p in pages:
            self.stack.addWidget(p)
        body.addWidget(self.stack, 1)

        bar = QFrame()
        bar.setObjectName("StatusBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 6, 16, 6)
        self.status_lbl = label("Not connected", "StatusText")
        bl.addWidget(self.status_lbl, 1)
        self.hb_lbl = label("", "StatusText")
        bl.addWidget(self.hb_lbl)
        bl.addSpacing(16)
        bl.addWidget(label("Glass", "StatusText"))
        self.glass = QSlider(Qt.Horizontal)
        self.glass.setRange(0, 60)            # % see-through
        self.glass.setFixedWidth(110)
        self.glass.setToolTip("Window transparency. Maps and the 3D view stay solid.")
        self.glass.setValue(int(self.settings.value("glass", 0)))
        bl.addWidget(self.glass)
        if not self.glass_ok:
            self.glass.setValue(0)
            for wdg in (self.glass, bl.itemAt(bl.count() - 2).widget()):
                wdg.hide()
        outer.addWidget(bar)
        self._glass_timer = QTimer(self, singleShot=True, interval=60, timeout=self._apply_glass)
        self.glass.valueChanged.connect(lambda _: self._glass_timer.start())
        self._apply_glass()

        self.link.connection_changed.connect(self._conn_changed)
        self.link.statustext.connect(self._statustext)
        self.link.params_progress.connect(self._params_progress)
        self.link.job_status.connect(self._job_status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(100)
        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(self._refresh_ports)
        self.port_timer.start(2000)

    # ---------- chrome ----------
    def _topbar(self):
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(58)
        h = QHBoxLayout(top)
        h.setContentsMargins(18, 8, 14, 8)
        h.setSpacing(8)
        h.addWidget(label("Flight", "Wordmark"))
        h.addWidget(label("Deck", "WordmarkAccent"))
        h.addSpacing(24)

        self.p_link = Pill("OFFLINE")
        self.p_mode = Pill("MODE —")
        self.p_arm = Pill("DISARMED")
        self.p_gps = Pill("GPS —")
        self.p_batt = Pill("BATT —")
        self.p_rc = Pill("RC —")
        self.p_fence = Pill("FENCE —")
        self.p_fence.setToolTip("Geofence. Click to turn it on or off (writes FENCE_ENABLE on the drone).")
        self.p_fence.setCursor(Qt.PointingHandCursor)
        self.p_fence.mousePressEvent = lambda e: self._toggle_fence()
        self.p_map = Pill("MAP")
        self.p_map.setToolTip("Which map source is in use. Click to add a MapTiler key for sharp HD satellite.")
        self.p_map.setCursor(Qt.PointingHandCursor)
        self.p_map.mousePressEvent = lambda e: self._map_key_dialog()
        for p in (self.p_link, self.p_mode, self.p_arm, self.p_gps, self.p_batt, self.p_rc, self.p_fence, self.p_map):
            h.addWidget(p)
        h.addStretch()

        self.port_box = QComboBox()
        self.port_box.setMinimumWidth(180)
        self.port_box.setMaximumWidth(300)
        self.port_box.setEditable(True)
        self.port_box.setInsertPolicy(QComboBox.NoInsert)
        self.baud_box = QComboBox()
        self.baud_box.addItems(BAUDS)
        self.baud_box.setCurrentText(self.settings.value("baud", "115200"))
        self._refresh_ports()
        last = self.settings.value("port", "")
        if last:
            self.port_box.setCurrentText(last)
        h.addWidget(self.port_box)
        h.addWidget(self.baud_box)
        self.conn_btn = button("Connect", "primary", self._toggle_connect)
        self.conn_btn.setMinimumWidth(110)
        h.addWidget(self.conn_btn)
        return top

    def _sidebar(self, pages):
        side = QFrame()
        side.setObjectName("SideBar")
        side.setFixedWidth(92)
        v = QVBoxLayout(side)
        v.setContentsMargins(10, 14, 10, 14)
        v.setSpacing(6)
        grp = QButtonGroup(self)
        glyph = {"Fly": "◎", "Plan": "⌖", "3D": "◭", "Setup": "⚙", "Ports": "⇄", "Tune": "≈", "Params": "☰", "Graphs": "∿",
                 "Logs": "▤", "Messages": "✉", "Claude": "✳"}
        self.nav_buttons = []
        for i, (name, _) in enumerate(pages):
            b = QToolButton()
            b.setObjectName("Nav")
            b.setText(f"{glyph[name]}\n{name}")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setMinimumSize(72, 56)
            self.nav_buttons.append(b)
            grp.addButton(b, i)
            v.addWidget(b)
            if i == 0:
                b.setChecked(True)
        grp.idClicked.connect(self.stack.setCurrentIndex)
        v.addStretch()
        return side

    def _refresh_ports(self):
        ports = list_serial()
        current = self.port_box.currentText()
        have = [self.port_box.itemData(i) for i in range(self.port_box.count())]
        if [p for p, _ in ports] == have:
            return
        self.port_box.blockSignals(True)
        self.port_box.clear()
        for dev, text in ports:
            self.port_box.addItem(text, dev)
        if current:
            self.port_box.setCurrentText(current)
        self.port_box.blockSignals(False)

    def _selected_port(self):
        i = self.port_box.currentIndex()
        txt = self.port_box.currentText().strip()
        if i >= 0 and self.port_box.itemText(i) == txt:
            return self.port_box.itemData(i)
        return txt.split()[0] if txt else ""

    # ---------- connection ----------
    def _toggle_connect(self):
        if self.link.is_open:
            self.link.disconnect()
            return
        port = self._selected_port()
        if not port:
            self.show_status("No port selected — plug in the flight controller")
            return
        baud = int(self.baud_box.currentText())
        self.settings.setValue("port", self.port_box.currentText())
        self.settings.setValue("baud", str(baud))
        self.link.connect_to(port, baud)
        self.conn_btn.setText("Disconnect")
        self.conn_btn.setProperty("kind", None)
        self.conn_btn.style().polish(self.conn_btn)

    def _conn_changed(self, ok, msg):
        self.show_status(msg)
        if not self.link.is_open and msg == "Disconnected":
            self.conn_btn.setText("Connect")
            self.conn_btn.setProperty("kind", "primary")
            self.conn_btn.style().polish(self.conn_btn)

    def _statustext(self, sev, text):
        self.show_status(text)

    def _params_progress(self, n, total):
        if total and n < total:
            self.show_status(f"Downloading parameters {n}/{total}")
        elif total:
            self.show_status(f"Parameters loaded · {total}")

    def _job_status(self, job, msg):
        if job in ("mission", "form", "fence"):
            self.show_status(msg)

    def _apply_glass(self):
        g = self.glass.value()
        self.settings.setValue("glass", g)
        QApplication.instance().setStyleSheet(theme.stylesheet(1 - g / 100))

    def show_status(self, text):
        self.status_lbl.setText(text)

    def _map_key_dialog(self):
        from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
        key, ok = QInputDialog.getText(
            self, "HD satellite (MapTiler)",
            "Esri satellite is blocked on your network. For sharp satellite imagery:\n"
            "1. Sign up free at maptiler.com (no card needed)\n"
            "2. Open Account → API keys and copy your key\n"
            "3. Paste it here:",
            QLineEdit.Normal, self.settings.value("maptiler_key", ""))
        if not ok:
            return
        TILES.set_key("maptiler", key)
        self.settings.setValue("maptiler_key", key.strip())
        if not key.strip():
            return
        good, msg = TILES.test_provider("maptiler")
        (QMessageBox.information if good else QMessageBox.warning)(self, "MapTiler key", msg)

    def _toggle_fence(self):
        from PySide6.QtWidgets import QMessageBox
        if not self.link.state.connected or "FENCE_ENABLE" not in self.link.params:
            self.show_status("Connect and wait for parameters before changing the fence")
            return
        on = self.link.params["FENCE_ENABLE"] >= 1
        P = self.link.params
        if on:
            text = "Turn the geofence OFF?\n\nThe drone will no longer be stopped at the radius/altitude limits."
            if self.link.state.armed:
                text += "\n\nThe drone is ARMED. Only do this if the fence is causing a problem."
        else:
            text = (f"Turn the geofence ON?\n\nRadius {P.get('FENCE_RADIUS', 0):g} m · max altitude "
                    f"{P.get('FENCE_ALT_MAX', 0):g} m · on breach: "
                    f"{ {0: 'report only', 1: 'RTL or Land', 2: 'Land', 3: 'SmartRTL or RTL or Land', 4: 'Brake or Land', 5: 'SmartRTL or Land'}.get(int(P.get('FENCE_ACTION', 1)), 'see FENCE_ACTION') }."
                    "\n\nArming will need a GPS fix while the fence is on.")
            if self.link.state.armed:
                text += ("\n\nThe drone is ARMED. If it is already outside the fence it will "
                         "start the breach action immediately.")
        if QMessageBox.question(self, "Geofence", text) != QMessageBox.Yes:
            return
        self.link.write_params({"FENCE_ENABLE": 0.0 if on else 1.0}, job="fence")

    def _open_3d(self, lat, lon, alt):
        i = self.stack.indexOf(self.view3d)
        self.stack.setCurrentIndex(i)
        self.nav_buttons[i].setChecked(True)
        self.view3d.preview_at(lat, lon, alt)

    # ---------- periodic ----------
    def _tick(self):
        st = self.link.state
        if not self.link.is_open:
            self.p_link.set("OFFLINE", None)
        elif st.connected:
            self.p_link.set("LINK OK", "ok")
        else:
            self.p_link.set("NO LINK", "danger")
        if st.connected:
            self.p_mode.set(st.mode, "accent")
            self.p_arm.set("ARMED" if st.armed else "DISARMED", "danger" if st.armed else "ok")
            fix = "3D" if st.gps_fix >= 3 else "2D" if st.gps_fix == 2 else "NO FIX"
            self.p_gps.set(f"GPS {fix} · {st.sats}", "ok" if st.gps_fix >= 3 and st.sats >= 8 else
                           "warn" if st.gps_fix >= 2 else "danger")
            if st.batt_v > 5:
                cells = round(st.batt_v / 4.2)
                per = st.batt_v / cells
                self.p_batt.set(f"{st.batt_v:.1f} V", "danger" if per < 3.5 else "warn" if per < 3.7 else "ok")
            else:
                self.p_batt.set("NO BATT", None)
            if st.rc_count == 0:
                self.p_rc.set("NO RC", "danger")
            else:
                self.p_rc.set(f"RC {round(st.rc_rssi / 2.54)}%" if st.rc_rssi != 255 else "RC OK", "ok")
            fe = self.link.params.get("FENCE_ENABLE")
            if fe is None:
                self.p_fence.set("FENCE —", None)
            elif fe >= 1:
                gf = mavutil_geofence_bit()
                breached = bool(st.sensors_present & gf) and not (st.sensors_health & gf)
                self.p_fence.set("FENCE BREACH" if breached else "FENCE ON", "danger" if breached else "ok")
            else:
                self.p_fence.set("FENCE OFF", "warn")
            age = time.time() - st.last_heartbeat
            self.hb_lbl.setText(f"heartbeat {age:.1f}s · {len(self.link.params)} params")
        else:
            for p, t in ((self.p_mode, "MODE —"), (self.p_arm, "DISARMED"), (self.p_gps, "GPS —"),
                         (self.p_batt, "BATT —"), (self.p_rc, "RC —"), (self.p_fence, "FENCE —")):
                p.set(t, None)
            self.hb_lbl.setText("")
        best = TILES.best_satellite()
        if best == "osm" and not TILES.reachable("osm"):
            self.p_map.set("MAP OFFLINE · SAVED TILES", "warn")
        else:
            self.p_map.set({"esri": "MAP · ESRI SATELLITE", "maptiler": "MAP · HD SATELLITE",
                            "s2": "MAP · SENTINEL-2 (LOW DETAIL)", "osm": "MAP · STREETS ONLY"}[best],
                           "ok" if best in ("esri", "maptiler") else "warn")
        for mv in (self.fly.map, self.plan.map):
            note = mv.auto_base()
            if note:
                self.show_status(note)
        # keep both 2D maps fed so whichever screen you switch to is already on the drone
        self.fly.tick()
        self.plan.tick()
        self.graphs.sample()   # always record, so history exists when you open Graphs
        cur = self.stack.currentWidget()
        if cur is self.setup:
            self.setup.tick()
        elif cur is self.ports:
            self.ports.tick()
        elif cur is self.view3d:
            self.view3d.tick()
        elif cur is self.graphs:
            self.graphs.tick()

    def closeEvent(self, e):
        self.link.disconnect()
        super().closeEvent(e)
