import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .theme import T


def set_kind(w, kind):
    if w.property("kind") != kind:
        w.setProperty("kind", kind)
        w.style().unpolish(w)
        w.style().polish(w)


def button(text, kind=None, slot=None):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    if kind:
        b.setProperty("kind", kind)
    if slot:
        b.clicked.connect(slot)
    return b


def label(text="", obj=None, wrap=False):
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


class Card(QFrame):
    def __init__(self, title=None, parent=None, spacing=10, margins=16):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(margins, margins - 2, margins, margins)
        self.lay.setSpacing(spacing)
        if title:
            self.lay.addWidget(label(title.upper(), "CardTitle"))

    def add(self, w, stretch=0):
        if isinstance(w, QWidget):
            self.lay.addWidget(w, stretch)
        else:
            self.lay.addLayout(w, stretch)
        return w


class Pill(QLabel):
    def __init__(self, text="", kind=None):
        super().__init__(text)
        self.setObjectName("Pill")
        self.setAlignment(Qt.AlignCenter)
        set_kind(self, kind)

    def set(self, text, kind=None):
        if self.text() != text:
            self.setText(text)
        set_kind(self, kind)


class Tile(QFrame):
    def __init__(self, title, unit="", big=20):
        super().__init__()
        self.setObjectName("Tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(2)
        lay.addWidget(label(title.upper(), "TileLabel"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.value = QLabel("—")
        self.value.setFont(theme.mono(big, bold=True))
        row.addWidget(self.value)
        self.unit = label(unit, "TileUnit")
        row.addWidget(self.unit, 0, Qt.AlignBottom)
        row.addStretch()
        lay.addLayout(row)
        self.sub = label("", "Faint")
        self.sub.hide()
        lay.addWidget(self.sub)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value, color=None, sub=None):
        self.value.setText(value)
        self.value.setStyleSheet(f"color:{color};" if color else "")
        if sub is not None:
            self.sub.setText(sub)
            self.sub.setVisible(bool(sub))


class HUD(QWidget):
    """Artificial horizon with pitch ladder, roll arc and heading tape."""

    def __init__(self):
        super().__init__()
        self.roll = self.pitch = 0.0
        self.heading = 0
        self.armed = False
        self.mode = ""
        self.setMinimumSize(320, 230)

    def set_attitude(self, roll, pitch, heading, armed, mode):
        self.roll, self.pitch, self.heading = math.degrees(roll), math.degrees(pitch), heading
        self.armed, self.mode = armed, mode
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 12, 12)
        p.setClipPath(clip)
        cx, cy = w / 2, h / 2 + 8
        ppd = h / 70.0  # pixels per degree of pitch

        # sky / ground, rotated by roll
        p.save()
        p.translate(cx, cy)
        p.rotate(-self.roll)
        off = self.pitch * ppd
        big = max(w, h) * 2
        sky = QLinearGradient(0, -big, 0, off)
        sky.setColorAt(0, QColor("#0F2440"))
        sky.setColorAt(1, QColor("#2D6198"))
        p.fillRect(QRectF(-big, -big + off, 2 * big, big), sky)
        gnd = QLinearGradient(0, off, 0, big)
        gnd.setColorAt(0, QColor("#5A4330"))
        gnd.setColorAt(1, QColor("#22190F"))
        p.fillRect(QRectF(-big, off, 2 * big, big), gnd)
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        p.drawLine(QPointF(-big, off), QPointF(big, off))

        # pitch ladder
        f = theme.mono(8)
        p.setFont(f)
        for deg in range(-40, 45, 5):
            if deg == 0:
                continue
            y = off - deg * ppd
            if abs(y) > h * 0.42:
                continue
            half = (w * 0.13) if deg % 10 == 0 else (w * 0.06)
            p.setPen(QPen(QColor(255, 255, 255, 200 if deg % 10 == 0 else 120), 1.4))
            p.drawLine(QPointF(-half, y), QPointF(half, y))
            if deg % 10 == 0:
                p.drawText(QPointF(half + 6, y + 4), f"{abs(deg)}")
                p.drawText(QPointF(-half - 22, y + 4), f"{abs(deg):>2}")
        p.restore()

        # roll arc
        r = min(w, h) * 0.40
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.5))
        p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), 30 * 16, 120 * 16)
        for a in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60):
            rad = math.radians(a - 90)
            l = 10 if a % 30 == 0 else 6
            p.drawLine(QPointF(cx + r * math.cos(rad), cy + r * math.sin(rad)),
                       QPointF(cx + (r + l) * math.cos(rad), cy + (r + l) * math.sin(rad)))
        p.save()
        p.translate(cx, cy)
        p.rotate(-self.roll)
        p.setBrush(QColor(T["warn"]))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(0, -r + 2), QPointF(-7, -r + 14), QPointF(7, -r + 14)]))
        p.restore()

        # aircraft symbol
        p.setPen(QPen(QColor(T["warn"]), 3.5, Qt.SolidLine, Qt.RoundCap))
        s = w * 0.11
        p.drawLine(QPointF(cx - s * 1.6, cy), QPointF(cx - s * 0.55, cy))
        p.drawLine(QPointF(cx - s * 0.55, cy), QPointF(cx - s * 0.25, cy + 9))
        p.drawLine(QPointF(cx - s * 0.25, cy + 9), QPointF(cx, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx + s * 0.25, cy + 9))
        p.drawLine(QPointF(cx + s * 0.25, cy + 9), QPointF(cx + s * 0.55, cy))
        p.drawLine(QPointF(cx + s * 0.55, cy), QPointF(cx + s * 1.6, cy))
        p.setBrush(QColor(T["warn"]))
        p.drawEllipse(QPointF(cx, cy), 2.5, 2.5)

        # heading tape (top)
        tape_h = 28
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(8, 12, 18, 190))
        p.drawRect(QRectF(0, 0, w, tape_h))
        p.setFont(theme.mono(8))
        pxd = w / 90.0
        for d in range(int(self.heading) - 50, int(self.heading) + 51):
            if d % 5:
                continue
            x = cx + (d - self.heading) * pxd
            dd = d % 360
            if dd % 10 == 0:
                p.setPen(QPen(QColor(255, 255, 255, 200), 1.2))
                p.drawLine(QPointF(x, tape_h - 8), QPointF(x, tape_h))
                txt = {0: "N", 90: "E", 180: "S", 270: "W"}.get(dd, f"{dd}" if dd % 30 == 0 else "")
                if txt:
                    p.drawText(QRectF(x - 20, 2, 40, 14), Qt.AlignCenter, txt)
            else:
                p.setPen(QPen(QColor(255, 255, 255, 110), 1))
                p.drawLine(QPointF(x, tape_h - 5), QPointF(x, tape_h))
        p.setBrush(QColor(T["accent"]))
        p.setPen(Qt.NoPen)
        box = QRectF(cx - 26, tape_h - 2, 52, 20)
        p.drawRoundedRect(box, 5, 5)
        p.setPen(QColor("white"))
        p.setFont(theme.mono(9, True))
        p.drawText(box, Qt.AlignCenter, f"{int(self.heading) % 360:03d}°")

        # armed / mode badge
        p.setFont(QFont(theme.UI_FONT, 9, QFont.Bold))
        text = "ARMED" if self.armed else "DISARMED"
        col = QColor(T["danger"]) if self.armed else QColor(T["ok"])
        br = QRectF(10, h - 30, 88, 22)
        p.setBrush(QColor(8, 12, 18, 200))
        p.setPen(QPen(col, 1.2))
        p.drawRoundedRect(br, 11, 11)
        p.setPen(col)
        p.drawText(br, Qt.AlignCenter, text)
        if self.mode:
            mr = QRectF(w - 118, h - 30, 108, 22)
            p.setPen(QPen(QColor(T["accent_hi"]), 1.2))
            p.drawRoundedRect(mr, 11, 11)
            p.setPen(QColor(T["accent_hi"]))
            p.drawText(mr, Qt.AlignCenter, self.mode)
        p.end()


class ChannelBar(QWidget):
    """Horizontal 800-2200us bar with optional min/max markers."""

    def __init__(self, name):
        super().__init__()
        self.name = name
        self.value = 0
        self.lo = self.hi = None
        self.setMinimumHeight(30)

    def set(self, value, lo=None, hi=None):
        self.value, self.lo, self.hi = value, lo, hi
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        name_w, val_w = 92, 58
        bar = QRectF(name_w, h / 2 - 6, w - name_w - val_w - 8, 12)
        p.setPen(QColor(T["muted"]))
        p.setFont(QFont(theme.UI_FONT, 9, QFont.DemiBold))
        p.drawText(QRectF(0, 0, name_w - 8, h), Qt.AlignVCenter | Qt.AlignLeft, self.name)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T["surface2"]))
        p.drawRoundedRect(bar, 6, 6)

        def x_of(us):
            return bar.left() + (min(max(us, 800), 2200) - 800) / 1400 * bar.width()

        if self.value:
            mid = x_of(1500)
            x = x_of(self.value)
            p.setBrush(QColor(T["accent"]))
            p.drawRoundedRect(QRectF(min(mid, x), bar.top(), max(abs(x - mid), 2), bar.height()), 5, 5)
        p.setPen(QPen(QColor(T["border_hi"]), 1))
        p.drawLine(QPointF(x_of(1500), bar.top() - 3), QPointF(x_of(1500), bar.bottom() + 3))
        if self.lo and self.hi:
            p.setPen(QPen(QColor(T["warn"]), 2))
            for us in (self.lo, self.hi):
                p.drawLine(QPointF(x_of(us), bar.top() - 4), QPointF(x_of(us), bar.bottom() + 4))
        p.setPen(QColor(T["text"] if self.value else T["faint"]))
        p.setFont(theme.mono(9, True))
        p.drawText(QRectF(w - val_w, 0, val_w, h), Qt.AlignVCenter | Qt.AlignRight,
                   str(self.value) if self.value else "—")
        p.end()


class ParamForm(QFrame):
    """Grid of editable parameters with live values, change highlighting and a Write button.
    rows: list of (PARAM, label, decimals, step) or (PARAM, label, {value: text}) for a dropdown."""

    def __init__(self, link, rows, meta=None, columns=1, write_label="Write"):
        from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QGridLayout
        super().__init__()
        self.link = link
        self.meta = meta or {}
        self.widgets = {}
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)
        per_col = (len(rows) + columns - 1) // columns
        for i, row in enumerate(rows):
            name, text = row[0], row[1]
            if isinstance(row[2], dict):
                w = QComboBox()
                for k, v in row[2].items():
                    w.addItem(v, k)
                w.currentIndexChanged.connect(self._changed)
            else:
                dec, step = row[2], row[3]
                w = QDoubleSpinBox()
                w.setDecimals(dec)
                w.setSingleStep(step)
                w.setRange(-1e6, 1e6)
                w.setFont(theme.mono(9))
                w.setMinimumWidth(100)
                w.valueChanged.connect(self._changed)
            m = self.meta.get(name, {})
            tip = f"<b>{name}</b><br>{m.get('doc', '')}" + (f"<br><br>Range: {m['range']}" if m.get("range") else "")
            lb = QLabel(text)
            lb.setToolTip(tip)
            w.setToolTip(tip)
            nm = QLabel(name)
            nm.setObjectName("Faint")
            nm.setFont(theme.mono(8))
            r, c = i % per_col, (i // per_col) * 3
            g.addWidget(lb, r, c)
            g.addWidget(w, r, c + 1)
            g.addWidget(nm, r, c + 2)
            self.widgets[name] = w
        lay.addLayout(g)
        foot = QHBoxLayout()
        self.info = QLabel("")
        self.info.setObjectName("Faint")
        foot.addWidget(self.info, 1)
        self.revert_btn = button("Revert", "ghost", self.load)
        self.write_btn = button(write_label, "primary", self.write)
        foot.addWidget(self.revert_btn)
        foot.addWidget(self.write_btn)
        lay.addLayout(foot)
        self.load()
        link.params_loaded.connect(self.load)
        link.job_status.connect(self._job)

    def _job(self, job, msg):
        if job == "form":
            self.info.setText(msg)
            if msg.startswith("Wrote"):
                self.load()
                self.info.setText(msg)

    def _value(self, w):
        from PySide6.QtWidgets import QComboBox
        return w.currentData() if isinstance(w, QComboBox) else w.value()

    def load(self):
        from PySide6.QtWidgets import QComboBox
        self._loading = True
        P = self.link.params
        for name, w in self.widgets.items():
            have = name in P
            w.setEnabled(have)
            if not have:
                continue
            if isinstance(w, QComboBox):
                j = w.findData(int(P[name]))
                if j < 0:
                    w.addItem(f"{P[name]:g} (other)", int(P[name]))
                    j = w.count() - 1
                w.setCurrentIndex(j)
            else:
                w.setValue(P[name])
            w.setStyleSheet("")
        self._loading = False
        self._changed()

    def changes(self):
        P = self.link.params
        out = {}
        for name, w in self.widgets.items():
            if name in P and abs(float(self._value(w)) - P[name]) > 1e-6:
                out[name] = float(self._value(w))
        return out

    def _changed(self, *_):
        if self._loading:
            return
        ch = self.changes()
        for name, w in self.widgets.items():
            w.setStyleSheet(f"color:{T['warn']};" if name in ch else "")
        missing = [n for n in self.widgets if n not in self.link.params]
        msg = f"{len(ch)} unsaved change{'s' if len(ch) != 1 else ''}" if ch else ""
        if missing and self.link.params:
            msg += ("  ·  " if msg else "") + f"{len(missing)} not available (feature disabled or needs reboot)"
        self.info.setText(msg)
        self.write_btn.setEnabled(bool(ch))
        self.revert_btn.setEnabled(bool(ch))

    def write(self):
        ch = self.changes()
        if ch and self.link.state.connected:
            self.link.write_params(ch, job="form")


class QuadXDiagram(QWidget):
    """Top-down quad X with ArduPilot motor-test letters and spin directions."""
    # (letter, motor/output number, x, y, ccw) — motor-test letters always go clockwise from front-right
    LAYOUTS = {
        1: [("A", 1, 1, -1, True), ("B", 4, 1, 1, False), ("C", 2, -1, 1, True), ("D", 3, -1, -1, False)],
        12: [("A", 2, 1, -1, True), ("B", 1, 1, 1, False), ("C", 3, -1, 1, True), ("D", 4, -1, -1, False)],
        18: [("A", 2, 1, -1, False), ("B", 1, 1, 1, True), ("C", 3, -1, 1, False), ("D", 4, -1, -1, True)],
    }
    MOTORS = LAYOUTS[1]

    @classmethod
    def layout(cls, frame_type):
        return cls.LAYOUTS.get(int(frame_type), cls.LAYOUTS[1])

    def __init__(self):
        super().__init__()
        self.active = None
        self.MOTORS = self.LAYOUTS[1]
        self.setMinimumSize(240, 240)

    def set_frame(self, frame_type):
        self.MOTORS = self.layout(frame_type)
        self.update()

    def set_active(self, letter):
        self.active = letter
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        s = min(w, h) * 0.30
        # deadcat-ish arms (front arms splayed wider)
        p.setPen(QPen(QColor(T["border_hi"]), 9, Qt.SolidLine, Qt.RoundCap))
        for _, _, x, y, _ in self.MOTORS:
            p.drawLine(QPointF(cx, cy), QPointF(cx + x * s, cy + y * s))
        p.setBrush(QColor(T["raised"]))
        p.setPen(QPen(QColor(T["border_hi"]), 1.5))
        p.drawRoundedRect(QRectF(cx - 22, cy - 30, 44, 60), 8, 8)
        # nose arrow
        p.setBrush(QColor(T["accent"]))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(cx, cy - 26), QPointF(cx - 8, cy - 12), QPointF(cx + 8, cy - 12)]))
        p.setPen(QColor(T["muted"]))
        p.setFont(QFont(theme.UI_FONT, 8, QFont.Bold))
        p.drawText(QRectF(cx - 40, 2, 80, 16), Qt.AlignCenter, "FRONT")
        for letter, num, x, y, ccw in self.MOTORS:
            mx, my = cx + x * s, cy + y * s
            r = s * 0.42
            on = self.active == letter
            p.setBrush(QColor(T["accent_soft"] if on else T["surface2"]))
            p.setPen(QPen(QColor(T["accent"] if on else T["border_hi"]), 2))
            p.drawEllipse(QPointF(mx, my), r, r)
            # spin direction arc + arrowhead
            col = QColor(T["ok"]) if ccw else QColor(T["warn"])
            p.setPen(QPen(col, 2.2, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            ar = r * 0.78
            p.drawArc(QRectF(mx - ar, my - ar, 2 * ar, 2 * ar), 30 * 16, 240 * 16 if ccw else -240 * 16)
            end_deg = 30 + (240 if ccw else -240)
            ea = math.radians(end_deg)
            ex, ey = mx + ar * math.cos(ea), my - ar * math.sin(ea)
            tang = ea + (math.pi / 2 if ccw else -math.pi / 2)
            tx, ty = math.cos(tang), -math.sin(tang)
            nx, ny = -ty, tx
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(ex + tx * 7, ey + ty * 7), QPointF(ex + nx * 5, ey + ny * 5),
                                     QPointF(ex - nx * 5, ey - ny * 5)]))
            p.setPen(QColor(T["text"]))
            p.setFont(QFont(theme.UI_FONT, 13, QFont.Bold))
            p.drawText(QRectF(mx - r, my - r, 2 * r, 2 * r - 8), Qt.AlignCenter, letter)
            p.setFont(QFont(theme.UI_FONT, 7))
            p.setPen(QColor(T["muted"]))
            p.drawText(QRectF(mx - r, my + 2, 2 * r, r - 2), Qt.AlignCenter,
                       f"M{num} · {'CCW' if ccw else 'CW'}")
        p.end()
