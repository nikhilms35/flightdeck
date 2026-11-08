import math
import time
from collections import deque

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                               QSplitter, QVBoxLayout, QWidget)

from .. import plots, theme
from ..theme import T
from ..widgets import Card, button, label

HZ = 10
MAX_PLOTS = 6

# (group, name, unit, getter)
CHANNELS = [
    ("Attitude", "Roll", "°", lambda s: math.degrees(s.roll)),
    ("Attitude", "Pitch", "°", lambda s: math.degrees(s.pitch)),
    ("Attitude", "Heading", "°", lambda s: s.heading),
    ("Flight", "Altitude", "m", lambda s: s.alt_rel),
    ("Flight", "Climb rate", "m/s", lambda s: s.climb),
    ("Flight", "Ground speed", "m/s", lambda s: s.groundspeed),
    ("Flight", "Throttle", "%", lambda s: s.throttle),
    ("Battery", "Voltage", "V", lambda s: s.batt_v),
    ("Battery", "Current", "A", lambda s: max(s.batt_a, 0)),
    ("Battery", "Used", "mAh", lambda s: s.batt_mah),
    ("Vibration", "Vibe X", "m/s²", lambda s: s.vibe[0]),
    ("Vibration", "Vibe Y", "m/s²", lambda s: s.vibe[1]),
    ("Vibration", "Vibe Z", "m/s²", lambda s: s.vibe[2]),
    ("GPS", "Satellites", "", lambda s: s.sats),
    ("GPS", "HDOP", "", lambda s: s.hdop if s.hdop < 50 else float("nan")),
    ("Radio", "RC link", "%", lambda s: s.rc_rssi / 2.54 if s.rc_count and s.rc_rssi != 255 else float("nan")),
] + [("Radio", f"RC {i + 1}", "µs", (lambda i: lambda s: s.rc[i] or float("nan"))(i)) for i in range(8)] \
  + [("Motors", f"Motor {i + 1}", "µs", (lambda i: lambda s: s.servo[i] or float("nan"))(i)) for i in range(4)]

VIBE_LEVELS = [(30, "ok", "✓ Good"), (60, "warn", "! High"), (1e9, "danger", "✕ Too high")]


class VibeMeter(QFrame):
    def __init__(self, axis):
        super().__init__()
        self.setObjectName("Tile")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.addWidget(label(f"VIBRATION {axis}", "TileLabel"))
        self.val = label("—")
        self.val.setFont(theme.mono(18, True))
        v.addWidget(self.val)
        self.state = label("", "Faint")
        v.addWidget(self.state)

    def set(self, x, clip):
        if x is None:
            self.val.setText("—")
            self.state.setText("")
            return
        lim, kind, text = next(lv for lv in VIBE_LEVELS if x < lv[0])
        self.val.setText(f"{x:.1f}")
        self.state.setText(f"<span style='color:{T[kind]}'>{text}</span> · {clip} clips")
        self.state.setTextFormat(Qt.RichText)


class GraphsPage(QWidget):
    def __init__(self, link):
        super().__init__()
        self.link = link
        self.buf_t = deque(maxlen=HZ * 600)
        self.bufs = [deque(maxlen=HZ * 600) for _ in CHANNELS]
        self.t0 = time.time()
        self._last_sample = 0.0
        self.curves = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label("Live graphs", "H1"))
        head.addStretch()
        head.addWidget(label("Window"))
        self.window = QComboBox()
        for s in (30, 60, 120, 300, 600):
            self.window.addItem(f"{s // 60} min" if s >= 60 else f"{s} s", s)
        self.window.setCurrentIndex(1)
        head.addWidget(self.window)
        head.addWidget(button("Clear", "ghost", self._clear))
        root.addLayout(head)

        vg = QGridLayout()
        vg.setSpacing(8)
        self.vibes = [VibeMeter(a) for a in "XYZ"]
        for i, m in enumerate(self.vibes):
            vg.addWidget(m, 0, i)
        hint = label("Vibration below 30 m/s² is good. Above 30, check prop balance, motor bearings and "
                     "FC soft-mounting. Any clipping means the accelerometer is saturating.", "Faint", True)
        vg.addWidget(hint, 0, 3)
        vg.setColumnStretch(3, 2)
        root.addLayout(vg)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(10)
        left = Card("Show")
        self.list = QListWidget()
        self.list.setObjectName("SubNav")
        group = None
        for i, (g, name, unit, _) in enumerate(CHANNELS):
            if g != group:
                hdr = QListWidgetItem(g.upper())
                hdr.setFlags(Qt.NoItemFlags)
                hdr.setForeground(pg.mkColor(plots.MUTED))
                f = hdr.font()
                f.setPointSizeF(8)
                f.setBold(True)
                hdr.setFont(f)
                self.list.addItem(hdr)
                group = g
            it = QListWidgetItem(f"{name}" + (f"  ({unit})" if unit else ""))
            it.setData(Qt.UserRole, i)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if name in ("Altitude", "Voltage", "Roll") else Qt.Unchecked)
            self.list.addItem(it)
        self.list.itemChanged.connect(self._rebuild)
        left.add(self.list, 1)
        left.setMinimumWidth(220)
        left.setMaximumWidth(280)
        split.addWidget(left)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(plots.SURFACE)
        split.addWidget(self.glw)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        self.note = label("", "Faint")
        root.addWidget(self.note)
        self._rebuild()

    def _selected(self):
        out = []
        for r in range(self.list.count()):
            it = self.list.item(r)
            if it.data(Qt.UserRole) is not None and it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _rebuild(self, *_):
        sel = self._selected()
        self.note.setText(f"Showing the first {MAX_PLOTS} of {len(sel)} selected — untick some to see others."
                          if len(sel) > MAX_PLOTS else "Hover a graph to read exact values.")
        sel = sel[:MAX_PLOTS]
        self.glw.clear()
        self.curves = []
        self._xh = []   # keep crosshairs alive (they hold the mouse signal proxy)
        first = None
        for row, idx in enumerate(sel):
            g, name, unit, _ = CHANNELS[idx]
            p = self.glw.addPlot(row=row, col=0)
            plots.style_plot(p, name, unit)
            c = p.plot(pen=plots.pen(0))  # one series per chart: no legend, title names it
            self._xh.append(plots.Crosshair(p, lambda c=c, n=name: [(n, c)], "{:.2f}"))
            if first is None:
                first = p
            else:
                p.setXLink(first)
            if row < len(sel) - 1:
                p.getAxis("bottom").setStyle(showValues=False)
            else:
                p.setLabel("bottom", "seconds", color=plots.MUTED)
            self.curves.append((idx, c))
        self.redraw()

    def _clear(self):
        self.buf_t.clear()
        for b in self.bufs:
            b.clear()
        self.redraw()

    def sample(self):
        """Called by the main window at 10 Hz whatever screen is showing, so history is kept."""
        st = self.link.state
        if not st.connected:
            return
        now = time.time()
        if now - self._last_sample < 1.0 / HZ - 0.01:
            return
        self._last_sample = now
        self.buf_t.append(now - self.t0)
        for b, (_, _, _, get) in zip(self.bufs, CHANNELS):
            try:
                b.append(float(get(st)))
            except Exception:
                b.append(float("nan"))

    def redraw(self):
        if not self.buf_t:
            for _, c in self.curves:
                c.setData([], [])
            return
        t = np.fromiter(self.buf_t, float)
        now = t[-1]
        win = self.window.currentData()
        m = t >= now - win
        x = t[m] - now
        for idx, c in self.curves:
            y = np.fromiter(self.bufs[idx], float)[m]
            c.setData(x, y, connect="finite")
        for p in self.glw.ci.items:
            if isinstance(p, pg.PlotItem):
                p.setXRange(-win, 0, padding=0)

    def tick(self):
        st = self.link.state
        for i, m in enumerate(self.vibes):
            m.set(st.vibe[i] if st.connected else None, st.clipping[i])
        self.redraw()
