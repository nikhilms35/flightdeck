import xml.etree.ElementTree as ET

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLineEdit, QMessageBox, QSplitter, QStyledItemDelegate, QTableView, QVBoxLayout,
                               QWidget)

from .. import theme
from ..theme import ASSETS, T
from ..widgets import Card, button, label


def load_metadata():
    meta = {}
    path = ASSETS / "ArduCopter.apm.pdef.xml"
    if not path.exists():
        return meta
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "param":
            continue
        name = el.get("name", "").split(":")[-1]
        d = dict(human=el.get("humanName", ""), doc=el.get("documentation", ""), units="", range="", values={})
        for fld in el.findall("field"):
            if fld.get("name") == "Units":
                d["units"] = fld.text or ""
            elif fld.get("name") == "Range":
                d["range"] = fld.text or ""
        vals = el.find("values")
        if vals is not None:
            for v in vals.findall("value"):
                try:
                    d["values"][float(v.get("code"))] = v.text or ""
                except (TypeError, ValueError):
                    pass
        meta.setdefault(name, d)
        el.clear()
    return meta


def fmt(v):
    if v == int(v) and abs(v) < 1e9:
        return str(int(v))
    return f"{v:.6g}"


class ParamModel(QAbstractTableModel):
    HEAD = ["Name", "Value", "Meaning / units", "Description"]

    def __init__(self, link, meta):
        super().__init__()
        self.link = link
        self.meta = meta
        self.names = []
        self.pending = {}
        self.only_changed = False
        self.mono = theme.mono(9)
        self.mono_b = theme.mono(9, True)

    def reset(self):
        self.beginResetModel()
        self.names = sorted(self.link.params)
        self.endResetModel()

    def update_one(self, name, _value):
        try:
            r = self.names.index(name)
        except ValueError:
            return
        self.dataChanged.emit(self.index(r, 1), self.index(r, 2))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.names)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, s, o, role=Qt.DisplayRole):
        if o == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEAD[s]
        return None

    def value(self, name):
        return self.pending.get(name, self.link.params.get(name, 0.0))

    def data(self, idx, role=Qt.DisplayRole):
        name = self.names[idx.row()]
        c = idx.column()
        m = self.meta.get(name, {})
        v = self.value(name)
        if role in (Qt.DisplayRole, Qt.EditRole):
            if c == 0:
                return name
            if c == 1:
                return fmt(v)
            if c == 2:
                if m.get("values"):
                    return m["values"].get(float(v), "?")
                return m.get("units", "")
            if c == 3:
                return m.get("human", "")
        if role == Qt.ToolTipRole:
            parts = [f"<b>{name}</b> — {m.get('human', '')}", m.get("doc", "")]
            if m.get("range"):
                parts.append(f"Range: {m['range']} {m.get('units', '')}")
            if m.get("values"):
                parts.append("<br>".join(f"{fmt(k)} = {t}" for k, t in sorted(m["values"].items())))
            return "<p style='max-width:420px'>" + "<br><br>".join(p for p in parts if p) + "</p>"
        if role == Qt.FontRole and c in (0, 1):
            return self.mono_b if name in self.pending else self.mono
        if role == Qt.ForegroundRole:
            if name in self.pending and c in (0, 1):
                return QColor(T["warn"])
            if c in (2, 3):
                return QColor(T["muted"])
        if role == Qt.UserRole:  # search text
            return f"{name} {m.get('human', '')} {m.get('doc', '')}"
        return None

    def flags(self, idx):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if idx.column() == 1:
            f |= Qt.ItemIsEditable
        return f

    def setData(self, idx, value, role=Qt.EditRole):
        if role != Qt.EditRole or idx.column() != 1:
            return False
        name = self.names[idx.row()]
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        if abs(v - self.link.params.get(name, 0.0)) < 1e-6:
            self.pending.pop(name, None)
        else:
            self.pending[name] = v
        self.dataChanged.emit(self.index(idx.row(), 0), self.index(idx.row(), 3))
        return True


class EnumDelegate(QStyledItemDelegate):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def _vals(self, idx):
        src = idx.model().mapToSource(idx)
        return self.model.meta.get(self.model.names[src.row()], {}).get("values")

    def createEditor(self, parent, option, idx):
        vals = self._vals(idx)
        if vals:
            cb = QComboBox(parent)
            for k, t in sorted(vals.items()):
                cb.addItem(f"{fmt(k)} · {t}", k)
            return cb
        ed = QLineEdit(parent)
        ed.setFont(theme.mono(9))
        return ed

    def setEditorData(self, ed, idx):
        if isinstance(ed, QComboBox):
            src = idx.model().mapToSource(idx)
            v = self.model.value(self.model.names[src.row()])
            j = ed.findData(float(v))
            if j >= 0:
                ed.setCurrentIndex(j)
        else:
            ed.setText(idx.data(Qt.EditRole))

    def setModelData(self, ed, model, idx):
        model.setData(idx, ed.currentData() if isinstance(ed, QComboBox) else ed.text(), Qt.EditRole)


class Filter(QSortFilterProxyModel):
    def __init__(self, src):
        super().__init__()
        self.src = src
        self.text = ""
        self.only_changed = False
        self.setSourceModel(src)

    def set(self, text=None, only_changed=None):
        if text is not None:
            self.text = text.lower().strip()
        if only_changed is not None:
            self.only_changed = only_changed
        self.invalidateFilter()

    def filterAcceptsRow(self, r, parent):
        name = self.src.names[r]
        if self.only_changed and name not in self.src.pending:
            return False
        if not self.text:
            return True
        return all(t in self.src.data(self.src.index(r, 0), Qt.UserRole).lower() for t in self.text.split())


class ParamsPage(QWidget):
    def __init__(self, link, status):
        super().__init__()
        self.link = link
        self.status = status
        self.meta = load_metadata()
        self.model = ParamModel(link, self.meta)
        self.proxy = Filter(self.model)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label("Parameters", "H1"))
        head.addStretch()
        self.count_lbl = label("", "Muted")
        head.addWidget(self.count_lbl)
        v.addLayout(head)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or description…  e.g.  batt volt,  serial3,  failsafe")
        self.search.textChanged.connect(lambda t: self.proxy.set(text=t))
        bar.addWidget(self.search, 1)
        self.only = QCheckBox("Changed only")
        self.only.toggled.connect(lambda on: self.proxy.set(only_changed=on))
        bar.addWidget(self.only)
        bar.addWidget(button("Refresh", "ghost", self._refresh))
        bar.addWidget(button("Load file…", None, self._load_file))
        bar.addWidget(button("Save file…", None, self._save_file))
        v.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(10)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setItemDelegateForColumn(1, EnumDelegate(self.model))
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                                   QAbstractItemView.AnyKeyPressed)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.resizeSection(0, 200)
        hh.resizeSection(1, 110)
        hh.resizeSection(2, 180)
        hh.setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self._show_doc)
        split.addWidget(self.table)

        self.doc = Card("Details")
        self.doc_name = label("", "H2")
        self.doc_name.setFont(theme.mono(12, True))
        self.doc_human = label("", None, True)
        self.doc_human.setStyleSheet("font-weight:600;")
        self.doc_text = label("Select a parameter to see what it does.", "Muted", True)
        self.doc_extra = label("", "Faint", True)
        self.doc_extra.setTextFormat(Qt.RichText)
        for w in (self.doc_name, self.doc_human, self.doc_text, self.doc_extra):
            self.doc.add(w)
        self.doc.lay.addStretch()
        self.doc.setMinimumWidth(280)
        split.addWidget(self.doc)
        split.setSizes([900, 340])
        split.setStretchFactor(0, 1)
        v.addWidget(split, 1)

        foot = QHBoxLayout()
        self.pending_lbl = label("", "Muted")
        foot.addWidget(self.pending_lbl)
        foot.addStretch()
        self.discard_btn = button("Discard changes", "ghost", self._discard)
        self.write_btn = button("Write changes", "primary", self._write)
        foot.addWidget(self.discard_btn)
        foot.addWidget(self.write_btn)
        v.addLayout(foot)

        link.params_loaded.connect(self._loaded)
        link.params_progress.connect(self._progress)
        link.param_changed.connect(self.model.update_one)
        link.job_status.connect(self._job)
        self.model.dataChanged.connect(self._update_pending)
        self.model.modelReset.connect(self._update_pending)
        self._update_pending()

    # ---------- events ----------
    def _progress(self, n, total):
        self.count_lbl.setText(f"Downloading {n}/{total}…" if total and n < total else "")

    def _loaded(self):
        self.model.reset()
        self.count_lbl.setText(f"{len(self.link.params)} parameters"
                               + (f" · descriptions for {sum(1 for n in self.link.params if n in self.meta)}"
                                  if self.meta else ""))

    def _job(self, job, msg):
        if job == "params":
            self.status(msg)
            if msg.startswith("Wrote"):
                self.model.pending = {k: v for k, v in self.model.pending.items()
                                      if abs(self.link.params.get(k, 1e99) - v) > 1e-4}
                self.model.reset()

    def _update_pending(self, *_):
        n = len(self.model.pending)
        self.pending_lbl.setText(f"{n} unsaved change{'s' if n != 1 else ''}" if n else "No unsaved changes")
        self.write_btn.setText(f"Write {n} change{'s' if n != 1 else ''}" if n else "Write changes")
        self.write_btn.setEnabled(bool(n))
        self.discard_btn.setEnabled(bool(n))

    def _show_doc(self, cur, _prev):
        if not cur.isValid():
            return
        name = self.model.names[self.proxy.mapToSource(cur).row()]
        m = self.meta.get(name, {})
        self.doc_name.setText(name)
        self.doc_human.setText(m.get("human", ""))
        self.doc_text.setText(m.get("doc", "No description available."))
        extra = []
        if m.get("range"):
            extra.append(f"<b>Range</b> {m['range']} {m.get('units', '')}")
        elif m.get("units"):
            extra.append(f"<b>Units</b> {m['units']}")
        if m.get("values"):
            extra.append("<b>Options</b><br>" + "<br>".join(f"{fmt(k)} — {t}" for k, t in sorted(m["values"].items())))
        self.doc_extra.setText("<br><br>".join(extra))

    # ---------- actions ----------
    def _refresh(self):
        if not self.link.state.connected:
            self.status("Not connected")
            return
        import threading
        threading.Thread(target=self.link.fetch_params, daemon=True).start()

    def _write(self):
        if not self.link.state.connected:
            self.status("Not connected")
            return
        p = dict(self.model.pending)
        names = ", ".join(list(p)[:6]) + ("…" if len(p) > 6 else "")
        if QMessageBox.question(self, "Write parameters?", f"Write {len(p)} parameter(s) to the drone?\n\n{names}") \
                != QMessageBox.Yes:
            return
        self.link.write_params(p, job="params")

    def _discard(self):
        self.model.pending.clear()
        self.model.reset()

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load parameters", "", "Parameter files (*.param *.parm *.txt)")
        if not path:
            return
        n_new, unknown = 0, []
        with open(path) as f:
            for ln in f:
                ln = ln.split("#")[0].strip()
                if not ln:
                    continue
                parts = ln.replace("\t", ",").replace(" ", ",").split(",")
                parts = [p for p in parts if p]
                if len(parts) < 2:
                    continue
                try:
                    name, v = parts[0], float(parts[1])
                except ValueError:
                    continue
                if self.link.params and name not in self.link.params:
                    unknown.append(name)
                    continue
                if abs(self.link.params.get(name, 1e99) - v) > 1e-6:
                    self.model.pending[name] = v
                    n_new += 1
        self.model.reset()
        self.only.setChecked(True)
        msg = f"Loaded {path}: {n_new} differ from the drone"
        if unknown:
            msg += f" · {len(unknown)} unknown (e.g. {', '.join(unknown[:3])}) — may appear after a reboot"
        self.status(msg)

    def _save_file(self):
        if not self.link.params:
            self.status("No parameters to save")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save parameters", "params.param", "Parameter files (*.param)")
        if not path:
            return
        with open(path, "w") as f:
            for k in sorted(self.link.params):
                f.write(f"{k},{fmt(self.link.params[k])}\n")
        self.status(f"Saved {len(self.link.params)} parameters to {path}")
