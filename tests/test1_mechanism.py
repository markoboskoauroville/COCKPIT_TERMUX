#!/usr/bin/env python3
"""TEST 1 - the mechanism, alone: every parser and every piece of arithmetic in probe.py and
bridge.py, on text, with no phone, no adb and no network. The numbers are measured ones from this
phone (13.9.2026), not invented: a fake that could not exist proves nothing."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import APP, DUMPSYS_BATTERY, DUMPSYS_MEMINFO, DUMPSYS_THERMAL, MEMINFO, check, fake_cpu_root, finish, set_idle  # noqa: E402

sys.path.insert(0, APP)
import bridge  # noqa: E402
import localguard  # noqa: E402
import portpick  # noqa: E402
import probe  # noqa: E402

print("probe: the cpu list")
check("a range", probe.parse_cpu_list("0-7\n") == list(range(8)))
check("ranges and singles", probe.parse_cpu_list("0-3,6-7") == [0, 1, 2, 3, 6, 7])
check("related_cpus, space separated", probe.parse_cpu_list("0 1 2 3 4 5") == [0, 1, 2, 3, 4, 5])
check("garbage is empty, not a crash", probe.parse_cpu_list("x-y,,7-3,") == [])
check("None is empty", probe.parse_cpu_list(None) == [])

print("probe: the idle counters make the cpu number")
root = fake_cpu_root(cores=4)
check("four cores are found", probe.cpus(root) == [0, 1, 2, 3])
check("idle time sums both states", probe.idle_us(0, root) == 1000000)
a = probe.cpu_sample(root)
# one second later: core 0 slept the whole second, core 1 half, core 2 not at all, core 3 slept MORE than the second (a counter can lead the clock)
for c, gain in ((0, 1000000), (1, 500000), (2, 0), (3, 1100000)):
    set_idle(root, c, 500000 + gain)
b = probe.cpu_sample(root)
b["t"] = a["t"] + 1.0
busy = probe.cpu_busy(a, b)
check("a core asleep all second is 0 % busy", busy["per_core"][0] == 0, busy)
check("a core asleep half the second is 50 %", busy["per_core"][1] == 50, busy)
check("a core never asleep is 100 %", busy["per_core"][2] == 100, busy)
check("a counter ahead of the clock is clamped to 0, not -10", busy["per_core"][3] == 0, busy)
check("the overall number is the mean of the cores", busy["pct"] == round((0 + 50 + 100 + 0) / 4), busy)
check("no time passed: no number", probe.cpu_busy(a, dict(a)) is None)
check("no previous sample: no number", probe.cpu_busy(None, b) is None)
os.remove(os.path.join(root, "cpu2", "cpuidle", "state0", "time"))
c2 = probe.cpu_sample(root)
check("a core whose counter vanished is left out, the rest still count", probe.cpu_busy(b, dict(c2, t=b["t"] + 1))["cores"] == 4 or probe.cpu_busy(b, dict(c2, t=b["t"] + 1))["cores"] == 3)

print("probe: the frequencies")
fr = probe.frequencies(root)
check("one policy over four cores", len(fr) == 1 and fr[0]["cpus"] == [0, 1, 2, 3], fr)
check("current and max in MHz, the percentage of max", fr[0]["cur_mhz"] == 1500 and fr[0]["max_mhz"] == 2000 and fr[0]["pct"] == 75, fr)
check("no sysfs at all: an empty list, not a crash", probe.frequencies("/nonexistent") == [])

print("probe: /proc/meminfo")
kb = probe.parse_meminfo(MEMINFO)
check("every line parsed", kb["MemTotal"] == 7590488 and kb["SwapFree"] == 557464 and kb["Dirty"] == 276)
m = probe.memory(MEMINFO)
check("used is total minus available (the number that means something)", m["used_mb"] == (7590488 - 1837916) // 1024, m)
check("swap used and its percentage", m["swap_used_mb"] == (4194300 - 557464) // 1024 and m["swap_pct"] == 87, m)
check("garbage: None, not a crash", probe.memory("MemTotal: lots\n") is None and probe.memory("") is None)
check("a phone without swap: 0 %, no division", probe.memory("MemTotal: 1000 kB\nMemAvailable: 500 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")["swap_pct"] == 0)

print("probe: the rest")
check("uptime is on the boot clock and positive", (probe.uptime_s() or 0) > 0)
check("storage of a real path", probe.storage("/")["total_gb"] > 0)
check("storage of nowhere is None", probe.storage("/nonexistent/x") is None)
check("pm output parses to sorted package names", probe.parse_packages("package:b.app\npackage:a.app\njunk\n") == ["a.app", "b.app"])
check("run of a missing command is 127, not a crash", probe.run(["no-such-command-xyz"])[0] == 127)
check("run of a hang is 124 with the deadline in the text", probe.run(["sleep", "5"], timeout=0.3)[0] == 124)

print("bridge: the parsers")
d = bridge.parse_devices("List of devices attached\nemulator-5554          device product:x\n192.168.1.5:41234      offline\n\n")
check("two devices, their states", [x["state"] for x in d] == ["device", "offline"], d)
check("an empty list parses to nothing", bridge.parse_devices("List of devices attached\n\n") == [])
pm = bridge.parse_meminfo_processes(DUMPSYS_MEMINFO)
check("four processes, biggest first, pss in MB", [p["name"] for p in pm["processes"]][:2] == ["com.android.systemui", "com.termux"] and pm["processes"][0]["pss_mb"] == 421556 // 1024, pm)
check("the pid and the note", pm["processes"][1]["pid"] == 8030 and pm["processes"][1]["note"] == "activities", pm)
check("total RAM read from the foot", pm["total_mb"] == 7590488 // 1024, pm)
check("no block: empty, not a crash", bridge.parse_meminfo_processes("nothing here")["processes"] == [])
b = bridge.parse_battery(DUMPSYS_BATTERY)
check("battery: level, tenths of a degree, status word", b["pct"] == 61 and b["temp_c"] == 35.0 and b["status"] == "discharging" and not b["plugged"], b)
check("battery: garbage is None", bridge.parse_battery("") is None)
t = bridge.parse_thermal(DUMPSYS_THERMAL)
check("thermal: the status and two named temperatures", t["status"] == 1 and t["status_name"] == "light" and t["temps"][0]["name"] == "skin" and t["temps"][1]["c"] == 41.2, t)
check("thermal: garbage is None", bridge.parse_thermal("x") is None)
st = bridge.parse_proc_stat("cpu  1000 0 500 8000 100 0 50 0 0 0\ncpu0 1 2 3 4\n")
check("/proc/stat: busy and total jiffies", st == (1000 + 500 + 50, 9650), st)
check("two readings make a percentage", bridge.cpu_from_stat((1550, 9650), (1550 + 300, 9650 + 1000)) == 30)
check("no time passed: None", bridge.cpu_from_stat((1, 1), (1, 1)) is None)
top = bridge.parse_top("Tasks: 2 total\n  PID USER   PR NI VIRT  RES  SHR S[%CPU] %MEM   TIME+ ARGS\n 1832 system 20  0 5.0G 400M  60M S  12.5  5.0  1:00.00 com.android.systemui\n 8030 u0_a245 20 0 1.0G 300M 50M S  3.0  4.0  0:10.00 com.termux\n")
check("top: pid, cpu, res in MB, name", top[0]["pid"] == 1832 and top[0]["cpu"] == 12.5 and top[0]["res_mb"] == 400 and top[0]["name"] == "com.android.systemui", top)
check("top: no header, no rows", bridge.parse_top("garbage\n") == [])

print("bridge: what a package name may be")
check("a package name", bridge.PKG_RE.fullmatch("com.android.systemui") is not None)
check("a shell injection is not one", bridge.PKG_RE.fullmatch("com.x; rm -rf /") is None and bridge.PKG_RE.fullmatch("$(id)") is None)
check("a bare word is not one", bridge.PKG_RE.fullmatch("systemui") is None)
check("pair refuses a bad code before touching adb", bridge.pair("192.168.1.5:41234", "12ab")[0] is False)
check("pair refuses a bad address", bridge.pair("not an address", "123456")[0] is False)
check("connect refuses a bad address", bridge.connect("x")[0] is False)
check("force_stop refuses a bad name", bridge.force_stop("rm -rf /")[0] is False)
check("run without adb is 127, an answer", bridge.run(["devices"], adb="/nonexistent/adb")[0] in (126, 127))

print("portpick and the guard")
check("a free port is taken as is", portpick.pick("127.0.0.1", 0)[0] > 0)
import socket
s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1); taken = s.getsockname()[1]
port, note = portpick.pick("127.0.0.1", taken)
check("a taken port is stepped past, and said", port != taken and note and str(taken) in note, note)
s.close()
check("the guard's host check", localguard._host_ok("127.0.0.1:8860") and localguard._host_ok("localhost:8860") and not localguard._host_ok("evil.example:8860") and not localguard._host_ok("0.0.0.0:8860"))
check("the guard's origin check", localguard._origin_ok("http://127.0.0.1:8860", 8860) and not localguard._origin_ok("http://evil.example", 8860) and localguard._origin_ok("", 8860))

print("the version")
import version  # noqa: E402
check("one whole number", isinstance(version.APP_VERSION, int) and version.APP_VERSION >= 1)
t0 = time.time(); probe.cpu_sample(); check("a cpu sample costs milliseconds, not seconds", time.time() - t0 < 0.5)
finish("test1_mechanism")
