"""Claude chat inside FlightDeck.

Runs the locally installed Claude Code CLI (`claude -p`) with the user's existing login, streams the reply,
and keeps one conversation going with --resume. Each question carries a snapshot of the live vehicle state,
and the full parameter list is written to a file Claude can read. Claude gets read-only tools only:
it can look at FlightDeck's code, logs and the parameter dump, but it cannot command the vehicle.
"""
import json
import os
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QTextBrowser, QVBoxLayout, QWidget

from ..widgets import Pill, button, label

PROJECT = Path(__file__).resolve().parents[1]   # the flightdeck package (works for git checkouts and pip installs)
CACHE = Path.home() / ".cache" / "flightdeck"
TOOLS = "Read,Grep,Glob"

SYSTEM = (
    "You are running inside FlightDeck, a desktop ground control station for ArduPilot ArduCopter written in "
    "Python/PySide6. The user is a hobby drone builder talking to you from the app's Claude tab. "
    "Each message starts with a [Vehicle snapshot] block taken at the moment they pressed Send; treat it as live "
    "telemetry. The full parameter list (NAME = value) is in the file named in the snapshot; read it when a "
    "question depends on parameters. FlightDeck's source code is in the working directory. "
    "You have read-only tools and cannot send commands to the vehicle: when something needs changing, tell the "
    "user exactly which page or parameter to change in FlightDeck. Keep answers short and practical, and put "
    "safety first: props off for bench tests, never advise changes while armed."
)


def find_claude():
    home = Path.home()
    for c in (shutil.which("claude"), home / ".local/bin/claude", home / ".local/bin/claude.exe",
              home / ".claude/local/claude", home / ".claude/local/claude.exe"):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


class ClaudePage(QWidget):
    def __init__(self, link):
        super().__init__()
        self.link = link
        self.exe = find_claude()
        self.proc = None
        self.session = None
        self.turns = []          # [role, text]
        self._buf = b""
        self._dirty = False

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        h = QHBoxLayout()
        h.addWidget(label("Claude", "H1"))
        h.addSpacing(8)
        self.state_pill = Pill("READY")
        h.addWidget(self.state_pill)
        h.addStretch()
        h.addWidget(button("New chat", "ghost", self.new_chat))
        v.addLayout(h)
        v.addWidget(label("Ask about your drone, parameters, logs or FlightDeck itself. Claude sees a live snapshot "
                          "of the vehicle and can read the parameter list, but it cannot fly or change anything.",
                          "Muted", True))

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.document().setDocumentMargin(14)
        v.addWidget(self.view, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("e.g.  Why won't it arm?   ·   Are my battery failsafes sensible for 4S?   "
                                      "(Ctrl+Enter to send)")
        self.input.setFixedHeight(72)
        row.addWidget(self.input, 1)
        col = QVBoxLayout()
        self.send_btn = button("Send", "primary", self.send)
        self.stop_btn = button("Stop", "danger", self.stop)
        self.stop_btn.hide()
        col.addWidget(self.send_btn)
        col.addWidget(self.stop_btn)
        col.addStretch()
        row.addLayout(col)
        v.addLayout(row)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self.input, activated=self.send)

        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_if_dirty)
        self._render_timer.start(120)

        if not self.exe:
            self.turns.append(["note", "The `claude` command was not found. Install Claude Code "
                                       "(https://claude.com/claude-code) and log in once in a terminal, then restart "
                                       "FlightDeck."])
            self.send_btn.setEnabled(False)
        self._render()

    # ---------------- context ----------------
    def _snapshot(self):
        st, P = self.link.state, self.link.params
        if not st.connected:
            return "[Vehicle snapshot]\nNot connected to a flight controller.\n[/Vehicle snapshot]\n\n"
        CACHE.mkdir(parents=True, exist_ok=True)
        pfile = CACHE / "params.txt"
        if P:
            pfile.write_text("\n".join(f"{k} = {P[k]:g}" for k in sorted(P)) + "\n")
        fix = {0: "none", 1: "none", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK float", 6: "RTK fixed"}.get(st.gps_fix, st.gps_fix)
        cells = round(st.batt_v / 4.2) if st.batt_v > 5 else 0
        batt = (f"{st.batt_v:.2f} V ({cells}S, {st.batt_v / cells:.2f} V/cell), {st.batt_a:.1f} A, "
                f"{st.batt_mah:.0f} mAh used" if cells else "no flight battery (USB power)")
        recent = [t for t, ts in st.prearm.items() if time.time() - ts < 30]
        lines = [
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Mode: {st.mode} · {'ARMED' if st.armed else 'disarmed'}",
            f"Attitude: roll {st.roll:.1f}°, pitch {st.pitch:.1f}°, heading {st.heading}°",
            f"Altitude: {st.alt_rel:.1f} m rel · climb {st.climb:+.1f} m/s · groundspeed {st.groundspeed:.1f} m/s",
            f"GPS: fix {fix}, {st.sats} sats, HDOP {st.hdop:.2f}",
            f"Battery: {batt}",
            f"RC: {st.rc_count} channels" + (f", RSSI {st.rc_rssi}" if st.rc_rssi != 255 else "")
            + (f", ch1-8 {st.rc[:8]}" if st.rc_count else ""),
            f"Vibration (m/s²): x {st.vibe[0]:.1f}, y {st.vibe[1]:.1f}, z {st.vibe[2]:.1f} · clipping {st.clipping}",
            "Pre-arm messages (last 30 s): " + ("; ".join(recent) if recent else "none"),
            f"Parameters: {len(P)} loaded" + (f", full list in {pfile}" if P else " (not downloaded yet)"),
        ]
        return "[Vehicle snapshot]\n" + "\n".join(lines) + "\n[/Vehicle snapshot]\n\n"

    # ---------------- running ----------------
    def send(self):
        text = self.input.toPlainText().strip()
        if not text or not self.exe or self.proc:
            return
        self.input.clear()
        self.turns.append(["you", text])
        self.turns.append(["claude", ""])
        self._render()

        args = ["-p", self._snapshot() + text, "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--append-system-prompt", SYSTEM, "--allowedTools", TOOLS]
        if self.session:
            args += ["--resume", self.session]
        self.proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
            env.remove(k)   # FlightDeck may have been started from inside a Claude Code session
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(str(PROJECT))
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._error)
        self._buf, self._stderr = b"", b""
        self.proc.readyReadStandardError.connect(lambda: setattr(self, "_stderr",
                                                                 self._stderr + bytes(self.proc.readAllStandardError())))
        self.proc.start(self.exe, args)
        self.proc.closeWriteChannel()
        self._busy(True)

    def stop(self):
        if self.proc:
            self.proc.kill()

    def new_chat(self):
        self.stop()
        self.session = None
        self.turns = []
        self._render()

    def _busy(self, on):
        self.send_btn.setVisible(not on)
        self.stop_btn.setVisible(on)
        self.state_pill.set("THINKING…" if on else "READY", "accent" if on else None)

    def _append(self, text):
        self.turns[-1][1] += text
        self._dirty = True

    def _read(self):
        self._buf += bytes(self.proc.readAllStandardOutput())
        *lines, self._buf = self._buf.split(b"\n")
        for ln in lines:
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            t = ev.get("type")
            if ev.get("session_id"):
                self.session = ev["session_id"]
            if t == "stream_event":
                e = ev.get("event", {})
                d = e.get("delta", {})
                if e.get("type") == "content_block_delta" and d.get("type") == "text_delta":
                    self._append(d.get("text", ""))
                elif e.get("type") == "content_block_start" and self.turns[-1][1] \
                        and e.get("content_block", {}).get("type") == "text":
                    self._append("\n\n")
            elif t == "assistant":
                for blk in ev.get("message", {}).get("content", []):
                    if blk.get("type") == "tool_use":
                        inp = blk.get("input", {})
                        what = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
                        what = what.replace(str(PROJECT) + "/", "").replace(str(Path.home()), "~")
                        what = what.replace("`", "'")[:120]
                        self._append(f"\n\n`↳ {blk.get('name')} {what}`\n\n")
            elif t == "result" and ev.get("is_error") and not self.turns[-1][1].strip():
                self._append(f"**Error:** {ev.get('result') or ev.get('subtype')}")

    def _done(self, code, _status):
        if self.proc is None:
            return
        if not self.turns[-1][1].strip():
            err = self._stderr.decode(errors="replace").strip()[-600:]
            self.turns[-1][1] = ("*Stopped.*" if code != 0 and not err else
                                 f"**Claude didn't answer** (exit {code}).\n\n```\n{err or 'no output'}\n```\n\n"
                                 "If it says you're not logged in, run `claude` once in a terminal and sign in.")
        self.proc.deleteLater()
        self.proc = None
        self._busy(False)
        self._render()

    def _error(self, err):
        if err == QProcess.FailedToStart:
            self._append(f"**Could not start** `{self.exe}`.")
            self.proc = None
            self._busy(False)
            self._render()

    # ---------------- view ----------------
    def _render_if_dirty(self):
        if self._dirty:
            self._render()

    def _render(self):
        self._dirty = False
        if not self.turns:
            md = ("### Hi — I'm Claude, inside FlightDeck.\n\nConnect the drone first if you want me to look at it. "
                  "Some things to try:\n\n- *Why won't it arm?*\n- *Check my failsafe settings.*\n"
                  "- *Is my vibration OK?*\n- *Explain what LOITER needs to work.*")
        else:
            parts = []
            for role, text in self.turns:
                if role == "you":
                    parts.append("**You**\n\n" + text)
                elif role == "claude":
                    body = "\n\n".join(b.strip() for b in text.split("\n\n") if b.strip())
                    parts.append("**Claude**\n\n" + (body or "*…*"))
                else:
                    parts.append("> " + text)
            md = "\n\n---\n\n".join(parts)
        sb = self.view.verticalScrollBar()
        at_end = sb.value() >= sb.maximum() - 30
        self.view.setMarkdown(md)
        if at_end:
            self.view.moveCursor(QTextCursor.End)
            sb.setValue(sb.maximum())
