import threading
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit,
                               QMessageBox, QProgressBar, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)
from pymavlink import DFReader

from .. import plots
from .. import firmware as fwmod
from ..widgets import Card, button, label

LOG_DIR = Path.home() / "flightdeck" / "logs"
MAX_PLOTS = 6

# preset -> list of charts; each chart is a list of (MSG, Field) sharing one unit/axis
PRESETS = {
    "Vibration": [[("VIBE", "VibeX"), ("VIBE", "VibeY"), ("VIBE", "VibeZ")],
                  [("VIBE", "Clip"), ("VIBE", "Clip0"), ("VIBE", "Clip1"), ("VIBE", "Clip2")]],
    "Battery": [[("BAT", "Volt")], [("BAT", "Curr")], [("BAT", "CurrTot")]],
    "Roll: desired vs actual": [[("ATT", "DesRoll"), ("ATT", "Roll")]],
    "Pitch: desired vs actual": [[("ATT", "DesPitch"), ("ATT", "Pitch")]],
    "Yaw: desired vs actual": [[("ATT", "DesYaw"), ("ATT", "Yaw")]],
    "Altitude": [[("CTUN", "DAlt"), ("CTUN", "Alt")], [("CTUN", "ThO")]],
    "RC input": [[("RCIN", "C1"), ("RCIN", "C2"), ("RCIN", "C3"), ("RCIN", "C4")]],
    "Motor outputs": [[("RCOU", "C1"), ("RCOU", "C2"), ("RCOU", "C3"), ("RCOU", "C4")]],
    "GPS": [[("GPS", "NSats")], [("GPS", "HDop")]],
}


class LogData:
    """All numeric fields of a DataFlash .bin, as numpy arrays keyed by message type."""

    def __init__(self):
        self.msgs = {}      # type -> {"t": [], field: []}
        self.modes = []     # (t, name)
        self.texts = []     # (t, text)

    @classmethod
    def load(cls, path, progress=None, default_fw=None):
        """default_fw: firmware to decode mode numbers with if the log doesn't say which vehicle wrote it."""
        d = cls()
        fw = None
        raw_modes = []
        r = DFReader.DFReader_binary(str(path), zero_time_base=True)
        t0 = None
        n = 0
        while True:
            m = r.recv_msg()
            if m is None:
                break
            typ = m.get_type()
            if typ in ("FMT", "FMTU", "UNIT", "MULT", "PARM"):
                continue
            tus = getattr(m, "TimeUS", None)
            if tus is None:
                continue
            if t0 is None:
                t0 = tus
            t = (tus - t0) / 1e6
            if typ == "MODE":
                raw_modes.append((t, getattr(m, "ModeNum", getattr(m, "Mode", -1))))
            elif typ == "MSG" and fw is None:
                # the first messages name the firmware, e.g. "ArduPlane V4.5.7 (…)"
                txt = getattr(m, "Message", "")
                for name, key in (("ArduCopter", "copter"), ("ArduPlane", "plane"), ("ArduRover", "rover"),
                                  ("Rover", "rover"), ("ArduSub", "sub")):
                    if txt.startswith(name):
                        fw = fwmod.ALL[key]
                        break
            elif typ in ("MSG", "ERR", "EV"):
                d.texts.append((t, f"{typ}: " + (getattr(m, "Message", "") if typ == "MSG"
                                                  else ", ".join(f"{k}={getattr(m, k)}" for k in m._fieldnames
                                                                 if k != "TimeUS"))))
            # instance messages (BAT[0], IMU[1]...) are kept separately by their instance
            key = typ
            inst = getattr(m, "fmt", None)
            if inst is not None and getattr(inst, "instance_field", None):
                key = f"{typ}[{getattr(m, inst.instance_field)}]"
            rec = d.msgs.get(key)
            if rec is None:
                rec = d.msgs[key] = {"t": []}
                for f in m._fieldnames:
                    if f != "TimeUS" and isinstance(getattr(m, f), (int, float)):
                        rec[f] = []
            rec["t"].append(t)
            for f in rec:
                if f != "t":
                    rec[f].append(getattr(m, f, np.nan))
            n += 1
            if progress and n % 20000 == 0:
                progress(r.offset / max(r.data_len, 1))
        for key, rec in d.msgs.items():
            for f in rec:
                rec[f] = np.asarray(rec[f], dtype=float)
        d.firmware = fw or default_fw or fwmod.DEFAULT
        d.modes = [(t, d.firmware.log_mode_name(num)) for t, num in raw_modes]
        return d

    def series(self, msg, field):
        rec = self.msgs.get(msg) or self.msgs.get(f"{msg}[0]")
        if rec is None or field not in rec:
            return None
        return rec["t"], rec[field]


class _Loader(QObject):
    progress = Signal(float)
    done = Signal(object, str)


class LogsPage(QWidget):
    def __init__(self, link, status):
        super().__init__()
        self.link = link
        self.status = status
        self.data = None
        self._dl_cancel = None
        self._queue = []
        self._loader = _Loader()
        self._loader.progress.connect(self._load_progress)
        self._loader.done.connect(self._loaded)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label("Logs", "H1"))
        head.addStretch()
        head.addWidget(button("Open log file…", None, self._open_file))
        root.addLayout(head)

        top = QSplitter(Qt.Vertical)
        top.setHandleWidth(10)

        # ---------- on-drone logs ----------
        dc = Card("On the flight controller")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Date (UTC)", "Size", "Saved to"])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setMinimumHeight(110)
        dc.add(self.table, 1)
        self.dl_bar = QProgressBar()
        self.dl_bar.hide()
        dc.add(self.dl_bar)
        r = QHBoxLayout()
        r.addWidget(button("Refresh list", "ghost", self._refresh))
        r.addWidget(button("Download selected", "primary", self._download))
        self.cancel_btn = button("Cancel", "ghost", lambda: self._dl_cancel and self._dl_cancel.set())
        self.cancel_btn.hide()
        r.addWidget(self.cancel_btn)
        r.addStretch()
        r.addWidget(button("Erase all logs on drone", "danger", self._erase))
        dc.add(r)
        self.dc_hint = label("Connect and click Refresh. If the list stays empty, the FC has no log storage — "
                             "insert a microSD card (the earlier \"Logging\" warning).", "Faint", True)
        dc.add(self.dc_hint)
        top.addWidget(dc)

        # ---------- viewer ----------
        viewer = QWidget()
        vl = QHBoxLayout(viewer)
        vl.setContentsMargins(0, 0, 0, 0)
        vs = QSplitter(Qt.Horizontal)
        vs.setHandleWidth(10)
        side = Card("Plot")
        self.file_lbl = label("No log open", "Muted", True)
        side.add(self.file_lbl)
        self.load_bar = QProgressBar()
        self.load_bar.hide()
        side.add(self.load_bar)
        self.preset = QComboBox()
        self.preset.addItem("Choose a preset…", None)
        for k in PRESETS:
            self.preset.addItem(k, k)
        self.preset.currentIndexChanged.connect(self._apply_preset)
        side.add(self.preset)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter fields… e.g. VIBE, BAT, RATE")
        self.search.textChanged.connect(self._filter_tree)
        side.add(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self._tree_changed)
        side.add(self.tree, 1)
        side.add(button("Clear plots", "ghost", self._clear_plots))
        side.setMinimumWidth(260)
        side.setMaximumWidth(340)
        vs.addWidget(side)
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(plots.SURFACE)
        vs.addWidget(self.glw)
        vs.setStretchFactor(1, 1)
        vl.addWidget(vs)
        top.addWidget(viewer)
        top.setSizes([220, 600])
        root.addWidget(top, 1)
        self.events = label("", "Faint", True)
        root.addWidget(self.events)

        self.charts = []   # list of [(msg, field)]
        self._xh = []
        link.log_list.connect(self._got_list)
        link.log_progress.connect(self._dl_progress)
        link.log_saved.connect(self._dl_saved)

    # ---------- on-drone ----------
    def _refresh(self):
        if not self.link.state.connected:
            self.status("Not connected")
            return
        self.status("Requesting log list…")
        self.link.list_logs()

    def _got_list(self, logs):
        self.logs = logs
        self.table.setRowCount(len(logs))
        for i, lg in enumerate(logs):
            ts = time.strftime("%Y-%m-%d %H:%M", time.gmtime(lg["time_utc"])) if lg["time_utc"] else "—"
            path = LOG_DIR / f"log_{lg['id']}.bin"
            for c, txt in enumerate([str(lg["id"]), ts, f"{lg['size'] / 1e6:.2f} MB",
                                     str(path) if path.exists() else ""]):
                self.table.setItem(i, c, QTableWidgetItem(txt))
        self.status(f"{len(logs)} log(s) on the flight controller")
        self.dc_hint.setVisible(not logs)

    def _download(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            self.status("Select one or more logs first")
            return
        self._queue = [self.logs[r] for r in rows]
        self._next_download()

    def _next_download(self):
        if not self._queue:
            self.dl_bar.hide()
            self.cancel_btn.hide()
            return
        lg = self._queue.pop(0)
        self._dl_cancel = threading.Event()
        self.dl_bar.setMaximum(max(lg["size"], 1))
        self.dl_bar.setValue(0)
        self.dl_bar.show()
        self.cancel_btn.show()
        self.link.download_log(lg["id"], lg["size"], str(LOG_DIR / f"log_{lg['id']}.bin"), self._dl_cancel)

    def _dl_progress(self, log_id, got, total):
        self.dl_bar.setMaximum(max(total, 1))
        self.dl_bar.setValue(got)
        self.dl_bar.setFormat(f"Log {log_id}: {got / 1e6:.2f} / {total / 1e6:.2f} MB")

    def _dl_saved(self, log_id, path):
        if path:
            self.status(f"Saved log {log_id} → {path}")
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0) and self.table.item(r, 0).text() == str(log_id):
                    self.table.setItem(r, 3, QTableWidgetItem(path))
            if not self._queue:
                self.open_log(path)
        else:
            self.status(f"Log {log_id} download incomplete or cancelled")
            self._queue = []
        self._next_download()

    def _erase(self):
        if QMessageBox.warning(self, "Erase all logs?", "Permanently delete every log stored on the flight "
                               "controller?", QMessageBox.Yes | QMessageBox.Cancel) == QMessageBox.Yes:
            self.link.erase_logs()
            self.table.setRowCount(0)
            self.status("Erase command sent")

    # ---------- viewer ----------
    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open DataFlash log", str(LOG_DIR), "ArduPilot logs (*.bin *.BIN)")
        if path:
            self.open_log(path)

    def open_log(self, path):
        self.file_lbl.setText(f"Loading {Path(path).name}…")
        self.load_bar.setValue(0)
        self.load_bar.show()

        def work():
            try:
                d = LogData.load(path, lambda f: self._loader.progress.emit(f), self.link.firmware)
                self._loader.done.emit(d, path)
            except Exception as e:
                self._loader.done.emit(None, f"{path}: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _load_progress(self, f):
        self.load_bar.setMaximum(100)
        self.load_bar.setValue(int(f * 100))

    def _loaded(self, data, path):
        self.load_bar.hide()
        if data is None:
            self.file_lbl.setText(f"Could not read log — {path}")
            return
        self.data = data
        dur = max((rec["t"][-1] for rec in data.msgs.values() if len(rec["t"])), default=0)
        self.file_lbl.setText(f"<b>{Path(path).name}</b><br>{dur / 60:.1f} min · {len(data.msgs)} message types")
        self.file_lbl.setTextFormat(Qt.RichText)
        self.tree.blockSignals(True)
        self.tree.clear()
        for key in sorted(data.msgs):
            rec = data.msgs[key]
            top = QTreeWidgetItem([f"{key}  ({len(rec['t'])})"])
            top.setFlags(Qt.ItemIsEnabled)
            for f in rec:
                if f == "t":
                    continue
                it = QTreeWidgetItem([f])
                it.setData(0, Qt.UserRole, (key, f))
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked)
                top.addChild(it)
            self.tree.addTopLevelItem(top)
        self.tree.blockSignals(False)
        modes = ", ".join(f"{m} @{t:.0f}s" for t, m in data.modes[:12])
        errs = [x for _, x in data.texts if x.startswith("ERR")]
        self.events.setText(f"Flight modes: {modes or '—'}" + (f"   ·   {len(errs)} error event(s)" if errs else ""))
        self.charts = []
        self.preset.setCurrentIndex(self.preset.findData("Vibration") if "VIBE" in data.msgs else 0)
        self._render()

    def _filter_tree(self, text):
        t = text.lower().strip()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            show_any = False
            for j in range(top.childCount()):
                ch = top.child(j)
                ok = not t or t in top.text(0).lower() or t in ch.text(0).lower()
                ch.setHidden(not ok)
                show_any |= ok
            top.setHidden(not show_any)
            top.setExpanded(bool(t) and show_any)

    def _tree_changed(self, item, _col):
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        if item.checkState(0) == Qt.Checked:
            if [key] not in self.charts:
                self.charts.append([key])
        else:
            self.charts = [c for c in self.charts if c != [key]]
        self._render()

    def _apply_preset(self, _i):
        name = self.preset.currentData()
        if not name or not self.data:
            return
        self.charts = [c for c in PRESETS[name] if any(self.data.series(*k) is not None for k in c)]
        if not self.charts:
            self.status(f"This log has no data for “{name}”")
        self._render()

    def _clear_plots(self):
        self.charts = []
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, Qt.Unchecked)
        self.tree.blockSignals(False)
        self._render()

    def _render(self):
        self.glw.clear()
        self._xh = []
        if not self.data:
            return
        first = None
        charts = self.charts[:MAX_PLOTS]
        for row, chart in enumerate(charts):
            p = self.glw.addPlot(row=row, col=0)
            names = [f"{m}.{f}" for m, f in chart]
            plots.style_plot(p, names[0] if len(names) == 1 else " vs ".join(f for _, f in chart),
                             chart[0][0])
            plots.legend(p, names)
            curves = []
            for i, (m, f) in enumerate(chart):   # colours in fixed slot order within each chart
                s = self.data.series(m, f)
                if s is None:
                    continue
                t, y = s
                if len(t) > 20000:   # decimate for speed; peaks kept by pyqtgraph's downsampling
                    p.setDownsampling(auto=True, mode="peak")
                    p.setClipToView(True)
                c = p.plot(t, y, pen=plots.pen(i), name=f"{m}.{f}")
                curves.append((f, c))
            for t, mname in self.data.modes:
                ln = pg.InfiniteLine(pos=t, angle=90, pen=pg.mkPen("#4A4A52", width=1, style=Qt.DashLine),
                                     label=mname if row == 0 else None,
                                     labelOpts=dict(position=0.95, color=plots.MUTED, fill=(11, 15, 20, 200)))
                p.addItem(ln, ignoreBounds=True)
            self._xh.append(plots.Crosshair(p, lambda cs=curves: cs, "{:.2f}"))
            if first is None:
                first = p
            else:
                p.setXLink(first)
            if row == len(charts) - 1:
                p.setLabel("bottom", "seconds since log start", color=plots.MUTED)
            else:
                p.getAxis("bottom").setStyle(showValues=False)
        if len(self.charts) > MAX_PLOTS:
            self.status(f"Showing the first {MAX_PLOTS} charts — untick fields to see others")
