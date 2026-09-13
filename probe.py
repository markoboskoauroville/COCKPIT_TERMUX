"""
probe.py  --  what the phone says about itself, read from the files an app is allowed to read.

Measured on this phone (Nothing Phone (2a), Android 16, 13.9.2026, from Termux's own shell, NOT
from inside the PRoot, whose /proc is partly fake):

    DENIED    /proc/stat  /proc/loadavg  /proc/uptime  /proc/vmstat  /proc/pressure/*  /proc/<pid>
              of anyone else, /sys/class/thermal, /sys/class/power_supply
    READABLE  /proc/meminfo, /proc/cpuinfo, /proc/self/*, and all of /sys/devices/system/cpu:
              cpuidle/state*/time (microseconds each core spent asleep), cpufreq scaling_cur_freq,
              cpuinfo_max_freq, stats/time_in_state

So CPU load is NOT /proc/stat here. It is the idle counters: a core that spent 1.8 of the last 2
seconds in an idle state was 10 % busy. That is the same arithmetic /proc/stat would give, from
the other side of the ledger, and it is what the status-bar number is made of. The ADB bridge
(bridge.py) reads the real /proc/stat with the shell's rights when it is paired; then both
numbers are shown and they agree to within a point or two.

Every reader here takes the file text as an argument where it can, so Test 1 attacks the parsers
without a phone, and every reader that touches the system returns None or {} rather than raising:
a cockpit that dies on the one file this phone hides is a cockpit that is not there.
"""
import json
import os
import re
import shutil
import subprocess
import time

CPU_ROOT = "/sys/devices/system/cpu"
MEMINFO = "/proc/meminfo"
PREFIX = "/data/data/com.termux/files/usr"
API_TIMEOUT = 8            # a Termux:API call is a round trip to another app: seconds, never forever


def read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def read_int(path):
    t = read(path)
    if t is None:
        return None
    t = t.strip()
    return int(t) if t.isdigit() else None


# ---------------------------------------------------------------- the cores
def parse_cpu_list(text):
    """'0-7' -> [0..7]; '0-3,6-7' -> [0,1,2,3,6,7]; '0 1 2' (related_cpus) -> [0,1,2]; garbage -> []."""
    out = []
    for part in re.split(r"[,\s]+", (text or "").strip()):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            if a.strip().isdigit() and b.strip().isdigit() and int(a) <= int(b):
                out.extend(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.append(int(part))
    return sorted(set(out))


def cpus(root=CPU_ROOT):
    lst = parse_cpu_list(read(os.path.join(root, "online")) or "")
    if lst:
        return lst
    return sorted(int(n[3:]) for n in os.listdir(root) if re.fullmatch(r"cpu\d+", n)) if os.path.isdir(root) else []


def idle_us(cpu, root=CPU_ROOT):
    """Microseconds this core has spent in ANY idle state since boot, or None when unreadable."""
    d = os.path.join(root, "cpu%d" % cpu, "cpuidle")
    if not os.path.isdir(d):
        return None
    total, seen = 0, False
    for n in os.listdir(d):
        if re.fullmatch(r"state\d+", n):
            v = read_int(os.path.join(d, n, "time"))
            if v is not None:
                total += v
                seen = True
    return total if seen else None


def cpu_sample(root=CPU_ROOT):
    """One reading: the clock and every core's idle counter."""
    return {"t": time.monotonic(), "idle": {c: idle_us(c, root) for c in cpus(root)}}


def cpu_busy(prev, now):
    """Two samples -> {'pct': 0..100 overall, 'per_core': [..], 'cores': n}. The busy fraction of a
    core is 1 - (idle it gained / wall time that passed). Clamped: a counter can run a little
    ahead of the wall clock at the edges of a tick, and 103 % is not a number to show."""
    if not prev or not now:
        return None
    dt = (now["t"] - prev["t"]) * 1_000_000
    if dt <= 0:
        return None
    per = []
    for c, v in sorted(now["idle"].items()):
        p = prev["idle"].get(c)
        if v is None or p is None:
            continue
        busy = 1.0 - (v - p) / dt
        per.append(round(max(0.0, min(1.0, busy)) * 100))
    if not per:
        return None
    return {"pct": round(sum(per) / len(per)), "per_core": per, "cores": len(per)}


def frequencies(root=CPU_ROOT):
    """Per cluster (policy): which cores, the current and the highest frequency in MHz."""
    out = []
    pol_dir = os.path.join(root, "cpufreq")
    names = sorted(n for n in os.listdir(pol_dir) if re.fullmatch(r"policy\d+", n)) if os.path.isdir(pol_dir) else []
    for n in names:
        p = os.path.join(pol_dir, n)
        cur, mx, mn = read_int(os.path.join(p, "scaling_cur_freq")), read_int(os.path.join(p, "cpuinfo_max_freq")), read_int(os.path.join(p, "cpuinfo_min_freq"))
        out.append({"policy": n, "cpus": parse_cpu_list(read(os.path.join(p, "related_cpus")) or ""),
                    "cur_mhz": (cur or 0) // 1000, "max_mhz": (mx or 0) // 1000, "min_mhz": (mn or 0) // 1000,
                    "pct": round(100 * cur / mx) if cur and mx else None})
    if not out:
        for c in cpus(root):
            p = os.path.join(root, "cpu%d" % c, "cpufreq")
            cur, mx = read_int(os.path.join(p, "scaling_cur_freq")), read_int(os.path.join(p, "cpuinfo_max_freq"))
            if cur is not None:
                out.append({"policy": "cpu%d" % c, "cpus": [c], "cur_mhz": cur // 1000, "max_mhz": (mx or 0) // 1000, "min_mhz": 0,
                            "pct": round(100 * cur / mx) if mx else None})
    return out


# ---------------------------------------------------------------- memory
def parse_meminfo(text):
    """The kB numbers of /proc/meminfo, by key; missing or garbled lines are simply absent."""
    out = {}
    for line in (text or "").splitlines():
        # the digit run is bounded: a line of five thousand nines is not a number, it is Python's
        # 4300-digit int() limit raising ValueError out of a reader (Test 3, MALFORMED, 13.9.2026)
        m = re.match(r"^([A-Za-z_()0-9]+):\s+(\d{1,18})(?:\s+kB)?\s*$", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def memory(text=None):
    """What a person wants to know, in MB: total, used (total - available), available, cached, swap."""
    kb = parse_meminfo(read(MEMINFO) if text is None else text)
    total = kb.get("MemTotal")
    if not total:
        return None
    avail = kb.get("MemAvailable", kb.get("MemFree", 0))
    st, sf = kb.get("SwapTotal", 0), kb.get("SwapFree", 0)
    return {"total_mb": total // 1024, "used_mb": (total - avail) // 1024, "available_mb": avail // 1024,
            "free_mb": kb.get("MemFree", 0) // 1024, "cached_mb": kb.get("Cached", 0) // 1024,
            "swap_total_mb": st // 1024, "swap_used_mb": (st - sf) // 1024,
            "used_pct": round(100 * (total - avail) / total), "swap_pct": round(100 * (st - sf) / st) if st else 0}


# ---------------------------------------------------------------- the rest
def uptime_s():
    """Seconds since boot on the boot clock. NOT /proc/uptime: proot-distro binds a fake one that
    reads about two minutes forever, and Termux's own shell is denied the real one."""
    try:
        return int(time.clock_gettime(time.CLOCK_BOOTTIME))
    except (AttributeError, OSError):
        return None


def storage(path=PREFIX):
    try:
        s = os.statvfs(path)
    except OSError:
        return None
    total, free = s.f_blocks * s.f_frsize, s.f_bavail * s.f_frsize
    return {"total_gb": round(total / 1e9, 1), "free_gb": round(free / 1e9, 1), "used_pct": round(100 * (total - free) / total) if total else 0}


def own_processes():
    """Every process this uid can see in /proc: on Android that is Termux's own family and nothing
    else (hidepid). Still worth a look: a server left running from yesterday is here."""
    out = []
    for n in os.listdir("/proc"):
        if not n.isdigit():
            continue
        st = read("/proc/%s/stat" % n)
        cmd = read("/proc/%s/cmdline" % n)
        if not st or cmd is None:
            continue
        try:
            name = st[st.index("(") + 1:st.rindex(")")]
            fields = st[st.rindex(")") + 2:].split()
            rss_kb = int(fields[21]) * 4
        except (ValueError, IndexError):
            continue
        argv = " ".join(a for a in cmd.split("\0") if a)[:120]
        out.append({"pid": int(n), "name": name, "rss_mb": rss_kb // 1024, "cmd": argv or name})
    out.sort(key=lambda p: -p["rss_mb"])
    return out


# Every child this module starts, by process group, while it lives. Two reasons: a call that
# runs out of time is killed as a GROUP (termux-battery-status is a script that starts termux-api,
# and killing the script alone leaves termux-api waiting on its socket forever, which is the pile
# of orphans that got Claude Code killed on 13.9.2026); and stop_children() at exit, so a pm or a
# Termux:API call still in flight does not outlive the app (Test 4 found three left behind).
_children = {}


def run(cmd, timeout=API_TIMEOUT):
    """A bounded call. (rc, text); 127 when the command does not exist, 124 on timeout."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    except FileNotFoundError:
        return 127, "not installed: " + cmd[0]
    except OSError as e:
        return 126, "could not run %s: %s" % (cmd[0], e)
    _children[p.pid] = p
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or ""
    except subprocess.TimeoutExpired:
        _kill_group(p)
        return 124, "timed out after %ss: %s" % (timeout, " ".join(cmd[:2]))
    finally:
        _children.pop(p.pid, None)


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
    """Kill every call still in flight. Called once, at exit. Returns how many it stopped."""
    n = 0
    for p in list(_children.values()):
        if p.poll() is None:
            _kill_group(p)
            n += 1
    _children.clear()
    return n


def parse_packages(text):
    return sorted(line.strip()[8:] for line in (text or "").splitlines() if line.strip().startswith("package:"))


def third_party_packages():
    """pm answers from Termux's own shell on this phone (414 packages, 13.9.2026); from inside a
    PRoot it may not. Empty means unknown, not none."""
    rc, out = run(["pm", "list", "packages", "-3"], timeout=15)
    return parse_packages(out) if rc == 0 else []


def termux_api(name, timeout=API_TIMEOUT):
    """One Termux:API call, JSON or None. Costs one to two seconds (measured 1.7 s for the
    battery, 1.8 s for wifi): the sampler calls these once a minute, never on a request."""
    if not shutil.which(name):
        return None
    rc, out = run([name], timeout=timeout)
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def battery():
    b = termux_api("termux-battery-status")
    if not b:
        return None
    return {"pct": b.get("percentage"), "status": (b.get("status") or "").lower(), "plugged": (b.get("plugged") or "").lower(),
            "temp_c": b.get("temperature"), "current_ma": round((b.get("current") or 0) / 1000), "health": (b.get("health") or "").lower()}


def wifi():
    w = termux_api("termux-wifi-connectioninfo")
    if not w:
        return None
    return {"ssid": (w.get("ssid") or "").strip('"'), "ip": w.get("ip"), "rssi": w.get("rssi"),
            "link_mbps": w.get("link_speed_mbps"), "freq_mhz": w.get("frequency_mhz")}


def device():
    """Model, brand, Android version, from getprop; an empty string where the property is hidden."""
    out = {}
    for key, prop in (("model", "ro.product.model"), ("brand", "ro.product.brand"), ("android", "ro.build.version.release"), ("sdk", "ro.build.version.sdk")):
        rc, txt = run(["getprop", prop], timeout=4)
        out[key] = txt.strip() if rc == 0 else ""
    out["cores"] = len(cpus())
    return out
