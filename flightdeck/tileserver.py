"""Local caching tile server. Every map (2D Leaflet and 3D Cesium) loads tiles from
http://127.0.0.1:<port>/t/<provider>/<z>/<x>/<y>. Online: fetch upstream and store on disk.
Offline: serve from disk. Missing tiles return 404 so the map can fall back to a lower zoom."""
import concurrent.futures
import math
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "flightdeck" / "tiles"
UA = "FlightDeck/0.2 (ArduPilot ground station)"

PROVIDERS = {
    # name: (url template, extension, max native zoom, bulk download allowed)
    "esri": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
             "?blankTile=false", "jpg", 19, True),
    "osm": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "png", 19, False),
    "carto": ("https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png", "png", 20, False),
    "terrain": ("https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", "png", 15, True),
    # MapTiler satellite (sharp, needs a free API key: maptiler.com → Account → API keys)
    "maptiler": ("https://api.maptiler.com/maps/satellite/256/{z}/{x}/{y}.jpg?key={key}", "jpg", 20, False),
    # Sentinel-2 cloudless 2016 by EOX (CC BY 4.0, no key; 10 m/pixel so soft when zoomed in)
    "s2": ("https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg", "jpg", 14, True),
}
NEEDS_KEY = {"maptiler"}
SATELLITE_ORDER = ["esri", "maptiler", "s2"]   # best first
CTYPE = {"jpg": "image/jpeg", "png": "image/png"}
ASSETS = Path(__file__).resolve().parent / "assets"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript",
                ".css": "text/css", ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
                ".svg": "image/svg+xml", ".wasm": "application/wasm", ".glb": "model/gltf-binary",
                ".ktx2": "image/ktx2", ".xml": "application/xml", ".ttf": "font/ttf", ".woff2": "font/woff2"}
NEG_TTL = 7 * 86400      # remember "tile doesn't exist" for a week
PROBE_EVERY = 15         # while offline, retry the network at most this often
FETCH_DEADLINE = 6       # seconds for one whole upstream fetch
# one download pool per provider, so an unreachable host can't starve the others
_POOLS = {p: concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix=f"fetch-{p}") for p in
          PROVIDERS}


def lonlat_to_tile(lon, lat, z):
    lat = max(min(lat, 85.0511), -85.0511)
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tiles_in_bounds(south, west, north, east, zmin, zmax):
    for z in range(zmin, zmax + 1):
        x0, y0 = lonlat_to_tile(west, north, z)
        x1, y1 = lonlat_to_tile(east, south, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield z, x, y


def count_tiles(bounds, zmin, zmax):
    s, w, n, e = bounds
    total = 0
    for z in range(zmin, zmax + 1):
        x0, y0 = lonlat_to_tile(w, n, z)
        x1, y1 = lonlat_to_tile(e, s, z)
        total += (x1 - x0 + 1) * (y1 - y0 + 1)
    return total


class TileServer:
    def __init__(self):
        self.online = True            # overall: did the most recent upstream request succeed?
        self.last_ok = 0.0
        self.last_fail = 0.0
        self.down_since = {}          # provider -> time it last failed (reachability tracked per provider)
        self.keys = {}                # provider -> API key
        self.key_rejected = set()     # providers whose key was refused (401/403)
        self.served = 0
        self._httpd = None
        self.port = None

    # ---------------- cache ----------------
    @staticmethod
    def path(prov, z, x, y):
        return CACHE / prov / str(z) / str(x) / f"{y}.{PROVIDERS[prov][1]}"

    def _fetch(self, prov, z, x, y):
        """Returns (status, bytes). status: 200, 404, or 0 for network failure."""
        url = PROVIDERS[prov][0].format(z=z, x=x, y=y, key=urllib.parse.quote(self.keys.get(prov, "")))
        req = urllib.request.Request(url, headers={"User-Agent": UA})

        def get():
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.read()
        try:
            # Hard overall deadline: urlopen's timeout applies per IP address, and a host with
            # 8 addresses (e.g. S3) can otherwise take ~40 s to fail, freezing the 3D terrain.
            data = _POOLS[prov].submit(get).result(timeout=FETCH_DEADLINE)
            self._ok(prov)
            return 200, data
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and prov in NEEDS_KEY:
                self.key_rejected.add(prov)
                return 0, b""
            self._ok(prov)
            return (404 if e.code in (404, 410) else 0), b""
        except Exception:
            self.last_fail = time.time()
            self.down_since[prov] = self.last_fail
            self.online = False
            return 0, b""

    def _ok(self, prov):
        self.last_ok = time.time()
        self.down_since.pop(prov, None)
        self.online = True

    def reachable(self, prov):
        """False while a provider failed recently (re-probed every PROBE_EVERY seconds),
        or when it needs an API key that is missing or was rejected."""
        if prov in NEEDS_KEY and (not self.keys.get(prov) or prov in self.key_rejected):
            return False
        t = self.down_since.get(prov)
        return t is None or time.time() - t >= PROBE_EVERY

    def set_key(self, prov, key):
        self.keys[prov] = key.strip()
        self.key_rejected.discard(prov)
        self.down_since.pop(prov, None)

    def best_satellite(self):
        """Best satellite provider that currently works, else 'osm' (streets)."""
        return next((p for p in SATELLITE_ORDER if self.reachable(p)), "osm")

    def test_provider(self, prov):
        """Blocking: fetch one tile (Bengaluru, z15) bypassing the cache. Returns (ok, message)."""
        self.down_since.pop(prov, None)
        self.key_rejected.discard(prov)
        status, data = self._fetch(prov, 15, 23300, 15200)
        if status == 200 and data:
            return True, f"OK — {len(data) // 1024} KB tile received"
        if prov in self.key_rejected:
            return False, "The key was rejected (401/403). Check it was copied completely."
        if not self.reachable(prov):
            return False, "Server not reachable from this network."
        return False, f"Unexpected response ({status})."

    def get(self, prov, z, x, y, allow_network=True):
        p = self.path(prov, z, x, y)
        if p.exists():
            return 200, p.read_bytes()
        neg = p.with_suffix(".none")
        if neg.exists() and time.time() - neg.stat().st_mtime < NEG_TTL:
            return 404, b""
        if not allow_network:
            return 404, b""
        if not self.reachable(prov):
            return 404, b""          # provider unreachable or no key: don't stall the map on timeouts
        status, data = self._fetch(prov, z, x, y)
        if status == 200 and data:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(p)
            return 200, data
        if status == 404:
            p.parent.mkdir(parents=True, exist_ok=True)
            neg.touch()
        return 404, b""

    def cache_size(self):
        total = files = 0
        if CACHE.exists():
            for root, _, fs in os.walk(CACHE):
                for f in fs:
                    if not f.endswith(".none"):
                        files += 1
                        total += os.path.getsize(os.path.join(root, f))
        return total, files

    def clear(self):
        shutil.rmtree(CACHE, ignore_errors=True)

    # ---------------- bulk download ----------------
    def prefetch(self, prov, bounds, zmin, zmax, progress, cancel):
        """Blocking; call from a thread. progress(done, total, failed)."""
        tiles = list(tiles_in_bounds(*bounds, zmin, zmax))
        total, done, failed = len(tiles), 0, 0
        lock = threading.Lock()
        it = iter(tiles)

        def worker():
            nonlocal done, failed
            while not cancel.is_set():
                with lock:
                    t = next(it, None)
                if t is None:
                    return
                p = self.path(prov, *t)
                if not p.exists():
                    self.get(prov, *t)
                    if not self.reachable(prov):
                        cancel.set()
                with lock:
                    done += 1
                    if not p.exists():
                        failed += 1
                    if done % 10 == 0 or done == total:
                        progress(done, total, failed)
        ths = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        progress(done, total, failed)
        return done, total, failed

    # ---------------- http ----------------
    def start(self):
        server = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _static(self, rel):
                p = (ASSETS / rel).resolve()
                if not str(p).startswith(str(ASSETS) + os.sep) or not p.is_file():
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = p.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", STATIC_TYPES.get(p.suffix.lower(), "application/octet-stream"))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                raw = urllib.parse.unquote(self.path.split("?")[0])
                if raw.startswith("/a/"):
                    return self._static(raw[3:])
                parts = raw.strip("/").split("/")
                try:
                    assert parts[0] == "t" and parts[1] in PROVIDERS
                    z, x, y = int(parts[2]), int(parts[3]), int(parts[4].split(".")[0])
                except Exception:
                    self.send_response(400)
                    self.end_headers()
                    return
                status, data = server.get(parts[1], z, x, y)
                server.served += 1
                self.send_response(status)
                self.send_header("Access-Control-Allow-Origin", "*")
                if status == 200:
                    self.send_header("Content-Type", CTYPE[PROVIDERS[parts[1]][1]])
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", "0")
                    self.end_headers()

        ThreadingHTTPServer.daemon_threads = True
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self.port

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"


TILES = TileServer()
