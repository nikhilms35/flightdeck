import json
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QMessageBox, QProgressBar, QScrollArea, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..mapview import MapView
from ..tileserver import TILES, count_tiles
from ..widgets import Card, button, label

MAX_DOWNLOAD_TILES = 20000   # keep bulk downloads to a flying field, not a whole region

CMDS = {16: "Waypoint", 22: "Takeoff", 19: "Loiter (time)", 21: "Land", 20: "Return home"}
CMD_IDS = {v: k for k, v in CMDS.items()}
KIND = {22: "takeoff", 21: "land", 19: "loiter"}


class PlanPage(QWidget):
    preview3d = Signal(float, float, float)      # lat, lon, alt
    _dl_progress = Signal(int, int, int, str)    # done, total, failed, phase
    _dl_done = Signal(str)

    def __init__(self, link, status):
        super().__init__()
        self.link = link
        self.status = status
        self.wps = []  # dicts: cmd, lat, lon, alt, p1
        self.rev = 0   # bumped on every change so the 3D view can follow
        self._building = False
        self._dl_cancel = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        root.addWidget(split)

        self.map = MapView(plan=True)
        self.map.bridge.clicked.connect(self._add_at)
        self.map.bridge.moved.connect(self._moved)
        split.addWidget(self.map)

        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setMinimumWidth(440)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 16, 16, 16)
        sv.setSpacing(12)
        sv.addWidget(label("Mission", "H1"))
        sv.addWidget(label("Click the map to add waypoints. Altitudes are relative to the take-off point.", "Muted", True))

        opts = Card("Defaults")
        r = QHBoxLayout()
        r.addWidget(label("New waypoint altitude"))
        self.def_alt = QDoubleSpinBox()
        self.def_alt.setRange(1, 500)
        self.def_alt.setValue(20)
        self.def_alt.setSuffix(" m")
        r.addStretch()
        r.addWidget(self.def_alt)
        opts.add(r)
        self.auto_takeoff = QCheckBox("Start with take-off (if first item isn't one)")
        self.auto_takeoff.setChecked(True)
        self.auto_rtl = QCheckBox("Finish with Return home")
        self.auto_rtl.setChecked(True)
        opts.add(self.auto_takeoff)
        opts.add(self.auto_rtl)
        sv.addWidget(opts)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Command", "Alt (m)", "Lat", "Lon"])
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._edited)
        self.table.setMinimumHeight(220)
        sv.addWidget(self.table, 1)

        r1 = QHBoxLayout()
        r1.addWidget(button("Preview in 3D", "ghost", self._preview_selected))
        r1.addWidget(button("Delete selected", "ghost", self._delete))
        r1.addWidget(button("Clear all", "ghost", self._clear))
        r1.addStretch()
        sv.addLayout(r1)
        r1b = QHBoxLayout()
        r1b.addWidget(button("Center on drone", "ghost", self._center))
        r1b.addWidget(button("Fit mission", "ghost", self.map.fit))
        r1b.addStretch()
        sv.addLayout(r1b)

        r2 = QHBoxLayout()
        r2.addWidget(button("Open file…", None, self._load_file))
        r2.addWidget(button("Save file…", None, self._save_file))
        sv.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(button("Read from drone", None, self.link.download_mission))
        r3.addWidget(button("Write to drone", "primary", self._upload))
        sv.addLayout(r3)

        oc = Card("Offline maps")
        oc.add(label("Every map tile you look at is saved automatically. To prepare a flying field with no "
                     "internet, zoom the map to it and download the area (satellite + terrain).", "Muted", True))
        self.dl_bar = QProgressBar()
        self.dl_bar.hide()
        oc.add(self.dl_bar)
        self.cache_lbl = label("", "Faint")
        oc.add(self.cache_lbl)
        orow = QHBoxLayout()
        self.dl_btn = button("Download visible area", "primary", self._download_area)
        self.dl_cancel_btn = button("Cancel", "ghost", self._cancel_download)
        self.dl_cancel_btn.hide()
        orow.addWidget(self.dl_btn)
        orow.addWidget(self.dl_cancel_btn)
        orow.addStretch()
        orow.addWidget(button("Clear saved maps", "ghost", self._clear_cache))
        oc.add(orow)
        sv.addWidget(oc)

        side_scroll.setWidget(side)
        split.addWidget(side_scroll)
        split.setSizes([1000, 470])
        split.setStretchFactor(0, 1)

        link.mission_downloaded.connect(self._downloaded)
        self._dl_progress.connect(self._on_dl_progress)
        self._dl_done.connect(self._on_dl_done)
        self._update_cache_lbl()

    # ---------- offline maps ----------
    def _update_cache_lbl(self):
        size, files = TILES.cache_size()
        self.cache_lbl.setText(f"Saved on this computer: {files:,} tiles · {size / 1e6:.1f} MB")

    def _download_area(self):
        self.map.eval("JSON.stringify(getBounds())", self._got_bounds)

    def _got_bounds(self, result):
        try:
            s, w, n, e, zoom = json.loads(result)
        except (TypeError, ValueError):
            self.status("Map not ready yet")
            return
        zmin, zmax = max(10, int(zoom) - 3), 19
        count = count_tiles((s, w, n, e), zmin, zmax)
        while count > MAX_DOWNLOAD_TILES and zmax > zmin + 1:
            zmax -= 1
            count = count_tiles((s, w, n, e), zmin, zmax)
        if count > MAX_DOWNLOAD_TILES:
            QMessageBox.information(self, "Area too large",
                                    "That area is too big to download. Zoom in to your flying field and try again.")
            return
        tcount = count_tiles((s, w, n, e), 8, 14)
        if QMessageBox.question(
                self, "Download for offline use?",
                f"Satellite zoom {zmin}–{zmax}: {count:,} tiles\nTerrain: {tcount:,} tiles\n"
                f"Estimated size: ~{(count * 18 + tcount * 60) / 1000:.0f} MB\n\n"
                "Please keep downloads to the area you actually fly.") != QMessageBox.Yes:
            return
        self._dl_cancel = threading.Event()
        self.dl_bar.setValue(0)
        self.dl_bar.show()
        self.dl_btn.setEnabled(False)
        self.dl_cancel_btn.show()
        bounds = (s, w, n, e)

        def work():
            res = []
            # bulk-download the best satellite source that allows it (Esri, else Sentinel-2)
            sat = "esri" if TILES.reachable("esri") else "s2"
            from ..tileserver import PROVIDERS
            smax = min(zmax, PROVIDERS[sat][2])
            for prov, z0, z1, phase in ((sat, min(zmin, smax), smax, "Satellite"), ("terrain", 8, 14, "Terrain")):
                if self._dl_cancel.is_set():
                    break
                done, total, failed = TILES.prefetch(
                    prov, bounds, z0, z1,
                    lambda d, t, f, ph=phase: self._dl_progress.emit(d, t, f, ph), self._dl_cancel)
                res.append(f"{phase}: {done - failed:,}/{total:,}")
                if not TILES.reachable(prov):
                    res.append(f"{phase} server unreachable")
            self._dl_done.emit(("Cancelled · " if self._dl_cancel.is_set() else "Offline maps saved · ")
                               + " · ".join(res))
        threading.Thread(target=work, daemon=True).start()

    def _on_dl_progress(self, done, total, failed, phase):
        self.dl_bar.setMaximum(max(total, 1))
        self.dl_bar.setValue(done)
        self.dl_bar.setFormat(f"{phase}  {done:,}/{total:,}" + (f"  ({failed} unavailable)" if failed else ""))

    def _on_dl_done(self, msg):
        self.dl_bar.hide()
        self.dl_btn.setEnabled(True)
        self.dl_cancel_btn.hide()
        self.status(msg)
        self._update_cache_lbl()

    def _cancel_download(self):
        if self._dl_cancel:
            self._dl_cancel.set()

    def _clear_cache(self):
        if QMessageBox.question(self, "Clear saved maps?", "Delete all map tiles saved on this computer?") \
                == QMessageBox.Yes:
            TILES.clear()
            self._update_cache_lbl()

    def _preview_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            self.status("Select a waypoint in the table first")
            return
        w = self.wps[rows[0]]
        if not (w["lat"] or w["lon"]):
            self.status("That item has no position")
            return
        self.preview3d.emit(w["lat"], w["lon"], w["alt"])

    def tick(self):
        st = self.link.state
        if not st.connected:
            return
        if st.lat is not None:
            self.map.set_vehicle(st.lat, st.lon, st.heading)
        if st.home_lat is not None:
            self.map.set_home(st.home_lat, st.home_lon)

    def _center(self):
        st = self.link.state
        if st.lat is None:
            self.status("No GPS position from the drone yet")
            return
        self.map.js(f"centerOn({st.lat:.7f},{st.lon:.7f},18)")

    # ---------- model ----------
    def _add_at(self, lat, lon):
        self.wps.append(dict(cmd=16, lat=lat, lon=lon, alt=self.def_alt.value(), p1=0))
        self._refresh()

    def _moved(self, i, lat, lon):
        if 0 <= i < len(self.wps):
            self.wps[i]["lat"], self.wps[i]["lon"] = lat, lon
            self._refresh(redraw_map=False)

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            del self.wps[r]
        self._refresh()

    def _clear(self):
        self.wps = []
        self._refresh()

    def _refresh(self, redraw_map=True):
        self.rev += 1
        self._building = True
        self.table.setRowCount(len(self.wps))
        for i, w in enumerate(self.wps):
            it = QTableWidgetItem(str(i + 1))
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(i, 0, it)
            cb = QComboBox()
            cb.addItems(list(CMDS.values()))
            cb.setCurrentText(CMDS.get(w["cmd"], f"CMD {w['cmd']}"))
            cb.currentTextChanged.connect(lambda txt, i=i: self._cmd_changed(i, txt))
            self.table.setCellWidget(i, 1, cb)
            self.table.setItem(i, 2, QTableWidgetItem(f"{w['alt']:.1f}"))
            for c, k in ((3, "lat"), (4, "lon")):
                it = QTableWidgetItem(f"{w[k]:.7f}")
                self.table.setItem(i, c, it)
        self._building = False
        if redraw_map:
            self.map.set_waypoints([dict(lat=w["lat"], lon=w["lon"], label=str(i + 1),
                                         kind=KIND.get(w["cmd"], "")) for i, w in enumerate(self.wps)])

    def _cmd_changed(self, i, txt):
        self.wps[i]["cmd"] = CMD_IDS[txt]
        self._refresh()

    def _edited(self, item):
        if self._building:
            return
        i, c = item.row(), item.column()
        key = {2: "alt", 3: "lat", 4: "lon"}.get(c)
        if not key:
            return
        try:
            self.wps[i][key] = float(item.text())
        except ValueError:
            pass
        self._refresh()

    # ---------- vehicle ----------
    def _mission_items(self):
        st = self.link.state
        hl = st.home_lat if st.home_lat is not None else (st.lat or 0)
        hn = st.home_lon if st.home_lon is not None else (st.lon or 0)
        items = [dict(cmd=16, lat=hl, lon=hn, alt=0)]
        body = [dict(w) for w in self.wps]
        if self.auto_takeoff.isChecked() and (not body or body[0]["cmd"] != 22):
            body.insert(0, dict(cmd=22, lat=0, lon=0, alt=body[0]["alt"] if body else self.def_alt.value(), p1=0))
        if self.auto_rtl.isChecked() and (not body or body[-1]["cmd"] not in (20, 21)):
            body.append(dict(cmd=20, lat=0, lon=0, alt=0, p1=0))
        return items + body

    def _upload(self):
        if not self.link.state.connected:
            self.status("Not connected")
            return
        if not self.wps:
            self.status("Mission is empty — click the map to add waypoints")
            return
        self.link.upload_mission(self._mission_items())

    def _downloaded(self, items):
        self.wps = [dict(cmd=i["cmd"], lat=i["lat"], lon=i["lon"], alt=i["alt"], p1=i.get("p1", 0))
                    for i in items[1:]]
        self._refresh()
        self.map.fit()

    # ---------- files (QGC WPL 110, Mission Planner compatible) ----------
    def _save_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save mission", "mission.waypoints", "Waypoints (*.waypoints *.txt)")
        if not path:
            return
        items = self._mission_items()
        with open(path, "w") as f:
            f.write("QGC WPL 110\n")
            for seq, it in enumerate(items):
                frame = 0 if seq == 0 else 3
                f.write(f"{seq}\t{1 if seq == 0 else 0}\t{frame}\t{it['cmd']}\t{it.get('p1', 0)}\t0\t0\t0\t"
                        f"{it['lat']:.8f}\t{it['lon']:.8f}\t{it['alt']:.6f}\t1\n")
        self.status(f"Saved {path}")

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open mission", "", "Waypoints (*.waypoints *.txt *.mission)")
        if not path:
            return
        wps = []
        try:
            with open(path) as f:
                lines = f.read().splitlines()
            if not lines or not lines[0].startswith("QGC WPL"):
                raise ValueError("not a QGC WPL file")
            for ln in lines[1:]:
                p = ln.split("\t")
                if len(p) < 12 or int(p[0]) == 0:
                    continue
                wps.append(dict(cmd=int(p[3]), lat=float(p[8]), lon=float(p[9]), alt=float(p[10]), p1=float(p[4])))
        except Exception as e:
            self.status(f"Could not open mission: {e}")
            return
        self.wps = wps
        self._refresh()
        self.map.fit()
        self.status(f"Loaded {len(wps)} items from {path}")
