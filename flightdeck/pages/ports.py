"""Serial ports (UART) setup: protocol, baud and options for every SERIALn port,
with board pad names, one-click presets and a reboot prompt."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QMenu, QMessageBox, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget)
from serial.tools import list_ports

from ..theme import T
from ..widgets import Card, button, label, set_kind

# Physical pad for each SERIALn, from the board's hwdef.dat (SERIAL_ORDER and pin comments).
BOARDS = {
    "speedybeef4v4": ("SpeedyBee F405 V4", {
        0: "USB",
        1: "UART1 · DJI / VTX pads · no DMA",
        2: "UART2 · receiver pads · DMA",
        3: "UART3 · no DMA",
        4: "UART4 · Bluetooth · no DMA",
        5: "UART5 · ESC telemetry (RX only)",
        6: "UART6 · GPS pads · DMA",
    }),
}

FALLBACK_PROTOCOLS = {-1: "None", 1: "MAVLink1", 2: "MAVLink2", 5: "GPS", 16: "ESC Telemetry", 23: "RCIN",
                      42: "DisplayPort"}
FALLBACK_BAUDS = {9: "9600", 19: "19200", 38: "38400", 57: "57600", 115: "115200", 230: "230400",
                  460: "460800", 921: "921600"}

# stream-rate params of one MAVLink channel, and the ELRS MAVLink recommendation for each
MAV_STREAMS = ["RAW_SENS", "EXT_STAT", "RC_CHAN", "RAW_CTRL", "POSITION", "EXTRA1", "EXTRA2", "EXTRA3",
               "PARAMS", "ADSB"]
ELRS_STREAMS = {s: (0 if s in ("RAW_CTRL", "PARAMS", "ADSB") else 1) for s in MAV_STREAMS}

# name -> (protocol, baud or None to keep, extra params, short help)
PRESETS = {
    "ELRS / CRSF receiver": (23, 115, {"RSSI_TYPE": 3},
                             "RC in over CRSF. Signal strength from the receiver."),
    "ELRS MAVLink receiver": (2, 460, {"RSSI_TYPE": 5},
                              "ELRS in MAVLink mode: sticks and full telemetry on one link. "
                              "Stream rates are set to 1 Hz as ExpressLRS recommends."),
    "Telemetry radio (SiK)": (2, 57, {}, "MAVLink2 at 57600 to a SiK / 3DR radio."),
    "GPS": (5, 230, {}, "GPS module (ArduPilot auto-configures u-blox)."),
    "ESC telemetry": (16, 115, {}, "BLHeli / Bluejay ESC telemetry wire."),
    "HD OSD (DisplayPort)": (42, 115, {}, "DJI O3 / Walksnail / HDZero OSD."),
    "Disabled": (-1, None, {}, "Port unused."),
}


def board_for(port):
    for p in list_ports.comports():
        if p.device == port:
            prod = (p.product or p.description or "").lower()
            for key, info in BOARDS.items():
                if key in prod:
                    return info
    return None


class PortsPage(QWidget):
    def __init__(self, link, meta, status):
        super().__init__()
        self.link = link
        self.meta = meta
        self.status = status
        self.pending = {}
        self.rows = {}  # n -> dict(proto, baud, opts, live, row widgets)
        self.reboot_needed = False
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(24, 20, 24, 24)
        v.setSpacing(14)
        sc.setWidget(inner)
        outer.addWidget(sc)

        head = QHBoxLayout()
        head.addWidget(label("Serial ports", "H1"))
        head.addStretch()
        self.board_lbl = label("", "Muted")
        head.addWidget(self.board_lbl)
        v.addLayout(head)
        v.addWidget(label("What is plugged into each UART. Pick a preset or set the protocol and baud yourself. "
                          "Serial changes only take effect after a reboot.", "Muted", True))

        self.card = Card("Ports")
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(8)
        self.card.add(self.grid_host)
        self.empty_lbl = label("Connect to the flight controller to see its serial ports.", "Muted", True)
        self.card.add(self.empty_lbl)
        v.addWidget(self.card)

        self.notes = label("", "Callout", True)
        self.notes.setTextFormat(Qt.RichText)
        self.notes.hide()
        v.addWidget(self.notes)
        v.addStretch()

        foot = QHBoxLayout()
        foot.setContentsMargins(24, 8, 24, 16)
        self.info = label("", "Muted")
        foot.addWidget(self.info, 1)
        self.revert_btn = button("Revert", "ghost", self._revert)
        self.reboot_btn = button("Reboot flight controller", None, self._reboot)
        self.write_btn = button("Write changes", "primary", self._write)
        for b in (self.revert_btn, self.reboot_btn, self.write_btn):
            foot.addWidget(b)
        outer.addLayout(foot)

        link.params_loaded.connect(self.rebuild)
        link.param_changed.connect(self._param_changed)
        link.job_status.connect(self._job)
        link.connection_changed.connect(self._conn_changed)
        self._refetch = None  # None, "wait_drop", "wait_up" while a reboot is in progress
        self.rebuild()

    # ---------- helpers ----------
    def value(self, name, default=None):
        if name in self.pending:
            return self.pending[name]
        return self.link.params.get(name, default)

    def _ports(self):
        return sorted(n for n in range(10) if f"SERIAL{n}_PROTOCOL" in self.link.params)

    def _choices(self, name, fallback):
        vals = self.meta.get(name, {}).get("values") or {}
        return {int(k): t for k, t in vals.items()} or fallback

    def _set(self, name, v):
        if name not in self.link.params:
            return
        if abs(float(v) - self.link.params[name]) < 1e-6:
            self.pending.pop(name, None)
        else:
            self.pending[name] = float(v)

    def _update_board(self):
        info = board_for(self.link.port) if self.link.port else None
        self.board = info
        self.board_lbl.setText(f"Board: {info[0]}" if info else "")

    # ---------- build ----------
    def rebuild(self):
        self._update_board()
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.rows = {}
        ports = self._ports()
        self.empty_lbl.setVisible(not ports)
        if ports:
            for c, h in enumerate(["Port", "Pad on board", "Protocol", "Baud", "Options", "Preset", "Live"]):
                self.grid.addWidget(label(h.upper(), "CardTitle"), 0, c)
        pads = self.board[1] if self.board else {}
        for r, n in enumerate(ports, 1):
            name_lbl = label(f"SERIAL{n}")
            name_lbl.setStyleSheet("font-weight:600;")
            pad = label(pads.get(n, "USB" if n == 0 else ""), "Muted")

            proto = QComboBox()
            for k, t in sorted(self._choices(f"SERIAL{n}_PROTOCOL", FALLBACK_PROTOCOLS).items(),
                               key=lambda kv: (kv[0] < 0, kv[1].lower())):
                proto.addItem(f"{t}  ({k})", k)
            proto.setMinimumWidth(220)
            proto.currentIndexChanged.connect(lambda _i, n=n: self._from_widgets(n))

            baud = QComboBox()
            for k, t in sorted(self._choices(f"SERIAL{n}_BAUD", FALLBACK_BAUDS).items()):
                baud.addItem(t, k)
            baud.currentIndexChanged.connect(lambda _i, n=n: self._from_widgets(n))
            if n == 0:
                baud.setEnabled(False)
                baud.setToolTip("USB ignores the baud rate")

            opts = QToolButton()
            opts.setPopupMode(QToolButton.InstantPopup)
            opts.setMinimumWidth(140)
            menu = QMenu(opts)
            bits = self.meta.get(f"SERIAL{n}_OPTIONS", {}).get("bits") or {}
            for b, t in sorted(bits.items()):
                a = QAction(t, menu)
                a.setCheckable(True)
                a.setData(b)
                a.toggled.connect(lambda _on, n=n: self._from_widgets(n))
                menu.addAction(a)
            opts.setMenu(menu)
            opts.setEnabled(f"SERIAL{n}_OPTIONS" in self.link.params and bool(bits))

            preset = QComboBox()
            preset.addItem("Apply preset…", None)
            for p, (_, _, _, help_) in PRESETS.items():
                preset.addItem(p, p)
                preset.setItemData(preset.count() - 1, help_, Qt.ToolTipRole)
            preset.activated.connect(lambda i, n=n, cb=preset: self._apply_preset(n, cb))
            if n == 0:
                preset.setEnabled(False)

            live = label("", "Faint")
            for c, w in enumerate([name_lbl, pad, proto, baud, opts, preset, live]):
                self.grid.addWidget(w, r, c)
            self.rows[n] = dict(proto=proto, baud=baud, opts=opts, menu=menu, live=live)
        self.grid.setColumnStretch(1, 1)
        self.load()

    def load(self):
        """Push current values (drone + pending) into the widgets."""
        self._loading = True
        for n, w in self.rows.items():
            p = int(self.value(f"SERIAL{n}_PROTOCOL", -1))
            j = w["proto"].findData(p)
            if j < 0:
                w["proto"].addItem(f"Unknown ({p})", p)
                j = w["proto"].count() - 1
            w["proto"].setCurrentIndex(j)
            b = self.value(f"SERIAL{n}_BAUD")
            if b is not None:
                j = w["baud"].findData(int(b))
                if j < 0:
                    w["baud"].addItem(f"{int(b)}", int(b))
                    j = w["baud"].count() - 1
                w["baud"].setCurrentIndex(j)
            o = int(self.value(f"SERIAL{n}_OPTIONS", 0) or 0)
            for a in w["menu"].actions():
                a.setChecked(bool(o & (1 << a.data())))
        self._loading = False
        self._refresh_view()

    def _from_widgets(self, n):
        if self._loading:
            return
        w = self.rows[n]
        self._set(f"SERIAL{n}_PROTOCOL", w["proto"].currentData())
        if n != 0 and w["baud"].currentData() is not None:
            self._set(f"SERIAL{n}_BAUD", w["baud"].currentData())
        if f"SERIAL{n}_OPTIONS" in self.link.params:
            o = sum(1 << a.data() for a in w["menu"].actions() if a.isChecked())
            self._set(f"SERIAL{n}_OPTIONS", o)
        self._refresh_view()

    # ---------- presets ----------
    def mav_channel(self, n):
        """MAVn_ prefix ArduPilot gives SERIALn (channels are handed out in port order to MAVLink ports)."""
        k = 0
        for p in self._ports():
            if int(self.value(f"SERIAL{p}_PROTOCOL", -1)) in (1, 2):
                k += 1
                if p == n:
                    return k
        return None

    def _apply_preset(self, n, cb):
        name = cb.currentData()
        cb.setCurrentIndex(0)
        if not name:
            return
        proto, baud, extra, _ = PRESETS[name]
        self._set(f"SERIAL{n}_PROTOCOL", proto)
        if baud is not None:
            self._set(f"SERIAL{n}_BAUD", baud)
        for k, v in extra.items():
            self._set(k, v)
        msg = f"SERIAL{n}: {name} — press Write, then reboot"
        if name == "ELRS MAVLink receiver":
            ch = self.mav_channel(n)
            names = [f"MAV{ch}_{s}" for s in MAV_STREAMS] if ch else []
            if names and all(x in self.link.params for x in names):
                for x in names:
                    self._set(x, ELRS_STREAMS[x.split("_", 1)[1]])
            else:
                msg += f". After the reboot, apply this preset again to set the MAV{ch or 'n'}_ stream rates"
        self.load()
        self.status(msg)

    # ---------- view ----------
    def _refresh_view(self):
        for n, w in self.rows.items():
            for key, pname in (("proto", "PROTOCOL"), ("baud", "BAUD"), ("opts", "OPTIONS")):
                changed = f"SERIAL{n}_{pname}" in self.pending
                w[key].setStyleSheet(f"color:{T['warn']}; font-weight:600;" if changed else "")
            o = int(self.value(f"SERIAL{n}_OPTIONS", 0) or 0)
            on = [a.text() for a in w["menu"].actions() if a.isChecked()]
            w["opts"].setText("None" if not o else (on[0] if len(on) == 1 else f"{len(on)} set"))
            w["opts"].setToolTip("\n".join(on) if on else "No options set")
        n = len(self.pending)
        extra = [k for k in self.pending if not k.startswith("SERIAL")]
        txt = f"{n} unsaved change{'s' if n != 1 else ''}" if n else "No unsaved changes"
        if extra:
            txt += f" (incl. {', '.join(extra[:3])}{'…' if len(extra) > 3 else ''})"
        self.info.setText(txt)
        self.write_btn.setEnabled(bool(n) and self.link.state.connected)
        self.write_btn.setText(f"Write {n} change{'s' if n != 1 else ''}" if n else "Write changes")
        self.revert_btn.setEnabled(bool(n))
        self.reboot_btn.setEnabled(self.link.state.connected)
        set_kind(self.reboot_btn, "primary" if self.reboot_needed and not n else None)
        self._notes()

    def _notes(self):
        ports = self._ports()
        if not ports:
            self.notes.hide()
            return
        proto = {n: int(self.value(f"SERIAL{n}_PROTOCOL", -1)) for n in ports}
        baud = {n: int(self.value(f"SERIAL{n}_BAUD", 0) or 0) for n in ports}
        warn, info = [], []
        rc = [n for n, p in proto.items() if p == 23]
        if len(rc) > 1:
            warn.append(f"RCIN is set on {len(rc)} ports (SERIAL{', SERIAL'.join(map(str, rc))}). Use only one.")
        gps = [n for n, p in proto.items() if p == 5]
        if not gps and int(self.value("GPS1_TYPE", 0) or 0) != 0:
            warn.append("GPS1_TYPE is set but no port uses the GPS protocol.")
        rssi = int(self.value("RSSI_TYPE", 0) or 0)
        if rc and rssi not in (0, 3):
            warn.append("A CRSF receiver is on RCIN but RSSI_TYPE isn't 3 (receiver protocol).")
        pads = self.board[1] if self.board else {}
        for n, p in proto.items():
            if n and "no DMA" in pads.get(n, "") and p in (1, 2, 23) and baud.get(n, 0) > 115:
                warn.append(f"SERIAL{n} has no DMA. At {baud[n]}k with {FALLBACK_PROTOCOLS.get(p, p)} it may "
                            "drop data. Prefer a DMA port or 115200.")
        for n, p in proto.items():
            if n and p in (1, 2):
                ch = self.mav_channel(n)
                info.append(f"SERIAL{n} is MAVLink channel <b>MAV{ch}</b> (its stream rates are MAV{ch}_*).")
        if self.reboot_needed:
            warn.insert(0, "Serial settings were written. <b>Reboot the flight controller</b> to apply them.")
        if not warn and not info:
            self.notes.hide()
            return
        html = "<br>".join([f"⚠ {w}" for w in warn] + info)
        self.notes.setText(html)
        set_kind(self.notes, "warn" if warn else None)
        self.notes.show()

    def tick(self):
        st = self.link.state
        for n, w in self.rows.items():
            p = int(self.value(f"SERIAL{n}_PROTOCOL", -1))
            txt = ""
            if not st.connected:
                txt = ""
            elif p == 23:
                txt = f"{st.rc_count} ch · RSSI {round(st.rc_rssi / 2.54)}%" if st.rc_count else "no RC"
            elif p == 5:
                fix = {0: "no GPS", 1: "no fix", 2: "2D", 3: "3D"}.get(st.gps_fix, "3D+")
                txt = f"{fix} · {st.sats} sats"
            elif p in (1, 2) and n == 0:
                txt = "this connection" if self._on_usb else ""
            w["live"].setText(txt)

    @property
    def _on_usb(self):
        port = self.link.port or ""
        if getattr(self, "_usb_cache", (None,))[0] != port:
            from ..link import is_fc_usb
            self._usb_cache = (port, is_fc_usb(port))
        return self._usb_cache[1]

    def _conn_changed(self, ok, _msg):
        self._update_board()
        if self._refetch == "wait_drop" and not ok:
            self._refetch = "wait_up"
        elif self._refetch == "wait_up" and ok:
            self._refetch = None
            import threading
            threading.Thread(target=self.link.fetch_params, daemon=True).start()
        self._refresh_view()

    # ---------- actions ----------
    def _param_changed(self, name, _v):
        if name.startswith("SERIAL") and self.rows and not self._loading:
            n = name[6:].split("_")[0]
            if n.isdigit() and int(n) not in self.rows:
                return
            if name not in self.pending:
                self.load()

    def _revert(self):
        self.pending.clear()
        self.load()

    def _write(self):
        if not self.link.state.connected or not self.pending:
            return
        lines = "\n".join(f"{k} = {v:g}" for k, v in sorted(self.pending.items()))
        if QMessageBox.question(self, "Write serial settings?",
                                f"Write these to the flight controller?\n\n{lines}\n\n"
                                "They take effect after a reboot.") != QMessageBox.Yes:
            return
        self.link.write_params(dict(self.pending), job="ports")

    def _job(self, job, msg):
        if job != "ports":
            return
        self.status(msg)
        if msg.startswith("Wrote"):
            self.pending = {k: v for k, v in self.pending.items()
                            if abs(self.link.params.get(k, 1e99) - v) > 1e-4}
            self.reboot_needed = True
            self.load()

    def _reboot(self):
        if not self.link.state.connected:
            return
        if self.link.state.armed:
            QMessageBox.warning(self, "Reboot", "Disarm before rebooting.")
            return
        if QMessageBox.question(self, "Reboot flight controller?",
                                "Reboot now? The USB link drops for a few seconds and reconnects.") \
                != QMessageBox.Yes:
            return
        self.link.reboot()
        self._refetch = "wait_drop"
        self.reboot_needed = False
        self.status("Rebooting… parameters reload after it reconnects")
        self._refresh_view()
