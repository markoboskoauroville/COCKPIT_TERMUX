"""Shared by the four tests: a Flask test client with the guard header, a pty around app.py
(KEYRING_TERMUX/tests/common.py's shape, copied 13.9.2026), a fake sysfs and /proc for the readers, a
fake adb on the PATH for the bridge."""
import fcntl
import os
import pty
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
PY = sys.executable
fails, count = [], 0


def check(label, ok, detail=""):
    global count
    count += 1
    print("  %s  %s%s" % ("ok  " if ok else "FAIL", label, ("  " + str(detail)[:400]) if detail and not ok else ""), flush=True)
    if not ok:
        fails.append(label)


def finish(name):
    print()
    print("%s: %d checks, %d failed" % (name, count, len(fails)))
    for f in fails:
        print("  - " + f)
    sys.exit(1 if fails else 0)


def fresh_home():
    d = tempfile.mkdtemp(prefix="cockpit-home-")
    os.environ["COCKPIT_HOME"] = d
    return d


def client(app_dir=APP):
    """The Flask test client, with the guard satisfied the way the page satisfies it."""
    sys.path.insert(0, app_dir)
    for m in ("app", "probe", "bridge", "localguard", "portpick", "version"):
        sys.modules.pop(m, None)
    import app as appmod
    appmod.app.config["TESTING"] = True
    c = appmod.app.test_client()
    H = {"Host": "127.0.0.1:%d" % appmod.LIVE_PORT, "X-Cockpit-Local": "1", "Origin": "http://127.0.0.1:%d" % appmod.LIVE_PORT}
    return appmod, c, H


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def strip_ansi(b):
    return re.sub(rb"\x1b\[[0-9;?]*[a-zA-Z]", b"", b).decode("utf-8", "replace")


def http(url, timeout=5, headers=None, data=None):
    try:
        req = urllib.request.Request(url, headers=headers or {}, data=data, method="POST" if data is not None else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310: http://127.0.0.1 only, the test's own server
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:                                  # noqa: BLE001
        return None, repr(e).encode()


def wait_port(port, seconds=12):
    end = time.time() + seconds
    while time.time() < end:
        st, _ = http("http://127.0.0.1:%d/health" % port, 2)
        if st == 200:
            return True
        time.sleep(0.2)
    return False


# ---------------------------------------------------------------- a fake phone
def fake_cpu_root(cores=4, idle_us=None, cur_mhz=1500, max_mhz=2000):
    """A sysfs tree the readers accept: N cores, two idle states each, one policy over all."""
    root = tempfile.mkdtemp(prefix="cockpit-sysfs-")
    with open(os.path.join(root, "online"), "w") as f:
        f.write("0-%d\n" % (cores - 1))
    for c in range(cores):
        for st in (0, 1):
            d = os.path.join(root, "cpu%d" % c, "cpuidle", "state%d" % st)
            os.makedirs(d)
            with open(os.path.join(d, "time"), "w") as f:
                f.write("%d\n" % ((idle_us or {}).get(c, 1000000) // 2))
            with open(os.path.join(d, "name"), "w") as f:
                f.write("WFI\n" if st == 0 else "off\n")
    pol = os.path.join(root, "cpufreq", "policy0")
    os.makedirs(pol)
    for name, val in (("scaling_cur_freq", cur_mhz * 1000), ("cpuinfo_max_freq", max_mhz * 1000), ("cpuinfo_min_freq", 400000)):
        with open(os.path.join(pol, name), "w") as f:
            f.write("%d\n" % val)
    with open(os.path.join(pol, "related_cpus"), "w") as f:
        f.write(" ".join(str(c) for c in range(cores)) + "\n")
    return root


def set_idle(root, cpu, us):
    """Put the whole idle time of a core in state0 (state1 stays); the readers sum both."""
    with open(os.path.join(root, "cpu%d" % cpu, "cpuidle", "state0", "time"), "w") as f:
        f.write("%d\n" % us)


MEMINFO = """MemTotal:        7590488 kB
MemFree:          202880 kB
MemAvailable:    1837916 kB
Buffers:            1208 kB
Cached:          2010144 kB
SwapCached:         4008 kB
SwapTotal:       4194300 kB
SwapFree:         557464 kB
Dirty:               276 kB
"""

DUMPSYS_MEMINFO = """Applications Memory Usage (in Kilobytes):
Uptime: 17486000 Realtime: 17486000

Total PSS by process:
    421,556K: com.android.systemui (pid 1832)
    318,004K: com.termux (pid 8030 / activities)
     97,120K: com.yahoo.mobile.client.android.weather (pid 21100)
     12,004K: com.termux:api (pid 7150)

Total PSS by OOM adjustment:
    900,000K: Native

Total RAM: 7,590,488K (status normal)
 Free RAM: 1,837,916K (  200,000K cached pss +  1,600,000K cached kernel +    37,916K free)
"""

DUMPSYS_BATTERY = """Current Battery Service state:
  AC powered: false
  USB powered: false
  Wireless powered: false
  Max charging current: 0
  status: 3
  health: 2
  present: true
  level: 61
  scale: 100
  voltage: 3944
  temperature: 350
  technology: Li-ion
"""

DUMPSYS_THERMAL = """IsStatusOverride: false
ThermalEventListeners:
Thermal Status: 1
Cached temperatures:
	Temperature{mValue=36.5, mType=3, mName=skin, mStatus=1}
	Temperature{mValue=41.2, mType=0, mName=cpu, mStatus=0}
"""


def fake_adb(behaviour="device", hang=False):
    """A stand-in `adb` on the PATH: answers `devices -l`, `shell` (with canned dumpsys output),
    `pair`, `connect`; records every call to calls.txt. `hang`: accepts and never answers."""
    d = tempfile.mkdtemp(prefix="cockpit-adb-")
    script = r'''#!/bin/sh
echo "$@" >> "%(d)s/calls.txt"
%(hang)s
case "$1" in
  devices) echo "List of devices attached"; %(dev)s ;;
  pair) case "$*" in *123456*) echo "Successfully paired to $2 [guid=adb-xyz]";; *) echo "Failed: wrong password"; exit 1;; esac ;;
  connect) echo "connected to $2" ;;
  disconnect) echo "disconnected everything" ;;
  -s) shift 2; case "$*" in
        *"dumpsys meminfo"*) cat "%(d)s/meminfo.txt" ;;
        *"dumpsys battery"*) cat "%(d)s/battery.txt" ;;
        *"dumpsys thermalservice"*) cat "%(d)s/thermal.txt" ;;
        *"cat /proc/stat"*) echo "cpu  $(cat "%(d)s/stat.txt")" ;;
        *"am force-stop"*) echo "" ;;
        *"am kill-all"*) echo "" ;;
        *"settings get global settings_enable_monitor_phantom_procs"*) cat "%(d)s/monitor.txt" ;;
        *"device_config get activity_manager max_phantom_processes"*) cat "%(d)s/maxp.txt" ;;
        *"device_config put"*) echo 2147483647 > "%(d)s/maxp.txt" ;;
        *"settings put"*) echo false > "%(d)s/monitor.txt" ;;
        *"top -b"*) printf '  PID USER   PR NI VIRT  RES  SHR S[%%%%CPU] %%%%MEM   TIME+ ARGS\n 1832 system 20  0 5.0G 400M  60M S  12.5  5.0  1:00.00 com.android.systemui\n 8030 u0_a245 20 0 1.0G 300M 50M S  3.0  4.0  0:10.00 com.termux\n' ;;
        *) echo "sh: unknown" ; exit 1 ;;
      esac ;;
  *) echo "unknown"; exit 1 ;;
esac
'''
    dev = {"device": 'echo "emulator-5554          device product:x model:y device:z transport_id:1"',
           "offline": 'echo "192.168.1.5:41234      offline transport_id:2"',
           "none": ":"}[behaviour]
    with open(os.path.join(d, "adb"), "w") as f:
        f.write(script % {"d": d, "dev": dev, "hang": "sleep 300" if hang else ":"})
    os.chmod(os.path.join(d, "adb"), 0o755)  # nosec B103: a stand-in command must be executable
    for name, txt in (("meminfo.txt", DUMPSYS_MEMINFO), ("battery.txt", DUMPSYS_BATTERY), ("thermal.txt", DUMPSYS_THERMAL),
                      ("stat.txt", "1000 0 500 8000 100 0 50 0 0 0"), ("monitor.txt", "null"), ("maxp.txt", "32")):
        with open(os.path.join(d, name), "w") as f:
            f.write(txt)
    return d


def adb_calls(d):
    try:
        return open(os.path.join(d, "calls.txt")).read().splitlines()
    except OSError:
        return []


class Console:
    """app.py on a real pty, in a fresh session (a harness pty is interactive: ENOTTY is not 'no tty')."""

    def __init__(self, app_dir=APP, port=None, env=None, home=None):
        import termios
        self.port = port or free_port()
        self.m, s = pty.openpty()
        fcntl.ioctl(s, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
        e = dict(os.environ, TERM="xterm-256color", PYTHONUNBUFFERED="1")
        if not (env and "PATH" in env):
            # a stand-in opener, so the auto-open at start is not a real Termux:API call (which costs
            # seconds and, under a harness, leaves a child behind); a test that wants its own stub passes PATH
            stub = tempfile.mkdtemp(prefix="cockpit-stub-")
            with open(os.path.join(stub, "termux-open-url"), "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(os.path.join(stub, "termux-open-url"), 0o755)  # nosec B103: a stand-in command must be executable
            e["PATH"] = stub + os.pathsep + e.get("PATH", "")
        if home:
            e["COCKPIT_HOME"] = home
        if env:
            e.update(env)
        self.p = subprocess.Popen([PY, os.path.join(app_dir, "app.py"), str(self.port)], stdin=s, stdout=s, stderr=s, env=e, close_fds=True, start_new_session=True)
        os.close(s)
        self.pgid = os.getpgid(self.p.pid)
        self.buf = b""

    def read(self, seconds=0.5):
        end = time.time() + seconds
        while time.time() < end:
            try:
                r, _, _ = select.select([self.m], [], [], 0.1)
            except (OSError, ValueError):
                break
            if r:
                try:
                    chunk = os.read(self.m, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self.buf += chunk
        return strip_ansi(self.buf)

    def wait_for(self, text, seconds=12):
        end = time.time() + seconds
        while time.time() < end:
            if text in self.read(0.3):
                return True
        return False

    def key(self, ch):
        os.write(self.m, ch.encode())

    def screen(self):
        return strip_ansi(self.buf)

    def alive(self):
        return self.p.poll() is None

    def wait_exit(self, seconds=8):
        end = time.time() + seconds
        while time.time() < end and self.p.poll() is None:
            self.read(0.2)
        return self.p.poll() is not None

    def kill(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if self.p.poll() is None:
                try:
                    os.killpg(self.pgid, sig)
                except OSError:
                    pass
                time.sleep(0.5)
        self.p.poll()
        try:
            os.close(self.m)
        except OSError:
            pass

    def left_behind(self):
        left = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/stat" % pid) as f:
                    st = f.read()
                pgrp = int(st[st.rindex(")") + 2:].split()[2])
            except (OSError, ValueError, IndexError):
                continue
            if pgrp == self.pgid and int(pid) != os.getpid():
                left.append(int(pid))
        return left
