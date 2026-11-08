"""MAVLink connection: one reader thread owns all receiving; jobs run in their own
threads and get messages through subscriptions. UI reads `state` on a timer and
listens to signals for discrete events."""
import math
import os
import queue
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

os.environ.setdefault("MAVLINK20", "1")  # must be set before pymavlink loads its dialect
from pymavlink import mavutil  # noqa: E402

mavlink = mavutil.mavlink

COPTER_MODES = dict(mavutil.mode_mapping_acm)  # num -> name
COPTER_MODE_IDS = {v: k for k, v in COPTER_MODES.items()}

# commands sent by number so they work regardless of dialect enum availability
CMD_ACCELCAL_VEHICLE_POS = 42429
CMD_DO_START_MAG_CAL = 42424
CMD_DO_ACCEPT_MAG_CAL = 42425
CMD_DO_CANCEL_MAG_CAL = 42426

ACCEL_POSITIONS = {
    1: "Level", 2: "On its LEFT side", 3: "On its RIGHT side",
    4: "Nose DOWN", 5: "Nose UP", 6: "Upside down (on its back)",
    16777215: "Success", 16777216: "Failed",
}

SENSOR_BITS = {
    "Gyro": mavlink.MAV_SYS_STATUS_SENSOR_3D_GYRO,
    "Accel": mavlink.MAV_SYS_STATUS_SENSOR_3D_ACCEL,
    "Compass": mavlink.MAV_SYS_STATUS_SENSOR_3D_MAG,
    "Baro": mavlink.MAV_SYS_STATUS_SENSOR_ABSOLUTE_PRESSURE,
    "GPS": mavlink.MAV_SYS_STATUS_SENSOR_GPS,
    "RC": mavlink.MAV_SYS_STATUS_SENSOR_RC_RECEIVER,
    "Logging": mavlink.MAV_SYS_STATUS_LOGGING,
    "Battery": mavlink.MAV_SYS_STATUS_SENSOR_BATTERY,
}


@dataclass
class VehicleState:
    connected: bool = False
    last_heartbeat: float = 0.0
    armed: bool = False
    mode: str = "—"
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    alt_rel: float = 0.0
    alt_msl: float = 0.0
    groundspeed: float = 0.0
    climb: float = 0.0
    heading: int = 0
    throttle: int = 0
    lat: float | None = None
    lon: float | None = None
    gps_fix: int = 0
    sats: int = 0
    hdop: float = 99.99
    home_lat: float | None = None
    home_lon: float | None = None
    batt_v: float = 0.0
    batt_a: float = -1.0
    batt_pct: int = -1
    batt_mah: float = 0.0
    rc: list = field(default_factory=lambda: [0] * 16)
    rc_count: int = 0
    rc_rssi: int = 255
    sensors_present: int = 0
    sensors_health: int = 0
    vibe: tuple = (0.0, 0.0, 0.0)
    clipping: tuple = (0, 0, 0)
    servo: list = field(default_factory=lambda: [0] * 8)
    telem_rssi: int | None = None
    telem_remrssi: int | None = None
    prearm: dict = field(default_factory=dict)  # text -> last seen time

    def sensor(self, name):
        bit = SENSOR_BITS[name]
        return bool(self.sensors_present & bit), bool(self.sensors_health & bit)

    def dist_home(self):
        if None in (self.lat, self.lon, self.home_lat, self.home_lon):
            return None
        r = 6371000.0
        p1, p2 = math.radians(self.lat), math.radians(self.home_lat)
        dp = p2 - p1
        dl = math.radians(self.home_lon - self.lon)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))


class Link(QObject):
    connection_changed = Signal(bool, str)
    statustext = Signal(int, str)
    params_progress = Signal(int, int)
    params_loaded = Signal()
    param_changed = Signal(str, float)
    job_status = Signal(str, str)          # job, message
    mission_downloaded = Signal(list)
    accelcal_pos = Signal(int)
    magcal_progress = Signal(int, int)     # compass id, pct
    magcal_report = Signal(int, int, float)  # compass id, status, fitness
    command_ack = Signal(int, int)
    log_list = Signal(list)                 # [dict(id, size, time_utc)]
    log_progress = Signal(int, int, int)    # id, bytes received, total
    log_saved = Signal(int, str)            # id, path ('' on failure)

    def __init__(self):
        super().__init__()
        self.state = VehicleState()
        self.params: dict[str, float] = {}
        self.param_types: dict[str, int] = {}
        self.param_count = 0
        self._param_seen: set[int] = set()
        self._m = None
        self._thread = None
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self._subs: list[tuple[set, queue.Queue]] = []
        self._subs_lock = threading.Lock()
        self.port = None

    # ---------------- connection ----------------
    @property
    def is_open(self):
        return self._thread is not None and self._thread.is_alive()

    def connect_to(self, port, baud):
        self.disconnect()
        self.port = port
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(port, baud), daemon=True)
        self._thread.start()

    def disconnect(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        self._close()
        if self.state.connected:
            self.state.connected = False
        self.connection_changed.emit(False, "Disconnected")

    def _close(self):
        m, self._m = self._m, None
        if m:
            try:
                m.close()
            except Exception:
                pass

    def _open(self, port, baud):
        m = mavutil.mavlink_connection(port, baud=baud, source_system=255, source_component=190)
        deadline = time.time() + 12
        while not self._stop.is_set() and time.time() < deadline:
            hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
            if hb and hb.autopilot != mavlink.MAV_AUTOPILOT_INVALID and hb.type != mavlink.MAV_TYPE_GCS:
                m.target_system = hb.get_srcSystem()
                m.target_component = hb.get_srcComponent()
                return m, hb
        m.close()
        return None, None

    def _run(self, port, baud):
        first = True
        while not self._stop.is_set():
            self.connection_changed.emit(False, f"Connecting to {port}…" if first else "Reconnecting…")
            try:
                m, hb = self._open(port, baud)
            except Exception as e:
                m, hb = None, None
                self.connection_changed.emit(False, f"Cannot open {port}: {e}")
                self._stop.wait(2)
            if m is None:
                if not self._stop.is_set():
                    self.connection_changed.emit(False, "No heartbeat — retrying")
                    self._stop.wait(1)
                continue
            self._m = m
            self.state.connected = True
            self.state.last_heartbeat = time.time()
            self._handle(hb)
            self._request_streams()
            self.connection_changed.emit(True, f"Connected · {port}")
            if first or not self.params:
                threading.Thread(target=self.fetch_params, daemon=True).start()
            first = False
            last_gcs_hb = 0.0
            try:
                while not self._stop.is_set():
                    now = time.time()
                    if now - last_gcs_hb > 1:
                        with self._send_lock:
                            m.mav.heartbeat_send(mavlink.MAV_TYPE_GCS, mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
                        last_gcs_hb = now
                    msg = m.recv_match(blocking=True, timeout=0.3)
                    if msg is not None:
                        self._handle(msg)
                    if self.state.connected and now - self.state.last_heartbeat > 4:
                        self.state.connected = False
                        self.connection_changed.emit(False, "Link lost — waiting for heartbeat")
                    elif not self.state.connected and now - self.state.last_heartbeat < 2:
                        self.state.connected = True
                        self.connection_changed.emit(True, f"Connected · {port}")
            except Exception as e:  # serial unplugged etc.
                self.state.connected = False
                self.connection_changed.emit(False, f"Link error: {e}")
                self._close()
                self._stop.wait(1)
        self._close()

    def _request_streams(self):
        rates = {
            mavlink.MAV_DATA_STREAM_RAW_SENSORS: 2,
            mavlink.MAV_DATA_STREAM_EXTENDED_STATUS: 2,
            mavlink.MAV_DATA_STREAM_RC_CHANNELS: 5,
            mavlink.MAV_DATA_STREAM_POSITION: 4,
            mavlink.MAV_DATA_STREAM_EXTRA1: 15,
            mavlink.MAV_DATA_STREAM_EXTRA2: 5,
            mavlink.MAV_DATA_STREAM_EXTRA3: 2,
        }
        for sid, hz in rates.items():
            self._send(lambda m, s=sid, r=hz: m.mav.request_data_stream_send(
                m.target_system, m.target_component, s, r, 1))
        # ask for home position once
        self.command(mavlink.MAV_CMD_GET_HOME_POSITION)

    # ---------------- receiving ----------------
    def subscribe(self, types):
        q = queue.Queue()
        with self._subs_lock:
            self._subs.append((set(types), q))
        return q

    def unsubscribe(self, q):
        with self._subs_lock:
            self._subs = [s for s in self._subs if s[1] is not q]

    def _handle(self, msg):
        t = msg.get_type()
        if t == "BAD_DATA":
            return
        st = self.state
        m = self._m
        src_ok = m is None or msg.get_srcSystem() == m.target_system
        if t == "HEARTBEAT":
            if src_ok and msg.get_srcComponent() == (m.target_component if m else 1):
                st.last_heartbeat = time.time()
                st.armed = bool(msg.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                st.mode = COPTER_MODES.get(msg.custom_mode, f"MODE {msg.custom_mode}")
        elif t == "ATTITUDE":
            st.roll, st.pitch, st.yaw = msg.roll, msg.pitch, msg.yaw
        elif t == "VFR_HUD":
            st.groundspeed, st.climb, st.heading, st.throttle = msg.groundspeed, msg.climb, msg.heading, msg.throttle
            st.alt_msl = msg.alt
        elif t == "GLOBAL_POSITION_INT":
            st.alt_rel = msg.relative_alt / 1000.0
            if msg.lat or msg.lon:
                st.lat, st.lon = msg.lat / 1e7, msg.lon / 1e7
        elif t == "GPS_RAW_INT":
            st.gps_fix, st.sats = msg.fix_type, msg.satellites_visible
            st.hdop = msg.eph / 100.0 if msg.eph != 65535 else 99.99
            if st.lat is None and msg.fix_type >= 3:
                st.lat, st.lon = msg.lat / 1e7, msg.lon / 1e7
        elif t == "HOME_POSITION":
            st.home_lat, st.home_lon = msg.latitude / 1e7, msg.longitude / 1e7
        elif t == "SYS_STATUS":
            st.sensors_present = msg.onboard_control_sensors_present
            st.sensors_health = msg.onboard_control_sensors_health
            st.batt_v = msg.voltage_battery / 1000.0
            st.batt_a = msg.current_battery / 100.0 if msg.current_battery >= 0 else -1
            st.batt_pct = msg.battery_remaining
        elif t == "BATTERY_STATUS":
            if msg.id == 0 and msg.current_consumed >= 0:
                st.batt_mah = msg.current_consumed
        elif t == "RC_CHANNELS":
            st.rc = [getattr(msg, f"chan{i}_raw") for i in range(1, 17)]
            st.rc_count = msg.chancount
            st.rc_rssi = msg.rssi
        elif t == "SERVO_OUTPUT_RAW":
            st.servo = [getattr(msg, f"servo{i}_raw") for i in range(1, 9)]
        elif t == "VIBRATION":
            st.vibe = (msg.vibration_x, msg.vibration_y, msg.vibration_z)
            st.clipping = (msg.clipping_0, msg.clipping_1, msg.clipping_2)
        elif t == "RADIO_STATUS":
            st.telem_rssi, st.telem_remrssi = msg.rssi, msg.remrssi
        elif t == "STATUSTEXT":
            text = msg.text.strip()
            if text.startswith("PreArm:"):
                st.prearm[text[7:].strip()] = time.time()
            self.statustext.emit(msg.severity, text)
        elif t == "PARAM_VALUE":
            name = msg.param_id
            self.params[name] = msg.param_value
            self.param_types[name] = msg.param_type
            self.param_count = msg.param_count
            if msg.param_index < 65535:
                self._param_seen.add(msg.param_index)
            self.param_changed.emit(name, msg.param_value)
        elif t == "COMMAND_LONG" and msg.command == CMD_ACCELCAL_VEHICLE_POS:
            self.accelcal_pos.emit(int(msg.param1))
        elif t == "MAG_CAL_PROGRESS":
            self.magcal_progress.emit(msg.compass_id, msg.completion_pct)
        elif t == "MAG_CAL_REPORT":
            self.magcal_report.emit(msg.compass_id, msg.cal_status, msg.fitness)
        elif t == "COMMAND_ACK":
            self.command_ack.emit(msg.command, msg.result)

        with self._subs_lock:
            subs = list(self._subs)
        for types, q in subs:
            if t in types:
                q.put(msg)

    # ---------------- sending ----------------
    def _send(self, fn):
        m = self._m
        if m is None:
            return False
        with self._send_lock:
            fn(m)
        return True

    def command(self, cmd, *params):
        p = list(params) + [0] * (7 - len(params))
        return self._send(lambda m: m.mav.command_long_send(
            m.target_system, m.target_component, cmd, 0, *p))

    def set_mode(self, name):
        num = COPTER_MODE_IDS.get(name)
        if num is None:
            return False
        return self.command(mavlink.MAV_CMD_DO_SET_MODE, mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, num)

    def arm(self, arm=True, force=False):
        return self.command(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1 if arm else 0, 21196 if force else 0)

    def reboot(self):
        return self.command(mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN, 1)

    def set_param(self, name, value):
        ptype = self.param_types.get(name, mavlink.MAV_PARAM_TYPE_REAL32)
        return self._send(lambda m: m.mav.param_set_send(
            m.target_system, m.target_component, name.encode(), float(value), ptype))

    def set_param_verified(self, name, value, retries=3, timeout=1.5):
        """Blocking (call from a worker thread). Returns True if readback matches."""
        q = self.subscribe(["PARAM_VALUE"])
        try:
            for _ in range(retries):
                self.set_param(name, value)
                end = time.time() + timeout
                while time.time() < end:
                    try:
                        msg = q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if msg.param_id == name:
                        if abs(msg.param_value - float(value)) <= max(1e-4, abs(float(value)) * 1e-5):
                            return True
                        break
            return False
        finally:
            self.unsubscribe(q)

    def write_params(self, changes: dict, job="params"):
        """Run in background thread; reports via job_status."""
        def work():
            ok, bad = 0, []
            for i, (k, v) in enumerate(changes.items(), 1):
                self.job_status.emit(job, f"Writing {k} ({i}/{len(changes)})")
                if self.set_param_verified(k, v):
                    ok += 1
                else:
                    bad.append(k)
            msg = f"Wrote {ok}/{len(changes)} parameters"
            if bad:
                msg += " · failed: " + ", ".join(bad)
            self.job_status.emit(job, msg)
        threading.Thread(target=work, daemon=True).start()

    def fetch_params(self):
        q = self.subscribe(["PARAM_VALUE"])
        try:
            self._param_seen = set()
            self.param_count = 0
            self._send(lambda m: m.mav.param_request_list_send(m.target_system, m.target_component))
            last_n, last_change = -1, time.time()
            rounds = 0
            while not self._stop.is_set():
                try:
                    q.get(timeout=0.25)
                except queue.Empty:
                    pass
                n = len(self._param_seen)
                if n != last_n:
                    last_n, last_change = n, time.time()
                    self.params_progress.emit(n, self.param_count)
                if self.param_count and n >= self.param_count:
                    break
                if time.time() - last_change > 1.5:
                    if not self.param_count:
                        if rounds > 3:
                            break
                        self._send(lambda m: m.mav.param_request_list_send(m.target_system, m.target_component))
                    else:
                        missing = [i for i in range(self.param_count) if i not in self._param_seen]
                        if rounds > 8:
                            break
                        for i in missing[:40]:
                            self._send(lambda m, i=i: m.mav.param_request_read_send(
                                m.target_system, m.target_component, b"", i))
                    rounds += 1
                    last_change = time.time()
            self.params_progress.emit(len(self._param_seen), self.param_count)
            self.params_loaded.emit()
        finally:
            self.unsubscribe(q)

    # ---------------- missions ----------------
    def upload_mission(self, items):
        """items: list of dicts with cmd, lat, lon, alt, p1..p4 (seq 0 = home included)."""
        def work():
            q = self.subscribe(["MISSION_REQUEST", "MISSION_REQUEST_INT", "MISSION_ACK"])
            try:
                n = len(items)
                self._send(lambda m: m.mav.mission_count_send(m.target_system, m.target_component, n, 0))
                sent = set()
                tries = 0
                while tries < 6:
                    try:
                        msg = q.get(timeout=2.5)
                    except queue.Empty:
                        tries += 1
                        if not sent:
                            self._send(lambda m: m.mav.mission_count_send(m.target_system, m.target_component, n, 0))
                        continue
                    if msg.get_type() == "MISSION_ACK":
                        if msg.type == mavlink.MAV_MISSION_ACCEPTED:
                            self.job_status.emit("mission", f"Mission written · {n - 1} items")
                        else:
                            self.job_status.emit("mission", f"Mission rejected (code {msg.type})")
                        return
                    seq = msg.seq
                    if seq >= n:
                        continue
                    it = items[seq]
                    self._send(lambda m, s=seq, it=it: m.mav.mission_item_int_send(
                        m.target_system, m.target_component, s, mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
                        if s else mavlink.MAV_FRAME_GLOBAL_INT, it["cmd"], 0, 1,
                        it.get("p1", 0), it.get("p2", 0), it.get("p3", 0), it.get("p4", 0),
                        int(it["lat"] * 1e7), int(it["lon"] * 1e7), float(it["alt"]), 0))
                    sent.add(seq)
                    tries = 0
                    self.job_status.emit("mission", f"Sending item {seq}/{n - 1}")
                self.job_status.emit("mission", "Upload timed out")
            finally:
                self.unsubscribe(q)
        threading.Thread(target=work, daemon=True).start()

    def download_mission(self):
        def work():
            q = self.subscribe(["MISSION_COUNT", "MISSION_ITEM_INT"])
            try:
                count = None
                for _ in range(4):
                    self._send(lambda m: m.mav.mission_request_list_send(m.target_system, m.target_component, 0))
                    try:
                        while True:
                            msg = q.get(timeout=2)
                            if msg.get_type() == "MISSION_COUNT":
                                count = msg.count
                                break
                    except queue.Empty:
                        continue
                    break
                if count is None:
                    self.job_status.emit("mission", "No response to mission request")
                    return
                items = []
                for seq in range(count):
                    got = None
                    for _ in range(5):
                        self._send(lambda m, s=seq: m.mav.mission_request_int_send(
                            m.target_system, m.target_component, s, 0))
                        end = time.time() + 1.5
                        while time.time() < end:
                            try:
                                msg = q.get(timeout=0.3)
                            except queue.Empty:
                                continue
                            if msg.get_type() == "MISSION_ITEM_INT" and msg.seq == seq:
                                got = msg
                                break
                        if got:
                            break
                    if not got:
                        self.job_status.emit("mission", f"Timed out at item {seq}")
                        return
                    items.append(dict(cmd=got.command, lat=got.x / 1e7, lon=got.y / 1e7, alt=got.z,
                                      p1=got.param1, p2=got.param2, p3=got.param3, p4=got.param4))
                    self.job_status.emit("mission", f"Reading item {seq + 1}/{count}")
                self._send(lambda m: m.mav.mission_ack_send(m.target_system, m.target_component, 0, 0))
                self.mission_downloaded.emit(items)
                self.job_status.emit("mission", f"Read {max(0, count - 1)} items from vehicle")
            finally:
                self.unsubscribe(q)
        threading.Thread(target=work, daemon=True).start()

    # ---------------- calibration / tests ----------------
    def accel_cal_start(self):
        return self.command(mavlink.MAV_CMD_PREFLIGHT_CALIBRATION, 0, 0, 0, 0, 1, 0, 0)

    def accel_cal_confirm(self, pos):
        return self.command(CMD_ACCELCAL_VEHICLE_POS, pos)

    def level_cal(self):
        return self.command(mavlink.MAV_CMD_PREFLIGHT_CALIBRATION, 0, 0, 0, 0, 2, 0, 0)

    def mag_cal_start(self):
        # mask 0 = all, retry 1, autosave 1, delay 0, autoreboot 0
        return self.command(CMD_DO_START_MAG_CAL, 0, 1, 1, 0, 0)

    def mag_cal_cancel(self):
        return self.command(CMD_DO_CANCEL_MAG_CAL, 0)

    def motor_test(self, motor, pct, seconds, count=0):
        return self.command(mavlink.MAV_CMD_DO_MOTOR_TEST, motor,
                            mavlink.MOTOR_TEST_THROTTLE_PERCENT, pct, seconds, count, 0)

    # ---------------- guided / home ----------------
    def guided_goto(self, lat, lon, alt_rel):
        # position-only target (ignore velocity, accel, yaw)
        mask = 0b0000110111111000
        return self._send(lambda m: m.mav.set_position_target_global_int_send(
            0, m.target_system, m.target_component, mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, mask,
            int(lat * 1e7), int(lon * 1e7), float(alt_rel), 0, 0, 0, 0, 0, 0, 0, 0))

    def set_home(self, lat, lon, alt_msl):
        ok = self._send(lambda m: m.mav.command_int_send(
            m.target_system, m.target_component, mavlink.MAV_FRAME_GLOBAL, mavlink.MAV_CMD_DO_SET_HOME,
            0, 0, 0, 0, 0, 0, int(lat * 1e7), int(lon * 1e7), float(alt_msl)))
        threading.Timer(1.0, lambda: self.command(mavlink.MAV_CMD_GET_HOME_POSITION)).start()
        return ok

    # ---------------- onboard logs ----------------
    def list_logs(self):
        def work():
            q = self.subscribe(["LOG_ENTRY"])
            try:
                logs, total = {}, None
                self._send(lambda m: m.mav.log_request_list_send(m.target_system, m.target_component, 0, 0xFFFF))
                end = time.time() + 4
                while time.time() < end:
                    try:
                        e = q.get(timeout=0.3)
                    except queue.Empty:
                        continue
                    total = e.num_logs
                    if e.num_logs == 0:
                        break
                    logs[e.id] = dict(id=e.id, size=e.size, time_utc=e.time_utc)
                    end = time.time() + 1.5
                    if len(logs) >= total:
                        break
                self.log_list.emit(sorted(logs.values(), key=lambda d: d["id"]))
            finally:
                self.unsubscribe(q)
        threading.Thread(target=work, daemon=True).start()

    def download_log(self, log_id, size, path, cancel):
        CH = 90

        def work():
            q = self.subscribe(["LOG_DATA"])
            try:
                buf = bytearray(size)
                nchunks = (size + CH - 1) // CH
                got = set()
                self._send(lambda m: m.mav.log_request_data_send(m.target_system, m.target_component,
                                                                   log_id, 0, 0xFFFFFFFF))
                last_rx, rounds, last_emit = time.time(), 0, 0.0
                while not cancel.is_set() and len(got) < nchunks:
                    try:
                        d = q.get(timeout=0.3)
                    except queue.Empty:
                        d = None
                    if d is not None and d.id == log_id:
                        last_rx = time.time()
                        if d.count:
                            buf[d.ofs:d.ofs + d.count] = bytes(d.data[:d.count])
                            got.add(d.ofs // CH)
                        if time.time() - last_emit > 0.2:
                            last_emit = time.time()
                            self.log_progress.emit(log_id, min(len(got) * CH, size), size)
                        continue
                    if time.time() - last_rx > 1.0:
                        missing = [i for i in range(nchunks) if i not in got]
                        if not missing or rounds > 30:
                            break
                        rounds += 1
                        # re-request missing runs (coalesced)
                        runs, start, prev = [], missing[0], missing[0]
                        for i in missing[1:]:
                            if i != prev + 1:
                                runs.append((start, prev))
                                start = i
                            prev = i
                        runs.append((start, prev))
                        for a, b in runs[:20]:
                            self._send(lambda m, a=a, b=b: m.mav.log_request_data_send(
                                m.target_system, m.target_component, log_id, a * CH, (b - a + 1) * CH))
                        last_rx = time.time()
                self._send(lambda m: m.mav.log_request_end_send(m.target_system, m.target_component))
                if cancel.is_set() or len(got) < nchunks:
                    self.log_saved.emit(log_id, "")
                    return
                with open(path, "wb") as f:
                    f.write(buf)
                self.log_progress.emit(log_id, size, size)
                self.log_saved.emit(log_id, path)
            finally:
                self.unsubscribe(q)
        threading.Thread(target=work, daemon=True).start()

    def erase_logs(self):
        return self._send(lambda m: m.mav.log_erase_send(m.target_system, m.target_component))
