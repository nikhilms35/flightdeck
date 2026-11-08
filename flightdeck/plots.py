"""pyqtgraph styling shared by live graphs and log plots.
Colours: dataviz reference palette, dark steps, validated against our chart surface #11161D
(all checks pass: lightness band, chroma, adjacent CVD dE >= 8.4, normal-vision >= 19.3, contrast >= 3:1)."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from . import theme
from .theme import T

SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
SURFACE = "#11161D"
GRID = "#2c2c2a"
AXIS = "#383835"
MUTED = "#898781"

pg.setConfigOptions(antialias=True, background=SURFACE, foreground=MUTED)


def style_plot(p: pg.PlotItem, title=None, unit=""):
    for side in ("left", "bottom"):
        ax = p.getAxis(side)
        ax.setPen(pg.mkPen(AXIS))
        ax.setTextPen(pg.mkPen(MUTED))
        ax.setStyle(tickFont=theme.mono(8), tickLength=-4)
    p.showGrid(x=True, y=True, alpha=0.12)
    p.getAxis("left").setWidth(52)
    if title:
        p.setTitle(f"<span style='color:{T['text']};font-family:{theme.UI_FONT};font-size:9pt;font-weight:600'>"
                   f"{title}</span> <span style='color:{MUTED};font-size:8pt'>{unit}</span>", justify="left")
    p.setMenuEnabled(False)
    p.hideButtons()
    return p


def pen(i):
    return pg.mkPen(SERIES[i % len(SERIES)], width=2)


class Crosshair:
    """Vertical hover line + readout of every curve's value at the cursor."""

    def __init__(self, plot: pg.PlotItem, curves_fn, fmt="{:.2f}"):
        self.plot = plot
        self.curves_fn = curves_fn
        self.fmt = fmt
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#5C6876", width=1))
        self.label = pg.TextItem(anchor=(0, 1), color=T["text"], fill=pg.mkBrush(11, 15, 20, 220),
                                 border=pg.mkPen("#32404F"))
        self.label.setFont(theme.mono(8))
        for it in (self.vline, self.label):
            it.setZValue(100)
            it.hide()
            plot.addItem(it, ignoreBounds=True)
        self.proxy = pg.SignalProxy(plot.scene().sigMouseMoved, rateLimit=30, slot=self._moved)

    def _moved(self, evt):
        pos = evt[0]
        vb = self.plot.vb
        if not self.plot.sceneBoundingRect().contains(pos):
            self.vline.hide()
            self.label.hide()
            return
        x = vb.mapSceneToView(pos).x()
        parts = []
        for name, curve in self.curves_fn():
            xs, ys = curve.getData()
            if xs is None or len(xs) == 0:
                continue
            i = int(np.clip(np.searchsorted(xs, x), 0, len(xs) - 1))
            parts.append(f"{name}: {self.fmt.format(ys[i])}")
        if not parts:
            return
        self.vline.setPos(x)
        (x0, x1), (y0, y1) = vb.viewRange()
        self.label.setText(f"t={x:.1f}s  " + "  ".join(parts))
        self.label.setPos(x if x < (x0 + x1) / 2 else x0, y1)
        self.vline.show()
        self.label.show()


def legend(plot, names):
    """Legend for >= 2 series (a single series is named by the title instead)."""
    if len(names) < 2:
        return None
    lg = plot.addLegend(offset=(-8, 8), labelTextColor=T["text"], brush=pg.mkBrush(11, 15, 20, 200),
                        pen=pg.mkPen("#32404F"))
    lg.setLabelTextSize("8pt")
    return lg
