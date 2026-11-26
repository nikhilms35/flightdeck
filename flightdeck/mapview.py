import json

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from .tileserver import ASSETS, TILES


def _export_qwebchannel_js():
    """Pages are served over http, which may not load qrc:// — so copy Qt's qwebchannel.js next to them."""
    from PySide6.QtCore import QFile, QIODevice
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.ReadOnly):
        return
    data = bytes(f.readAll())
    f.close()
    dst = ASSETS / "qwebchannel.js"
    try:
        if not dst.exists() or dst.read_bytes() != data:
            dst.write_bytes(data)
    except OSError:
        pass  # read-only install (e.g. system site-packages); bundled copy is used


_export_qwebchannel_js()


class _Bridge(QObject):
    clicked = Signal(float, float)
    context = Signal(float, float)
    moved = Signal(int, float, float)
    loaded = Signal()
    message = Signal(str)

    @Slot()
    def ready(self):
        self.loaded.emit()

    @Slot(float, float)
    def mapClicked(self, lat, lon):
        self.clicked.emit(lat, lon)

    @Slot(float, float)
    def mapContext(self, lat, lon):
        self.context.emit(lat, lon)

    @Slot(int, float, float)
    def markerMoved(self, i, lat, lon):
        self.moved.emit(i, lat, lon)

    @Slot(str)
    def say(self, text):
        self.message.emit(text)


class WebView(QWebEngineView):
    """QWebEngineView hosting one of our local HTML pages with a `bridge` web channel."""

    def __init__(self, page_name):
        super().__init__()
        s = self.settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebGLEnabled, True)
        s.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
        self.page().setBackgroundColor("#0A0A0B")
        self.bridge = _Bridge()
        self.channel = QWebChannel(self.page())
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self._ready = False
        self._pending = []
        self.bridge.loaded.connect(self._on_ready)
        # served over http from the local server (Cesium's web workers can't start from file://)
        self.load(QUrl(f"{TILES.base}/a/{page_name}?t={TILES.base}"))

    def _on_ready(self):
        self._ready = True
        self.on_ready()
        for code in self._pending:
            self.page().runJavaScript(code)
        self._pending.clear()

    def on_ready(self):
        pass

    @property
    def ready(self):
        return self._ready

    def js(self, code):
        if self._ready:
            self.page().runJavaScript(code)
        else:
            self._pending.append(code)

    def eval(self, code, callback):
        self.page().runJavaScript(code, 0, callback)


class MapView(WebView):
    def __init__(self, plan=False):
        self._plan = plan
        self._last_home = None
        self._last_fence = None
        super().__init__("map.html")

    def on_ready(self):
        if self._plan:
            self.page().runJavaScript("setPlanMode(true)")

    _auto = "esri"

    def auto_base(self):
        """Show the best satellite source that currently works (unless the user picked a layer).
        Returns a short note for the status bar when it changes."""
        if not self._ready:
            return None
        best = TILES.best_satellite()
        if best == self._auto:
            return None
        self._auto = best
        self.js(f"autoBase('{best}')")
        return {"esri": "Esri satellite imagery available — switched to it",
                "maptiler": "Using MapTiler HD satellite imagery",
                "s2": "Esri satellite blocked on this network — using Sentinel-2 satellite (10 m detail)",
                "osm": "No satellite source reachable — showing Streets map"}[best]

    def set_vehicle(self, lat, lon, hdg):
        self.js(f"setVehicle({lat:.7f},{lon:.7f},{hdg:.0f})")

    def set_home(self, lat, lon):
        if self._last_home != (lat, lon):
            self._last_home = (lat, lon)
            self.js(f"setHome({lat:.7f},{lon:.7f})")

    def set_fence(self, lat, lon, radius):
        key = (round(lat, 6), round(lon, 6), radius) if radius else None
        if key == self._last_fence:
            return
        self._last_fence = key
        self.js(f"setFence({lat:.7f},{lon:.7f},{radius:.1f})" if radius else "clearFence()")

    def set_target(self, lat, lon):
        self.js(f"setTarget({lat:.7f},{lon:.7f})")

    def set_waypoints(self, wps):
        self.js(f"setWaypoints({json.dumps(wps)})")

    def fit(self):
        self.js("fitWaypoints()")
