"""
bridge.py  --  the ADB bridge: the phone's own shell, reached over Wireless debugging.

WHY. An app on Android 14 or newer cannot kill another app, read /proc/stat, or see which
processes are in memory: killBackgroundProcesses() only touches the caller's own package now,
whatever it targets (developer.android.com, behavior-changes-14). The one way a person keeps
those rights on their own unrooted phone is the shell user, and the shell user is reachable from
Termux through adb over Wireless debugging (`pkg install android-tools`; Developer options ->
Wireless debugging -> pair). Paired, `adb shell` gives: dumpsys meminfo (every process with its
memory), ps -A, am force-stop, am kill-all, dumpsys battery, dumpsys thermalservice, the real
/proc/stat, and the two settings that lift Android's phantom-process limit.

Every call here is bounded (adb can sit forever on a device that went away) and every parser
takes text, so Test 1 covers them without a phone or a pairing. Unpaired is a normal state: every
function answers with None or an empty list, never raises, and the page says "pair the bridge".
"""
import os
import re
import shutil
import subprocess

PREFIX = "/data/data/com.termux/files/usr"
ADB_TIMEOUT = 12
PAIR_TIMEOUT = 30


def adb_path():
    return shutil.which("adb") or (os.path.join(PREFIX, "bin", "adb") if os.path.exists(os.path.join(PREFIX, "bin", "adb")) else None)


def run(args, timeout=None, adb=None):
    """(rc, text). 127 when adb is not installed, 124 on a timeout: both are answers, not faults.
    The deadline is read at call time, so a test (or a person) can shorten ADB_TIMEOUT."""
    timeout = timeout or ADB_TIMEOUT
    adb = adb or adb_path()
    if not adb:
        return 127, "adb is not installed: pkg install android-tools"
    try:
        p = subprocess.Popen([adb] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    except OSError as e:
        return 126, "adb could not run: %s" % e
    _children[p.pid] = p
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or ""
    except subprocess.TimeoutExpired:
        _kill_group(p)
        return 124, "adb did not answer in %ss" % timeout
    finally:
        _children.pop(p.pid, None)


# the same registry as probe.py's, for the same two reasons (a timed-out adb is killed as a group;
# stop_children() at exit leaves nothing behind)
_children = {}


def _kill_group(p):
    import signal
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        p.communicate(timeout=2)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def stop_children():
    n = 0
    for p in list(_children.values()):
        if p.poll() is None:
            _kill_group(p)
            n += 1
    _children.clear()
    return n


# ---------------------------------------------------------------- parsers
def parse_devices(text):
    """`adb devices -l` -> [{'serial': ..., 'state': 'device'|'offline'|'unauthorized'|...}]."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append({"serial": parts[0], "state": parts[1]})
    return out


def parse_meminfo_processes(text):
    """The 'Total PSS by process' block of `dumpsys meminfo`:
        123,456K: com.example (pid 1234 / activities)
    -> [{'pss_mb': 120, 'name': 'com.example', 'pid': 1234, 'note': 'activities'}], biggest first.
    Also the 'Total RAM' line when present."""
    procs, total_kb = [], None
    in_block = False
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("Total PSS by process"):
            in_block = True
            continue
        if in_block:
            if not s:
                in_block = False
                continue
            m = re.match(r"([\d,]+)K:\s+(\S+)\s+\(pid\s+(\d+)(?:\s*/\s*([^)]*))?\)", s)
            if m:
                procs.append({"pss_mb": int(m.group(1).replace(",", "")) // 1024, "name": m.group(2), "pid": int(m.group(3)), "note": (m.group(4) or "").strip()})
        m = re.match(r"Total RAM:\s*([\d,]+)K", s)
        if m:
            total_kb = int(m.group(1).replace(",", ""))
    procs.sort(key=lambda p: -p["pss_mb"])
    return {"processes": procs, "total_mb": total_kb // 1024 if total_kb else None}


def parse_battery(text):
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"\s*([A-Za-z ]+):\s*(-?\d+|true|false)\s*$", line)
        if m:
            k, v = m.group(1).strip().lower(), m.group(2)
            out[k] = (v == "true") if v in ("true", "false") else int(v)
    if "level" not in out:
        return None
    return {"pct": out.get("level"), "temp_c": (out.get("temperature") or 0) / 10, "status": {2: "charging", 3: "discharging", 4: "not charging", 5: "full"}.get(out.get("status"), "unknown"),
            "plugged": bool(out.get("ac powered") or out.get("usb powered") or out.get("wireless powered")), "voltage_mv": out.get("voltage")}


def parse_thermal(text):
    """`dumpsys thermalservice`: the status (0 none .. 6 shutdown) and the named temperatures."""
    status, temps = None, []
    for line in (text or "").splitlines():
        m = re.search(r"Thermal Status:\s*(\d+)", line)
        if m:
            status = int(m.group(1))
        m = re.search(r"Temperature\{mValue=([\d.\-]+), mType=(\d+), mName=([^,]+), mStatus=(\d+)\}", line)
        if m:
            temps.append({"name": m.group(3).strip(), "c": round(float(m.group(1)), 1), "status": int(m.group(4))})
    if status is None and not temps:
        return None
    names = {0: "none", 1: "light", 2: "moderate", 3: "severe", 4: "critical", 5: "emergency", 6: "shutdown"}
    return {"status": status, "status_name": names.get(status, "?"), "temps": temps}


def parse_proc_stat(text):
    """The first line of /proc/stat -> (busy_jiffies, total_jiffies), or None."""
    for line in (text or "").splitlines():
        if line.startswith("cpu "):
            nums = [int(x) for x in line.split()[1:] if x.isdigit()]
            if len(nums) >= 4:
                idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
                return sum(nums) - idle, sum(nums)
    return None


def cpu_from_stat(prev, now):
    """Two /proc/stat readings -> percent busy, or None."""
    if not prev or not now:
        return None
    db, dt = now[0] - prev[0], now[1] - prev[1]
    return round(100 * db / dt) if dt > 0 else None


def parse_top(text):
    """toybox `top -b -n 1`: the rows under the header, by column name -> [{'pid','cpu','res_mb','name'}]."""
    lines = (text or "").splitlines()
    hdr = None
    rows = []
    for line in lines:
        if hdr is None:
            if re.search(r"\bPID\b", line) and re.search(r"CPU", line):
                # toybox writes the state and the cpu column as one token, S[%CPU]; the rows have two
                hdr = line.replace("S[%CPU]", "S %CPU").split()
            continue
        parts = line.split()
        if len(parts) < len(hdr) - 1 or not parts[0].isdigit():
            continue
        row = dict(zip(hdr, parts))
        cpu = row.get("%CPU") or "0"
        res = row.get("RES") or "0"
        name = " ".join(parts[len(hdr) - 1:]) if len(parts) > len(hdr) - 1 else row.get("ARGS", "")
        rows.append({"pid": int(parts[0]), "cpu": float(cpu) if re.fullmatch(r"[\d.]+", cpu) else 0.0, "res_mb": _size_mb(res), "name": name})
    return rows


def _size_mb(s):
    m = re.fullmatch(r"([\d.]+)([KMG]?)", s or "")
    if not m:
        return 0
    v = float(m.group(1))
    return round({"K": v / 1024, "M": v, "G": v * 1024, "": v / 1024 / 1024}[m.group(2)])


# ---------------------------------------------------------------- the calls
def devices():
    rc, out = run(["devices", "-l"])
    return parse_devices(out) if rc == 0 else []


def state():
    """What the page shows in the bridge box."""
    adb = adb_path()
    if not adb:
        return {"installed": False, "paired": False, "serial": None, "note": "adb is not installed: pkg install android-tools"}
    devs = devices()
    live = [d for d in devs if d["state"] == "device"]
    if live:
        return {"installed": True, "paired": True, "serial": live[0]["serial"], "note": "the bridge is up: %s" % live[0]["serial"]}
    if devs:
        return {"installed": True, "paired": False, "serial": devs[0]["serial"], "note": "adb sees %s but it is %s" % (devs[0]["serial"], devs[0]["state"])}
    return {"installed": True, "paired": False, "serial": None, "note": "not connected: Developer options -> Wireless debugging, then pair and connect below"}


def pair(hostport, code):
    hostport, code = (hostport or "").strip(), (code or "").strip()
    if not re.fullmatch(r"[\w.\-\[\]:]+:\d{1,5}", hostport) or not re.fullmatch(r"\d{6}", code):
        return False, "pairing needs host:port and the six-digit code from the Wireless debugging screen"
    rc, out = run(["pair", hostport, code], timeout=PAIR_TIMEOUT)
    ok = rc == 0 and "Successfully paired" in out
    return ok, out.strip().splitlines()[-1] if out.strip() else ("paired" if ok else "pairing failed")


def connect(hostport):
    hostport = (hostport or "").strip()
    if not re.fullmatch(r"[\w.\-\[\]:]+:\d{1,5}", hostport):
        return False, "connect needs host:port from the Wireless debugging screen (the port changes on every enable)"
    rc, out = run(["connect", hostport], timeout=PAIR_TIMEOUT)
    ok = rc == 0 and ("connected to" in out or "already connected" in out)
    return ok, out.strip().splitlines()[-1] if out.strip() else ("connected" if ok else "connect failed")


def disconnect():
    rc, out = run(["disconnect"])
    return rc == 0, out.strip()


_serial_cache = {"at": 0.0, "serial": None}


def live_serial(max_age=5.0):
    """The first live device's serial, remembered for a few seconds: every shell() used to ask
    `adb devices` first, two process starts per command, and G6's soak timed out on it."""
    import time
    if time.time() - _serial_cache["at"] > max_age:
        st = state()
        _serial_cache.update(at=time.time(), serial=st.get("serial") if st.get("paired") else None)
    return _serial_cache["serial"]


def shell(cmd, timeout=None, serial=None):
    """(rc, text) of one command in the phone's shell. None serial: the first live device."""
    serial = serial or live_serial()
    if not serial:
        return 125, "the bridge is not connected"
    rc, out = run(["-s", serial, "shell", cmd], timeout=timeout or ADB_TIMEOUT)
    if rc != 0 and "not found" in out or rc == 124:
        _serial_cache["at"] = 0.0                            # ask again next time: the device may have gone
    return rc, out


def processes():
    rc, out = shell("dumpsys meminfo", timeout=25)
    return parse_meminfo_processes(out) if rc == 0 else None


def top():
    rc, out = shell("top -b -n 1 -m 20", timeout=15)
    return parse_top(out) if rc == 0 else None


def proc_stat():
    rc, out = shell("cat /proc/stat", timeout=6)
    return parse_proc_stat(out) if rc == 0 else None


def battery():
    rc, out = shell("dumpsys battery", timeout=8)
    return parse_battery(out) if rc == 0 else None


def thermal():
    rc, out = shell("dumpsys thermalservice", timeout=8)
    return parse_thermal(out) if rc == 0 else None


PKG_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+")


def force_stop(pkg):
    """`am force-stop`: the same as the Force stop button in App Info, and the only kill that
    means anything on Android 14 or newer. The package name is checked by shape before it is
    handed to a shell."""
    if not pkg or not PKG_RE.fullmatch(pkg):
        return False, "not a package name"
    rc, out = shell("am force-stop %s" % pkg, timeout=10)
    return rc == 0, (out.strip() or "stopped %s" % pkg)


def kill_all():
    """`am kill-all`: every background process, the way the system does it under pressure."""
    rc, out = shell("am kill-all", timeout=15)
    return rc == 0, (out.strip() or "every background process was told to go")


def phantom():
    """The two settings that decide whether Android kills an app with more than 32 child
    processes (Termux, and every Claude Code session in it, has hundreds)."""
    rc1, monitor = shell("settings get global settings_enable_monitor_phantom_procs", timeout=8)
    rc2, maxp = shell("device_config get activity_manager max_phantom_processes", timeout=8)
    if rc1 != 0 and rc2 != 0:
        return None
    monitor, maxp = monitor.strip(), maxp.strip()
    return {"monitor": monitor or "null", "max": maxp or "null",
            "lifted": monitor == "false" or (maxp.isdigit() and int(maxp) >= 1000000)}


def lift_phantom():
    """Termux's own recipe (wiki, Android 12+): stop the sync that would put the default back,
    raise the limit, switch the monitor off. Then read it back: a setting that was refused says
    nothing on the way in."""
    cmds = ["device_config set_sync_disabled_for_tests persistent",
            "device_config put activity_manager max_phantom_processes 2147483647",
            "settings put global settings_enable_monitor_phantom_procs false"]
    said = []
    for c in cmds:
        rc, out = shell(c, timeout=10)
        said.append("%s -> %s" % (c.split()[1], "ok" if rc == 0 else out.strip()[:80]))
    after = phantom()
    return bool(after and after["lifted"]), "; ".join(said)
