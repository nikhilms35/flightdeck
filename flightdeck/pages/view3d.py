import json
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSlider, QSplitter, QVBoxLayout, QWidget)

from ..mapview import WebView
from ..theme import T
from ..widgets import Card, button, label

MODES = [("preview", "Preview"), ("fpv", "FPV"), ("chase", "Chase"), ("flythrough", "Fly-through"), ("free", "Free look")]


class View3D(WebView):
    def __init__(self):
        super().__init__("view3d.html")


def slider(lo, hi, val, suffix, fmt="{:.0f}"):
    row = QHBoxLayout()
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    lab = QLabel(fmt.format(val) + suffix)
    lab.setMinimumWidth(58)
    lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    s.valueChanged.connect(lambda v: lab.setText(fmt.format(v) + suffix))
    row.addWidget(s, 1)
    row.addWidget(lab)
    return row, s


class View3DPage(QWidget):
    def __init__(self, link, plan, status):
        super().__init__()
        self.link = link
        self.plan = plan
        self.status = status
        self.mode = "preview"
        self._plan_rev = -1
        self._tick_n = 0
        self._pending_preview = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        root.addWidget(split)
        # The 3D engine (Cesium/WebGL) is only started the first time this screen is shown.
        self.view = None
        self.holder = QWidget()
        self.holder_lay = QVBoxLayout(self.holder)
        self.holder_lay.setContentsMargins(0, 0, 0, 0)
        self.holder_lay.addWidget(label("Starting 3D view…", "Muted"), 0, Qt.AlignCenter)
        split.addWidget(self.holder)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        side = QWidget()
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 16, 16, 16)
        v.setSpacing(12)
        v.addWidget(label("3D view", "H1"))
        v.addWidget(label("See what the camera sees from any altitude, follow the drone live, or fly your mission "
                          "before you fly it for real.", "Muted", True))

        mc = Card("Mode")
        grid = QHBoxLayout()
        grid.setSpacing(6)
        self.mode_group = QButtonGroup(self)
        self.mode_btns = {}
        for key, name in MODES:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("kind", "ghost")
            self.mode_group.addButton(b)
            self.mode_btns[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            grid.addWidget(b)
        mc.add(grid)
        r = QHBoxLayout()
        self.imagery = QComboBox()
        self.imagery.addItem("Satellite (auto best)", "auto")
        self.imagery.addItem("Satellite (Esri)", "esri")
        self.imagery.addItem("Satellite HD (MapTiler)", "maptiler")
        self.imagery.addItem("Satellite (Sentinel-2)", "s2")
        self.imagery.addItem("Streets", "osm")
        self._img_auto = None
        self.imagery.currentIndexChanged.connect(lambda _: self._apply_imagery(force=True))
        self.terrain = QCheckBox("3D terrain (hills)")
        self.terrain.setChecked(True)
        self.terrain.toggled.connect(lambda on: self._js(f"setTerrain({'true' if on else 'false'})"))
        r.addWidget(self.imagery)
        r.addWidget(self.terrain)
        r.addStretch()
        mc.add(r)
        v.addWidget(mc)

        pc = Card("Camera")
        lr = QHBoxLayout()
        lr.addWidget(label("Location"))
        self.where = QComboBox()
        self.where.setMinimumWidth(180)
        self.where.activated.connect(self._where_picked)
        lr.addWidget(self.where, 1)
        pc.add(lr)
        pc.add(label("Altitude above take-off point", "Faint"))
        row, self.s_alt = slider(0, 150, 30, " m")
        pc.add(row)
        pc.add(label("Camera tilt  (0 = horizon, −90 = straight down)", "Faint"))
        row, self.s_tilt = slider(-90, 30, -20, "°")
        pc.add(row)
        pc.add(label("Heading", "Faint"))
        row, self.s_hdg = slider(0, 359, 0, "°")
        pc.add(row)
        pc.add(label("Field of view  (analog FPV lens ≈ 110–130°)", "Faint"))
        row, self.s_fov = slider(50, 150, 110, "°")
        pc.add(row)
        pc.add(label("FPV camera uptilt  (used in FPV mode)", "Faint"))
        row, self.s_up = slider(0, 50, 25, "°")
        pc.add(row)
        for s in (self.s_alt, self.s_tilt, self.s_hdg):
            s.valueChanged.connect(self._apply_preview)
        self.s_fov.valueChanged.connect(lambda val: self._js(f"setFov({val})"))
        self.s_up.valueChanged.connect(lambda val: self._js(f"setUptilt({val})"))
        self.agl_lbl = label("", "Muted", True)
        self.agl_lbl.setTextFormat(Qt.RichText)
        pc.add(self.agl_lbl)
        v.addWidget(pc)

        fc = Card("Mission fly-through")
        fr = QHBoxLayout()
        fr.addWidget(label("Speed"))
        self.fly_speed = QDoubleSpinBox()
        self.fly_speed.setRange(1, 30)
        self.fly_speed.setValue(8)
        self.fly_speed.setSuffix(" m/s")
        fr.addWidget(self.fly_speed)
        fr.addStretch()
        fr.addWidget(button("▶ Fly", "primary", self._fly))
        fr.addWidget(button("■ Stop", "ghost", lambda: self.set_mode("preview")))
        fc.add(fr)
        v.addWidget(fc)

        cc = Card("Ground clearance")
        self.clr_lbl = label("Add waypoints on the Plan screen to check how high above the ground each one is.",
                             "Muted", True)
        self.clr_lbl.setTextFormat(Qt.RichText)
        cc.add(self.clr_lbl)
        v.addWidget(cc)
        v.addStretch()
        sc.setWidget(side)
        sc.setMinimumWidth(380)
        split.addWidget(sc)
        split.setSizes([1100, 400])
        split.setStretchFactor(0, 1)
        self.mode_btns["preview"].setChecked(True)
        self._rebuild_where()

    def _apply_imagery(self, force=False):
        from ..tileserver import TILES
        want = self.imagery.currentData()
        if want == "auto":
            want = TILES.best_satellite()
        if force or want != self._img_auto:
            self._img_auto = want
            self._js(f"setImagery('{want}')")

    # ---------- lazy 3D engine ----------
    def _js(self, code):
        if self.view is not None:
            self.view.js(code)

    def _ensure_view(self):
        if self.view is not None:
            return
        while self.holder_lay.count():
            w = self.holder_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.view = View3D()
        self.view.bridge.message.connect(self._on_msg)
        self.holder_lay.addWidget(self.view)
        # bring the new page up to date with the controls (queued until the page is ready)
        self._apply_imagery(force=True)
        if not self.terrain.isChecked():
            self._js("setTerrain(false)")
        self._js(f"setFov({self.s_fov.value()})")
        self._js(f"setUptilt({self.s_up.value()})")
        self._push_mission(force=True)
        self.set_mode(self.mode if self.mode != "flythrough" else "preview")

    def showEvent(self, e):
        super().showEvent(e)
        self._ensure_view()

    # ---------- locations ----------
    def _rebuild_where(self):
        st = self.link.state
        cur = self.where.currentData()
        self.where.blockSignals(True)
        self.where.clear()
        if st.lat is not None:
            self.where.addItem("Drone (live position)", ("drone",))
        if st.home_lat is not None:
            self.where.addItem("Home", ("home",))
        for i, w in enumerate(self.plan.wps):
            if w["lat"] or w["lon"]:
                self.where.addItem(f"Waypoint {i + 1}  ·  {w['alt']:.0f} m", ("wp", i))
        if self.where.count() == 0:
            self.where.addItem("No location yet — connect or add waypoints", None)
        if cur is not None:
            j = next((k for k in range(self.where.count()) if self.where.itemData(k) == cur), -1)
            if j >= 0:
                self.where.setCurrentIndex(j)
        self.where.blockSignals(False)

    def _where_latlon(self):
        st = self.link.state
        d = self.where.currentData()
        if not d:
            return None
        if d[0] == "drone" and st.lat is not None:
            return st.lat, st.lon
        if d[0] == "home" and st.home_lat is not None:
            return st.home_lat, st.home_lon
        if d[0] == "wp" and d[1] < len(self.plan.wps):
            w = self.plan.wps[d[1]]
            return w["lat"], w["lon"]
        return None

    def _where_picked(self, _i):
        self._pending_preview = None
        self._apply_preview()

    def preview_at(self, lat, lon, alt=None):
        """Called from other screens (Plan, Fly map right-click)."""
        if alt is not None:
            self.s_alt.blockSignals(True)
            self.s_alt.setValue(int(alt))
            self.s_alt.blockSignals(False)
        self._pending_preview = (lat, lon)
        self.set_mode("preview")
        self._apply_preview()

    def _apply_preview(self, *_):
        if self.mode != "preview":
            return
        # a spot picked on another screen stays in use until a location is chosen from the list
        ll = self._pending_preview or self._where_latlon()
        if not ll:
            self.agl_lbl.setText("Pick a location: connect the drone (GPS) or add waypoints on the Plan screen.")
            return
        self._js(f"setPreview({ll[0]:.7f},{ll[1]:.7f},{self.s_alt.value()},{self.s_hdg.value()},"
                     f"{self.s_tilt.value()})")

    # ---------- modes ----------
    def set_mode(self, m):
        self.mode = m
        self.mode_btns[m].setChecked(True)
        if m == "flythrough":
            self._fly()
            return
        self._js(f"setMode('{m}')")
        if m == "preview":
            self._apply_preview()
        elif m in ("fpv", "chase") and self.link.state.lat is None:
            self.status("No live GPS position from the drone — FPV/Chase need a connected drone with GPS")

    def _fly(self):
        self.mode = "flythrough"
        self.mode_btns["flythrough"].setChecked(True)
        self._push_mission(force=True)
        self._js(f"flyThrough({self.fly_speed.value()},{self.s_tilt.value()})")

    def _push_mission(self, force=False):
        rev = getattr(self.plan, "rev", 0)
        if not force and rev == self._plan_rev:
            return
        self._plan_rev = rev
        pts = [dict(n=i + 1, lat=w["lat"], lon=w["lon"], alt=w["alt"]) for i, w in enumerate(self.plan.wps)
               if (w["lat"] or w["lon"]) and w["cmd"] in (16, 19, 22)]
        self._js(f"setMission({json.dumps(pts)})")
        self._rebuild_where()

    # ---------- messages from the page ----------
    def _on_msg(self, text):
        try:
            m = json.loads(text)
        except ValueError:
            return
        t = m.get("type")
        if t == "preview":
            agl = m["agl"]
            col = T["danger"] if agl < 10 else T["warn"] if agl < 20 else T["ok"]
            self.agl_lbl.setText(f"<span style='color:{col}'>●</span> {agl:.0f} m above the ground at this spot "
                                 f"(ground {m['ground']:.0f} m above sea level)")
        elif t == "clearance":
            rows = m["rows"]
            if not rows:
                self.clr_lbl.setText("Add waypoints on the Plan screen to check how high above the ground each one is.")
                return
            out = []
            worst = min(r["clearance"] for r in rows)
            for r in rows:
                c = r["clearance"]
                col = T["danger"] if c < 10 else T["warn"] if c < 20 else T["ok"]
                out.append(f"<span style='color:{col}'>●</span> WP {r['n']}: set {r['alt']:.0f} m → "
                           f"<b>{c:.0f} m</b> above ground")
            if worst < 10:
                out.insert(0, f"<b style='color:{T['danger']}'>Warning: terrain is close to the flight path. "
                              f"Raise those waypoints.</b>")
            self.clr_lbl.setText("<br>".join(out))
        elif t == "flydone":
            self.set_mode("preview")
        elif t == "info":
            self.status(m.get("text", ""))

    # ---------- periodic ----------
    def tick(self):
        self._tick_n += 1
        if self._tick_n % 2:
            return  # 5 Hz is plenty for the 3D view
        from ..tileserver import TILES
        self._apply_imagery()
        st = self.link.state
        if st.home_lat is not None:
            self._js(f"setHome({st.home_lat:.7f},{st.home_lon:.7f})")
        if st.lat is not None and st.connected:
            self._js(f"setVehicle({st.lat:.7f},{st.lon:.7f},{st.alt_rel:.2f},{st.heading},"
                         f"{math.degrees(st.pitch):.1f},{math.degrees(st.roll):.1f})")
        self._push_mission()
        if self._tick_n % 50 == 0:
            self._rebuild_where()
