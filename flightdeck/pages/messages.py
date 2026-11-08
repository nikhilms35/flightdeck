import time

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QTextEdit, QVBoxLayout, QWidget

from .. import theme
from ..theme import T
from ..widgets import button, label

SEV = {0: ("EMERG", "danger"), 1: ("ALERT", "danger"), 2: ("CRIT", "danger"), 3: ("ERROR", "danger"),
       4: ("WARN", "warn"), 5: ("NOTICE", "accent"), 6: ("INFO", "muted"), 7: ("DEBUG", "faint")}


class MessagesPage(QWidget):
    def __init__(self, link):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        h = QHBoxLayout()
        h.addWidget(label("Messages", "H1"))
        h.addStretch()
        h.addWidget(button("Clear", "ghost", lambda: self.log.clear()))
        v.addLayout(h)
        v.addWidget(label("Everything the flight controller reports, newest at the bottom.", "Muted"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(theme.mono(9))
        v.addWidget(self.log, 1)
        link.statustext.connect(self.add)
        link.connection_changed.connect(self._conn)

    def add(self, sev, text):
        name, kind = SEV.get(sev, ("?", "muted"))
        col = T.get(kind, T["muted"])
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"<span style='color:{T['faint']}'>{ts}</span>&nbsp;&nbsp;"
                        f"<span style='color:{col};font-weight:700'>{name:<6}</span>&nbsp;&nbsp;"
                        f"<span style='color:{T['text'] if sev <= 4 else T['muted']}'>{text}</span>")
        self.log.moveCursor(QTextCursor.End)

    def _conn(self, ok, msg):
        self.add(5 if ok else 4, f"— {msg} —")
