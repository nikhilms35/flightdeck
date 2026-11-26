import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout,
                               QListWidget, QMessageBox, QProgressBar, QScrollArea, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..link import ACCEL_POSITIONS
from .params import load_metadata
from ..widgets import Card, ChannelBar, ModeRangeSlider, MotorDiagram, button, label, set_kind


def page(title, intro):
    w = QWidget()
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 0, 0, 0)
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    inner = QWidget()
    v = QVBoxLayout(inner)
    v.setContentsMargins(24, 20, 24, 24)
    v.setSpacing(14)
    v.addWidget(label(title, "H1"))
    if intro:
        v.addWidget(label(intro, "Muted", True))
    sc.setWidget(inner)
    outer.addWidget(sc)
    return w, v


def callout(text, kind=None):
    lb = label(text, "Callout", True)
    lb.setTextFormat(Qt.RichText)
    set_kind(lb, kind)
    return lb


class SetupPage(QWidget):
    def __init__(self, link, status):
        super().__init__()
        self.link = link
        self.status = status
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        navw = QWidget()
        navw.setFixedWidth(210)
        nv = QVBoxLayout(navw)
        nv.setContentsMargins(12, 20, 8, 12)
        nv.addWidget(label("SETUP", "CardTitle"))
        self.nav = QListWidget()
        self.nav.setObjectName("SubNav")
        nv.addWidget(self.nav)
        root.addWidget(navw)

        self.fw_note = label("", "Faint", True)
        self.fw_note.setTextFormat(Qt.RichText)
        nv.addWidget(self.fw_note)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.pages = {}
        self._build(link.firmware)
        link.firmware_changed.connect(self._build)

        link.accelcal_pos.connect(self._accel_pos)
        link.magcal_progress.connect(self._mag_progress)
        link.magcal_report.connect(self._mag_report)
        link.statustext.connect(self._statustext)
        link.params_loaded.connect(self.reload_params)
        link.job_status.connect(self._job_status)
        self._reboot_after_write = False

    BUILDERS = ["Frame", "Accelerometer", "Compass", "Radio", "Flight modes", "Motor test", "Motor direction",
                "Battery & failsafe", "Geofence"]

    def _build(self, fw):
        """(Re)create the sub-pages that apply to this firmware."""
        self.fw = fw
        self.meta = load_metadata(fw)
        current = self.nav.currentItem().text() if self.nav.currentItem() else None
        builders = {"Frame": self._frame, "Accelerometer": self._accel, "Compass": self._compass,
                    "Radio": self._radio, "Flight modes": self._modes, "Motor test": self._motors,
                    "Motor direction": self._direction, "Battery & failsafe": self._failsafe,
                    "Geofence": self._fence}
        self.nav.blockSignals(True)
        self.nav.clear()
        while self.stack.count():
            old = self.stack.widget(0)
            self.stack.removeWidget(old)
            old.deleteLater()
        self.pages = {}
        self._acc_pos = None
        self._rc_cal = None
        for name in self.BUILDERS:
            if name in fw.setup_pages:
                self.nav.addItem(name)
                self.pages[name] = builders[name]()
                self.stack.addWidget(self.pages[name])
        self.nav.blockSignals(False)
        names = list(self.pages)
        self.nav.setCurrentRow(names.index(current) if current in names else 0)
        self.fw_note.setText(f"<b>{fw.name}</b><br>{fw.notes}" if fw.notes else f"<b>{fw.name}</b>")
        if self.link.params:
            self.reload_params()

    def _current(self):
        it = self.nav.currentItem()
        return it.text() if it else None

    def _job_status(self, job, msg):
        if job != "setup":
            return
        self.status(msg)
        if msg.startswith("Wrote"):
            if self._reboot_after_write:
                self._reboot_after_write = False
                self.link.reboot()
                self.status(msg + " · rebooting")
            if self._current() == "Radio":
                self.rc_cal_lbl.setText(msg)

    # ======================= helpers =======================
    def _need(self):
        if not self.link.state.connected:
            QMessageBox.information(self, "Not connected", "Connect to the flight controller first.")
            return False
        return True

    def _p(self, name, default=None):
        return self.link.params.get(name, default)

    # ======================= frame =======================
    def _frame(self):
        w, v = page("Frame", "Tell ArduCopter how many motors your multirotor has and how they are arranged. "
                             "Most quads, including deadcat and stretched-X frames, use Quad + X.")
        row = QHBoxLayout()
        row.setSpacing(14)
        c = Card("Frame type")
        f = QFormLayout()
        f.setSpacing(10)
        self.frame_class = QComboBox()
        for k, n in [(1, "Quad"), (2, "Hexa"), (3, "Octa"), (4, "OctaQuad (X8)"), (5, "Y6"), (7, "Tri"),
                     (12, "Dodeca-hexa"), (14, "Deca")]:
            self.frame_class.addItem(n, k)
        self.frame_type = QComboBox()
        for k, n in [(1, "X"), (0, "Plus (+)"), (2, "V"), (3, "H"), (12, "X, Betaflight motor order"),
                     (18, "X, Betaflight order reversed"), (13, "X, DJI motor order"), (14, "X, clockwise order"),
                     (10, "Y6B"), (11, "Y6F")]:
            self.frame_type.addItem(n, k)
        f.addRow("Class", self.frame_class)
        f.addRow("Layout", self.frame_type)
        c.add(f)
        r = QHBoxLayout()
        r.addStretch()
        r.addWidget(button("Write & reboot", "primary", self._write_frame))
        c.add(r)
        c.lay.addStretch()
        row.addWidget(c, 1)
        pc = Card("Preview")
        self.frame_preview = MotorDiagram()
        pc.add(self.frame_preview, 1)
        self.frame_preview_lbl = label("", "Faint", True)
        pc.add(self.frame_preview_lbl)
        row.addWidget(pc, 1)
        v.addLayout(row)
        self.frame_class.currentIndexChanged.connect(self._frame_preview)
        self.frame_type.currentIndexChanged.connect(self._frame_preview)
        self._frame_preview()
        v.addWidget(callout("After changing the frame the flight controller must reboot. "
                            "Then run <b>Motor test</b> to confirm order and direction."))
        v.addStretch()
        return w

    def _frame_preview(self, *_):
        fc, ft = self.frame_class.currentData(), self.frame_type.currentData()
        ok = MotorDiagram.supported(fc, ft)
        self.frame_preview.setVisible(ok)
        self.frame_preview.set_frame(fc, ft)
        self.frame_preview_lbl.setText(MotorDiagram.NAMES[(fc, ft)] if ok else
                                       "No preview for this combination. Check the motor order diagram in the "
                                       "ArduPilot docs, and make sure the layout exists for this class.")

    def _write_frame(self):
        if not self._need():
            return
        ch = {"FRAME_CLASS": self.frame_class.currentData(), "FRAME_TYPE": self.frame_type.currentData()}
        self._reboot_after_write = True
        self.link.write_params(ch, job="setup")

    # ======================= accelerometer =======================
    def _accel(self):
        w, v = page("Accelerometer", f"Place the {self.fw.vehicle} in six positions when asked. Hold it still in each one.")
        c = Card("6-position calibration")
        self.acc_prompt = label("Not started", "BigPrompt")
        c.add(self.acc_prompt)
        self.acc_detail = label(f"Click Start, then place the {self.fw.vehicle} LEVEL on a flat surface.", "Muted", True)
        c.add(self.acc_detail)
        r = QHBoxLayout()
        self.acc_start = button("Start calibration", "primary", self._accel_start)
        self.acc_next = button("Done — next position", "ok", self._accel_next)
        self.acc_next.setEnabled(False)
        r.addWidget(self.acc_start)
        r.addWidget(self.acc_next)
        r.addStretch()
        c.add(r)
        v.addWidget(c)
        lc = Card("Level trim")
        lc.add(label("If it drifts in a self-levelling mode, put it on a level surface and run a quick level calibration.",
                     "Muted", True))
        r2 = QHBoxLayout()
        r2.addWidget(button("Calibrate level", None, lambda: self._need() and self.link.level_cal()))
        r2.addStretch()
        lc.add(r2)
        v.addWidget(lc)
        v.addStretch()
        self._acc_pos = None
        return w

    def _accel_start(self):
        if not self._need():
            return
        self.link.accel_cal_start()
        self.acc_prompt.setText("Starting…")
        self.acc_start.setEnabled(False)

    def _accel_pos(self, pos):
        if "Accelerometer" not in self.pages:
            return
        name = ACCEL_POSITIONS.get(pos, f"Position {pos}")
        if pos in (16777215, 16777216):
            ok = pos == 16777215
            self.acc_prompt.setText("Calibration successful ✓" if ok else "Calibration failed ✗")
            self.acc_detail.setText("Reboot the flight controller to apply." if ok
                                    else f"Try again — keep the {self.fw.vehicle} completely still in each position.")
            self.acc_next.setEnabled(False)
            self.acc_start.setEnabled(True)
            self._acc_pos = None
            return
        self._acc_pos = pos
        self.acc_prompt.setText(f"{pos}/6 · {name}")
        self.acc_detail.setText(f"Place the {self.fw.vehicle} like this, hold still, then click “Done — next position”.")
        self.acc_next.setEnabled(True)

    def _accel_next(self):
        if self._acc_pos:
            self.link.accel_cal_confirm(self._acc_pos)
            self.acc_next.setEnabled(False)
            self.acc_detail.setText("Sampling… keep still.")

    # ======================= compass =======================
    def _compass(self):
        w, v = page("Compass", "Do this outdoors, away from cars, metal tables and your laptop.")
        self.compass_info = callout("Connect to see detected compasses.")
        v.addWidget(self.compass_info)
        c = Card("Onboard calibration")
        c.add(label(f"Click Start, then pick up the {self.fw.vehicle} and slowly rotate it so every side points at the "
                    "ground once (roll it over, nose down, nose up, both sides). Keep going until all bars reach 100%.",
                    "Muted", True))
        self.mag_bars = []
        for i in range(3):
            row = QHBoxLayout()
            lb = label(f"Compass {i + 1}")
            lb.setFixedWidth(90)
            pb = QProgressBar()
            pb.setRange(0, 100)
            row.addWidget(lb)
            row.addWidget(pb, 1)
            holder = QWidget()
            holder.setLayout(row)
            holder.hide()
            c.add(holder)
            self.mag_bars.append((holder, pb))
        self.mag_result = label("", None, True)
        self.mag_result.setTextFormat(Qt.RichText)
        c.add(self.mag_result)
        r = QHBoxLayout()
        r.addWidget(button("Start", "primary", self._mag_start))
        r.addWidget(button("Cancel", "ghost", lambda: self.link.mag_cal_cancel()))
        r.addStretch()
        self.mag_reboot = button("Reboot to apply", "ok", lambda: self.link.reboot())
        self.mag_reboot.hide()
        r.addWidget(self.mag_reboot)
        c.add(r)
        v.addWidget(c)
        v.addStretch()
        return w

    def _mag_start(self):
        if not self._need():
            return
        for h, pb in self.mag_bars:
            pb.setValue(0)
        self.mag_result.setText(f"Rotate the {self.fw.vehicle} now…")
        self.mag_reboot.hide()
        self.link.mag_cal_start()

    def _mag_progress(self, cid, pct):
        if "Compass" not in self.pages:
            return
        if cid < 3:
            h, pb = self.mag_bars[cid]
            h.show()
            pb.setValue(pct)

    def _mag_report(self, cid, status, fitness):
        if "Compass" not in self.pages:
            return
        ok = status == 4
        names = {4: "success", 5: "failed", 6: "bad orientation", 7: "bad radius"}
        col = "#2FBF71" if ok else "#F05A52"
        prev = self.mag_result.text() if "Compass" in self.mag_result.text() else ""
        self.mag_result.setText(prev + f"<div><span style='color:{col}'>●</span> Compass {cid + 1}: "
                                f"<b>{names.get(status, status)}</b> · fitness {fitness:.1f}</div>")
        if ok:
            self.mag_reboot.show()

    # ======================= radio =======================
    def _radio(self):
        w, v = page("Radio", "Check every stick and switch moves the right bar. Then calibrate.")
        self.rc_warn = callout("", "warn")
        self.rc_warn.hide()
        v.addWidget(self.rc_warn)
        c = Card("Channels")
        names = ["1 · Roll", "2 · Pitch", "3 · Throttle", "4 · Yaw"] + [f"{i} · Aux" for i in range(5, 13)]
        self.rc_bars = [ChannelBar(n) for n in names]
        for b in self.rc_bars:
            c.add(b)
        v.addWidget(c)
        cc = Card("Calibration")
        self.rc_cal_lbl = label("1. Click Start.  2. Move all sticks and switches to their full extents.  "
                                "3. Centre the sticks, throttle LOW, then click Save.", "Muted", True)
        cc.add(self.rc_cal_lbl)
        r = QHBoxLayout()
        self.rc_start = button("Start", "primary", self._rc_start)
        self.rc_save = button("Save calibration", "ok", self._rc_save)
        self.rc_save.setEnabled(False)
        r.addWidget(self.rc_start)
        r.addWidget(self.rc_save)
        r.addStretch()
        cc.add(r)
        v.addWidget(cc)
        v.addStretch()
        self._rc_cal = None
        return w

    def _rc_start(self):
        if not self._need():
            return
        if self.link.state.rc_count == 0:
            QMessageBox.warning(self, "No receiver", "No RC channels are coming from the receiver.")
            return
        self._rc_cal = [[9999, 0] for _ in range(12)]
        self.rc_save.setEnabled(True)
        self.rc_start.setEnabled(False)
        self.rc_cal_lbl.setText("Recording… move every stick and switch to both ends, several times.")

    def _rc_save(self):
        st = self.link.state
        ch = {}
        for i, (lo, hi) in enumerate(self._rc_cal):
            if hi - lo < 300:  # channel did not move enough — skip
                continue
            trim = st.rc[i] if i != 2 else lo
            ch[f"RC{i + 1}_MIN"] = lo
            ch[f"RC{i + 1}_MAX"] = hi
            ch[f"RC{i + 1}_TRIM"] = min(max(trim, lo), hi)
        self._rc_cal = None
        self.rc_save.setEnabled(False)
        self.rc_start.setEnabled(True)
        if not ch:
            self.rc_cal_lbl.setText("No channel moved enough — nothing saved.")
            return
        self.rc_cal_lbl.setText(f"Saving {len(ch) // 3} channels…")
        self.link.write_params(ch, job="setup")

    # ======================= flight modes =======================
    # ArduPilot's fixed FLTMODE1-6 / MODE1-6 PWM bands (slot 1 also covers anything below, slot 6 anything above)
    MODE_RANGES = [(900, 1230), (1231, 1360), (1361, 1490), (1491, 1620), (1621, 1749), (1750, 2100)]
    # PX4 splits the calibrated stick range into six equal slots
    PX4_RANGES = [(900, 1166), (1167, 1333), (1334, 1500), (1501, 1666), (1667, 1833), (1834, 2100)]

    def _mode_options(self):
        """[(value written to the slot parameter, label)] for this firmware's mode switch."""
        opts = self.fw.mode_switch[2]
        if opts:
            return list(opts.items())
        order = self.fw.mode_names()
        num = {v: k for k, v in self.fw.modes.items()}
        return [(num[n], n) for n in order]

    def _modes(self):
        fw = self.fw
        px4 = fw.family == "px4"
        self.fm_ranges = self.PX4_RANGES if px4 else self.MODE_RANGES
        w, v = page("Flight modes", "Pick a switch channel and assign a mode to each position. "
                                    "A 3-position switch hits slots 1, 4 and 6."
                    + (" On PX4 the slots are approximate: they depend on your radio calibration." if px4 else ""))
        c = Card("Mode switch")
        top = QHBoxLayout()
        top.addWidget(label("Switch channel"))
        self.fm_ch = QComboBox()
        if px4:
            self.fm_ch.addItem("Not used", 0)
        for i in range(5, 17):
            self.fm_ch.addItem(f"Channel {i}", i)
        top.addWidget(self.fm_ch)
        top.addStretch()
        self.fm_pwm = label("", "Muted")
        self.fm_pwm.setTextFormat(Qt.RichText)
        top.addWidget(self.fm_pwm)
        c.add(top)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        self.fm_boxes, self.fm_marks, self.fm_sliders = [], [], []
        options = self._mode_options()
        for i in range(6):
            mark = label("●")
            mark.setStyleSheet("color:#2A2A2F;")
            g.addWidget(mark, i, 0)
            lo, hi = self.fm_ranges[i]
            name = QVBoxLayout()
            name.setSpacing(0)
            name.addWidget(label(f"Mode {i + 1}"))
            name.addWidget(label(f"{'<' if i == 0 else ''}{lo if i else hi}"
                                 f"{'' if i == 0 else ('+' if i == 5 else f'–{hi}')} µs", "Faint"))
            g.addLayout(name, i, 1)
            cb = QComboBox()
            for val, text in options:
                cb.addItem(text, val)
            cb.setMinimumWidth(150)
            g.addWidget(cb, i, 2)
            sl = ModeRangeSlider(lo, hi)
            g.addWidget(sl, i, 3)
            self.fm_boxes.append(cb)
            self.fm_marks.append(mark)
            self.fm_sliders.append(sl)
        g.setColumnStretch(3, 1)
        c.add(g)
        r = QHBoxLayout()
        r.addStretch()
        r.addWidget(button("Write modes", "primary", self._write_modes))
        c.add(r)
        v.addWidget(c)
        if fw.suggested:
            v.addWidget(callout(fw.suggested))
        v.addStretch()
        return w

    def _write_modes(self):
        if not self._need():
            return
        ch_param, slot_fmt, _ = self.fw.mode_switch
        ch = {ch_param: self.fm_ch.currentData()}
        for i, cb in enumerate(self.fm_boxes):
            ch[slot_fmt.format(i + 1)] = cb.currentData()
        missing = [k for k in ch if self.link.params and k not in self.link.params]
        if missing:
            QMessageBox.warning(self, "Not available", f"This vehicle doesn't have {', '.join(missing)}. "
                                                       "Check the firmware selection in the top bar.")
            return
        self.link.write_params(ch, job="setup")

    # ======================= motor test =======================
    MOTOR_COUNT = {1: 4, 2: 6, 3: 8, 4: 8, 5: 6, 7: 3, 12: 12, 14: 10}

    def _motor_letters(self, frame_class, frame_type):
        if MotorDiagram.supported(frame_class, frame_type):
            return [m[0] for m in MotorDiagram.layout(frame_class, frame_type)]
        n = self.MOTOR_COUNT.get(int(frame_class), 4)
        return [chr(ord("A") + i) for i in range(n)]

    def _motors(self):
        w, v = page("Motor test", "Spins one motor at a time so you can check order and direction.")
        v.addWidget(callout("<b>Remove all propellers before testing.</b> Plug in the flight battery — motors do not "
                            "spin on USB power alone.", "danger"))
        row = QHBoxLayout()
        row.setSpacing(14)
        dc = Card("Expected layout")
        self.quad = MotorDiagram()
        dc.add(self.quad, 1)
        self.mt_frame_lbl = label("", "Faint", True)
        self.mt_frame_lbl.setTextFormat(Qt.RichText)
        dc.add(self.mt_frame_lbl)
        row.addWidget(dc, 1)
        cc = Card("Test")
        self.props_off = QCheckBox("I have removed all propellers")
        self.props_off.toggled.connect(self._props_toggled)
        cc.add(self.props_off)
        f = QFormLayout()
        self.mt_pct = QSpinBox()
        self.mt_pct.setRange(3, 30)
        self.mt_pct.setValue(8)
        self.mt_pct.setSuffix(" %")
        self.mt_sec = QDoubleSpinBox()
        self.mt_sec.setRange(0.5, 5)
        self.mt_sec.setValue(2)
        self.mt_sec.setSuffix(" s")
        f.addRow("Throttle", self.mt_pct)
        f.addRow("Duration", self.mt_sec)
        cc.add(f)
        self.mt_grid_w = QWidget()
        self.mt_grid = QGridLayout(self.mt_grid_w)
        self.mt_grid.setContentsMargins(0, 0, 0, 0)
        cc.add(self.mt_grid_w)
        self.mt_all = button("Test all in sequence", "primary", lambda: self._motor(1, None, count=len(self.mt_btns)))
        cc.add(self.mt_all)
        cc.lay.addStretch()
        row.addWidget(cc, 1)
        v.addLayout(row)
        v.addStretch()
        self.mt_btns = []
        self._mt_set_layout(1, 1)
        return w

    def _mt_set_layout(self, frame_class, frame_type):
        for b in self.mt_btns:
            self.mt_grid.removeWidget(b)
            b.deleteLater()
        self.mt_btns = []
        letters = self._motor_letters(frame_class, frame_type)
        for i, L in enumerate(letters):
            b = button(f"Motor {L}", None, lambda _=False, i=i, L=L: self._motor(i + 1, L))
            self.mt_grid.addWidget(b, i // 2, i % 2)
            self.mt_btns.append(b)
        self.quad.set_frame(frame_class, frame_type)
        if MotorDiagram.supported(frame_class, frame_type):
            self.mt_frame_lbl.setText(f"{MotorDiagram.NAMES[(int(frame_class), int(frame_type))]} · green = "
                                      "counter-clockwise, amber = clockwise, viewed from above. Letters are the "
                                      "test order (clockwise from the front); M-numbers are the outputs. If a motor "
                                      "spins the wrong way, fix it on <b>Motor direction</b>.")
        else:
            self.mt_frame_lbl.setText(f"This frame (class {frame_class}, type {frame_type}) has no diagram here. "
                                      "The test still runs motors A, B, C… in ArduPilot's test order: compare "
                                      "with the motor order diagram for your frame in the ArduPilot docs.")
        self._props_toggled(self.props_off.isChecked())

    def _props_toggled(self, on):
        for b in self.mt_btns + [self.mt_all]:
            b.setEnabled(on)

    def _motor(self, n, letter, count=0):
        if not self._need() or not self.props_off.isChecked():
            return
        if self.link.state.armed:
            QMessageBox.warning(self, "Armed", "Disarm before running a motor test.")
            return
        self.link.motor_test(n, self.mt_pct.value(), self.mt_sec.value(), count)
        self.quad.set_active(letter if not count else None)
        QTimer.singleShot(int(self.mt_sec.value() * 1000), lambda: self.quad.set_active(None))
        self.status(f"Motor test: {'all motors' if count else 'motor ' + letter} at {self.mt_pct.value()}%")

    # ======================= motor direction =======================
    # ArduPilot sends the DShot "reverse" command to every output in SERVO_BLH_RVMASK while disarmed.
    # It only does so when SERVO_DSHOT_ESC names a BLHeli-family ESC (BLHeli_S / Bluejay = 2).
    def _direction(self):
        w, v = page("Motor direction", "Spin each motor, compare it with the diagram, and tick “Reverse” for any "
                                       "that turn the wrong way. Works with DShot — no wire swapping.")
        v.addWidget(callout("<b>Remove all propellers.</b> Plug in the flight battery to spin motors.", "danger"))
        row = QHBoxLayout()
        row.setSpacing(14)
        dc = Card("Correct direction (viewed from above)")
        self.dir_quad = MotorDiagram()
        dc.add(self.dir_quad, 1)
        dc.add(label("Green = counter-clockwise, amber = clockwise.", "Faint", True))
        row.addWidget(dc, 1)

        cc = Card("Motors")
        self.dir_props = QCheckBox("I have removed all propellers")
        self.dir_props.toggled.connect(self._dir_props_toggled)
        cc.add(self.dir_props)
        self.dir_grid_w = QWidget()
        self.dir_grid = QGridLayout(self.dir_grid_w)
        self.dir_grid.setContentsMargins(0, 0, 0, 0)
        self.dir_grid.setHorizontalSpacing(12)
        self.dir_grid.setVerticalSpacing(10)
        cc.add(self.dir_grid_w)
        self.dir_unsupported = callout("", "warn")
        self.dir_unsupported.hide()
        cc.add(self.dir_unsupported)
        self.dir_state = label("", "Muted", True)
        self.dir_state.setTextFormat(Qt.RichText)
        cc.add(self.dir_state)
        r2 = QHBoxLayout()
        r2.addStretch()
        self.dir_write_btn = button("Write && reboot", "primary", self._dir_write)
        r2.addWidget(self.dir_write_btn)
        cc.add(r2)
        cc.lay.addStretch()
        row.addWidget(cc, 1)
        v.addLayout(row)
        v.addWidget(callout("How it works: ArduPilot tells the ESC to reverse the ticked motors every time it starts "
                            "(<code>SERVO_BLH_RVMASK</code>). Nothing is written into the ESC itself. "
                            "<b>After un-ticking a motor, unplug and replug the battery</b> — the ESC keeps the "
                            "reversed direction until it loses power."))
        v.addStretch()
        self.dir_rows, self.dir_spin_btns, self.dir_layout = {}, [], {}
        self._dir_set_layout(1, 1)
        return w

    def _dir_set_layout(self, frame_class, frame_type):
        """Motor letters are fixed by position; which output drives each depends on the frame."""
        while self.dir_grid.count():
            it = self.dir_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.dir_rows, self.dir_spin_btns, self.dir_layout = {}, [], {}
        ok = MotorDiagram.supported(frame_class, frame_type)
        self.dir_quad.set_frame(frame_class, frame_type)
        self.dir_grid_w.setVisible(ok)
        self.dir_write_btn.setEnabled(ok)
        self.dir_unsupported.setVisible(not ok)
        if not ok:
            self.dir_unsupported.setText(f"Frame class {frame_class}, type {frame_type} isn't drawn here, so FlightDeck "
                                         "can't tell which output is which motor. Set <code>SERVO_BLH_RVMASK</code> "
                                         "on the Params page using the ArduPilot motor order diagram.")
            return
        for col, h in enumerate(["Motor", "Should spin", "", "Fix"]):
            self.dir_grid.addWidget(label(h, "Faint"), 0, col)
        for r, (L, num, angle, ccw) in enumerate(MotorDiagram.layout(frame_class, frame_type), start=1):
            self.dir_layout[L] = (num, ccw)
            name_lbl = label(f"<b>{L}</b> · {MotorDiagram.position_name(angle)} · output {num}", None, True)
            name_lbl.setTextFormat(Qt.RichText)
            self.dir_grid.addWidget(name_lbl, r, 0)
            self.dir_grid.addWidget(label("↺ counter-clockwise" if ccw else "↻ clockwise"), r, 1)
            b = button("Spin", None, lambda _=False, i=r, L=L: self._dir_spin(i, L))
            self.dir_spin_btns.append(b)
            self.dir_grid.addWidget(b, r, 2)
            cb = QCheckBox("Reverse")
            self.dir_grid.addWidget(cb, r, 3)
            self.dir_rows[L] = cb
        rv = int(self._p("SERVO_BLH_RVMASK", 0) or 0)
        for L, cb in self.dir_rows.items():
            cb.setChecked(bool(rv & (1 << (self.dir_layout[L][0] - 1))))
        self._dir_props_toggled(self.dir_props.isChecked())

    def _dir_props_toggled(self, on):
        for b in self.dir_spin_btns:
            b.setEnabled(on)

    def _dir_spin(self, seq, letter):
        if not self._need() or not self.dir_props.isChecked():
            return
        if self.link.state.armed:
            QMessageBox.warning(self, "Armed", "Disarm before spinning motors.")
            return
        self.link.motor_test(seq, 8, 2.0)
        self.dir_quad.set_active(letter)
        QTimer.singleShot(2000, lambda: self.dir_quad.set_active(None))
        self.status(f"Spinning motor {letter} at 8% for 2 s — compare with the diagram")

    def _dir_write(self):
        if not self._need() or not self.dir_layout:
            return
        if self.link.state.armed:
            QMessageBox.warning(self, "Armed", "Disarm first.")
            return
        if int(self._p("MOT_PWM_TYPE", 0) or 0) < 4:
            QMessageBox.warning(self, "Not DShot", "Motor direction can only be set this way when the motors use "
                                                   "DShot (MOT_PWM_TYPE 4–7). Set DShot first.")
            return
        old = int(self._p("SERVO_BLH_RVMASK", 0) or 0)
        ours = sum(1 << (num - 1) for num, _ in self.dir_layout.values())
        mask = old & ~ours
        for L, cb in self.dir_rows.items():
            if cb.isChecked():
                mask |= 1 << (self.dir_layout[L][0] - 1)
        changes = {"SERVO_BLH_RVMASK": mask}
        if int(self._p("SERVO_DSHOT_ESC", 0) or 0) == 0:
            changes["SERVO_DSHOT_ESC"] = 2   # BLHeli_S / Bluejay — needed for the reverse command to be sent
        un_reversed = old & ~mask & ours
        self._reboot_after_write = True
        self.link.write_params(changes, job="setup")
        if un_reversed:
            QMessageBox.information(self, "Power-cycle the battery",
                                    "You un-reversed a motor. After the reboot, unplug and replug the flight "
                                    "battery so the ESC goes back to its normal direction.")

    # ======================= battery & failsafe =======================
    FS_FIELDS = [
        ("BATT_CAPACITY", "Pack capacity", "mAh", 0, 30000, 0),
        ("BATT_LOW_VOLT", "Low voltage", "V", 0, 60, 2),
        ("BATT_CRT_VOLT", "Critical voltage", "V", 0, 60, 2),
        ("BATT_ARM_VOLT", "Minimum voltage to arm", "V", 0, 60, 2),
    ]
    # (param, label, fallback options when there are no parameter descriptions). Rows the vehicle doesn't have
    # are hidden once parameters are loaded, so one list covers Copter, Plane, Rover and Sub.
    FS_COMBOS = [
        ("BATT_FS_LOW_ACT", "When low", {0: "Warn only", 1: "Land", 2: "Return home (RTL)", 3: "SmartRTL→RTL→Land"}),
        ("BATT_FS_CRT_ACT", "When critical", {0: "Warn only", 1: "Land", 2: "Return home (RTL)",
                                              3: "SmartRTL→RTL→Land"}),
        ("FS_THR_ENABLE", "Radio signal lost", {0: "Disabled", 1: "Return home (RTL)", 2: "Continue mission, else RTL",
                                                3: "Land", 4: "SmartRTL→RTL", 5: "SmartRTL→Land"}),
        ("THR_FAILSAFE", "Radio signal lost", {0: "Disabled", 1: "Enabled", 2: "Enabled, no failsafe action"}),
        ("FS_SHORT_ACTN", "Short failsafe action", {}),
        ("FS_LONG_ACTN", "Long failsafe action", {}),
        ("FS_ACTION", "Failsafe action", {}),
    ]

    def _options(self, name, fallback):
        vals = self.meta.get(name, {}).get("values") or fallback
        return [(int(k) if float(k).is_integer() else k, t) for k, t in vals.items()]

    def _failsafe(self):
        w, v = page("Battery & failsafe", f"What the {self.fw.vehicle} does when the battery runs low or the radio "
                                          "link drops.")
        self.batt_live = callout("Connect to see live battery readings.")
        v.addWidget(self.batt_live)
        c = Card("Battery")
        f = QFormLayout()
        f.setSpacing(10)
        self.fs_widgets, self.fs_rows = {}, {}
        for name, lab, unit, lo, hi, dec in self.FS_FIELDS:
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(dec)
            sp.setSuffix(f" {unit}")
            sp.setSingleStep(0.1 if dec else 100)
            f.addRow(lab, sp)
            self.fs_widgets[name] = sp
            self.fs_rows[name] = (f, sp)
        c.add(f)
        v.addWidget(c)
        c2 = Card("Failsafe actions")
        f2 = QFormLayout()
        f2.setSpacing(10)
        for name, lab, fallback in self.FS_COMBOS:
            opts = self._options(name, fallback)
            if not opts:
                continue
            cb = QComboBox()
            for k, n in opts:
                cb.addItem(n, k)
            f2.addRow(lab, cb)
            self.fs_widgets[name] = cb
            self.fs_rows[name] = (f2, cb)
        c2.add(f2)
        v.addWidget(c2)
        v.addWidget(callout("For a 4S LiPo, sensible values are low <b>14.0 V</b> (3.5 V/cell) and critical "
                            "<b>13.2 V</b> (3.3 V/cell). Returning home needs a GPS lock."))
        r = QHBoxLayout()
        r.addStretch()
        r.addWidget(button("Write", "primary", self._write_fs))
        v.addLayout(r)
        v.addStretch()
        return w

    def _write_fs(self):
        if not self._need():
            return
        ch = {}
        for name, wdg in self.fs_widgets.items():
            if name not in self.link.params:
                continue
            ch[name] = wdg.currentData() if isinstance(wdg, QComboBox) else wdg.value()
        self.link.write_params(ch, job="setup")

    # ======================= geofence =======================
    def _fence(self):
        from ..widgets import ParamForm
        w, v = page("Geofence", f"An invisible boundary around home. If the {self.fw.vehicle} goes outside it, the "
                                "breach action brings it back. The circle is drawn in red on the Fly map.")
        c = Card("Fence")
        rows = [("FENCE_ENABLE", "Fence", dict(self._options("FENCE_ENABLE", {0: "Off", 1: "On"}))),
                ("FENCE_TYPE", "Limits", dict(self._options("FENCE_TYPE", {
                    1: "Max altitude", 2: "Circle", 3: "Max altitude + circle", 7: "Altitude + circle + polygon"}))),
                ("FENCE_RADIUS", "Circle radius (m)", 0, 10),
                ("FENCE_ALT_MAX", "Max altitude (m)", 0, 5),
                ("FENCE_MARGIN", "Margin (m)", 1, 0.5),
                ("FENCE_ACTION", "When breached", dict(self._options("FENCE_ACTION", {
                    0: "Report only", 1: "RTL, else Land", 2: "Land"})))]
        c.add(ParamForm(self.link, rows, self.meta))
        v.addWidget(c)
        v.addWidget(callout("A sensible start for line-of-sight flying is a <b>150 m</b> circle, <b>60 m</b> max "
                            "altitude and <b>RTL</b> on breach. With the fence on, arming needs a GPS fix. "
                            "FENCE_TYPE is a bitmask: if the list doesn't show your combination, set it on the "
                            "Params page."))
        v.addStretch()
        return w

    # ======================= sync =======================
    def reload_params(self):
        P = self.link.params
        pg = self.pages
        if "Frame" in pg:
            for box, name in ((self.frame_class, "FRAME_CLASS"), (self.frame_type, "FRAME_TYPE")):
                if name in P:
                    i = box.findData(int(P[name]))
                    if i >= 0:
                        box.setCurrentIndex(i)
            self._frame_preview()
        if "Flight modes" in pg and self.fw.mode_switch:
            ch_param, slot_fmt, _ = self.fw.mode_switch
            if ch_param in P:
                i = self.fm_ch.findData(int(P[ch_param]))
                if i >= 0:
                    self.fm_ch.setCurrentIndex(i)
            for i, cb in enumerate(self.fm_boxes):
                n = P.get(slot_fmt.format(i + 1))
                if n is not None:
                    j = cb.findData(int(n))
                    if j >= 0:
                        cb.setCurrentIndex(j)
        if "Battery & failsafe" in pg:
            for name, wdg in self.fs_widgets.items():
                form, _ = self.fs_rows[name]
                if P:
                    form.setRowVisible(wdg, name in P)
                if name in P:
                    if isinstance(wdg, QComboBox):
                        j = wdg.findData(int(P[name]))
                        if j >= 0:
                            wdg.setCurrentIndex(j)
                    else:
                        wdg.setValue(P[name])
        if "Compass" in pg:
            comps = []
            for i, sfx in enumerate(["", "2", "3"]):
                dev = int(P.get(f"COMPASS_DEV_ID{sfx}", 0) or 0)
                if dev:
                    use = int(P.get(f"COMPASS_USE{sfx}", 1))
                    ext = "external" if (i == 0 and int(P.get("COMPASS_EXTERNAL", 0))) or (dev >> 3 & 0x1F) else ""
                    comps.append(f"Compass {i + 1}: id {dev}{' · ' + ext if ext else ''} · "
                                 f"{'<b>in use</b>' if use else 'not used'}")
            self.compass_info.setText("<br>".join(comps) if comps else "No compass detected.")
        if "Motor test" in pg or "Motor direction" in pg:
            fc, ft = int(P.get("FRAME_CLASS", 1) or 1), int(P.get("FRAME_TYPE", 1) or 0)
            if "Motor test" in pg:
                self._mt_set_layout(fc, ft)
            if "Motor direction" in pg:
                self._dir_set_layout(fc, ft)
                rv = int(P.get("SERVO_BLH_RVMASK", 0) or 0)
                esc = int(P.get("SERVO_DSHOT_ESC", 0) or 0)
                pwm = int(P.get("MOT_PWM_TYPE", 0) or 0)
                names = {4: "DShot150", 5: "DShot300", 6: "DShot600", 7: "DShot1200"}
                rev = [L for L, (n, _) in self.dir_layout.items() if rv & (1 << (n - 1))]
                esc_names = {0: "not set (will set to BLHeli_S/Bluejay)", 1: "BLHeli32/AM32", 2: "BLHeli_S/Bluejay",
                             3: "BLHeli32/AM32 EDT", 4: "BLHeli_S/Bluejay EDT"}
                self.dir_state.setText(
                    f"Protocol: <b>{names.get(pwm, 'not DShot')}</b> · ESC type: "
                    f"<b>{esc_names.get(esc, str(esc))}</b> · Reversed now: <b>{', '.join(rev) if rev else 'none'}</b>")

    def _statustext(self, sev, text):
        if "Accelerometer" not in self.pages:
            return
        low = text.lower()
        if "calibration successful" in low or "calibration failed" in low or "place vehicle" in low:
            self.acc_detail.setText(text)

    def tick(self):
        st = self.link.state
        if not st.connected:
            return
        cur = self._current()
        if cur == "Radio":
            if st.rc_count == 0:
                hint = ("Check the receiver is bound (solid LED) and wired to a flight controller UART"
                        + (", and that UART's <code>SERIALn_PROTOCOL</code> is 23 (RCIN)." if self.fw.family == "ardupilot"
                           else "."))
                self.rc_warn.setText(f"<b>No receiver data.</b> {hint}")
                self.rc_warn.show()
            else:
                self.rc_warn.hide()
            for i, b in enumerate(self.rc_bars):
                val = st.rc[i] if i < st.rc_count else 0
                if self._rc_cal and val:
                    lohi = self._rc_cal[i]
                    lohi[0], lohi[1] = min(lohi[0], val), max(lohi[1], val)
                    b.set(val, lohi[0], lohi[1])
                else:
                    b.set(val, int(self._p(f"RC{i + 1}_MIN", 0)) or None, int(self._p(f"RC{i + 1}_MAX", 0)) or None)
        elif cur == "Flight modes":
            ch = self.fm_ch.currentData()
            pwm = st.rc[ch - 1] if ch and st.rc_count >= ch else 0
            slot = None
            if pwm:
                bounds = [hi for _, hi in self.fm_ranges[:5]]
                slot = next((i for i, b in enumerate(bounds) if pwm <= b), 5)
                self.fm_pwm.setText(f"Channel {ch}: {pwm} µs → <b>{self.fm_boxes[slot].currentText()}</b>")
            else:
                self.fm_pwm.setText(f"Channel {ch}: no signal" if ch else "Mode switch not used")
            for i, m in enumerate(self.fm_marks):
                m.setStyleSheet("color:#2FBF71;" if i == slot else "color:#2A2A2F;")
            for sl in self.fm_sliders:
                sl.set_value(pwm)
        elif cur == "Battery & failsafe":
            cells = round(st.batt_v / 4.2) if st.batt_v > 5 else 0
            if cells:
                self.batt_live.setText(f"Live: <b>{st.batt_v:.2f} V</b> ({cells}S, {st.batt_v / cells:.2f} V/cell) · "
                                       f"{st.batt_a:.1f} A · {st.batt_mah:.0f} mAh used")
            else:
                self.batt_live.setText("No flight battery detected (running on USB).")
