#!/usr/bin/env python3
"""TEST 3 - the ugly cases (four-tests.md): EMPTY, MALFORMED, HOSTILE, TWICE, OUT OF ORDER, ABSENT,
NEVER ANSWERS. A phone that hides a file, an adb that hangs, a page that sends garbage, a port that
is taken, a package name built to reach a shell. Every one must be an answer, never a crash."""
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import APP, Console, check, client, fake_adb, fake_cpu_root, finish, fresh_home, wait_port  # noqa: E402

sys.path.insert(0, APP)
import bridge  # noqa: E402
import probe  # noqa: E402

home = fresh_home()

print("EMPTY - a phone that hides everything")
check("no sysfs: no cores, no crash", probe.cpus("/nonexistent") == [])
check("no idle counters: None", probe.idle_us(0, "/nonexistent") is None)
check("cpu_busy of two empty samples: None", probe.cpu_busy({"t": 1, "idle": {}}, {"t": 2, "idle": {}}) is None)
root = fake_cpu_root(cores=2)
for c in (0, 1):
    os.remove(os.path.join(root, "cpu%d" % c, "cpuidle", "state0", "time"))
    os.remove(os.path.join(root, "cpu%d" % c, "cpuidle", "state1", "time"))
check("idle files present but unreadable: None per core, and no number overall", probe.idle_us(0, root) is None and probe.cpu_busy(probe.cpu_sample(root), dict(probe.cpu_sample(root), t=99)) is None)
check("memory of nothing: None", probe.memory("") is None)
check("no adb on the PATH: an answer", bridge.run(["devices"], adb="/no/such/adb")[0] in (126, 127))

print("MALFORMED - files with the wrong shape")
check("meminfo with words for numbers", probe.memory("MemTotal: many kB\nMemAvailable: 3 kB\n") is None)
check("meminfo with a five-thousand-digit line: skipped, no crash (Python's int limit raised out of the first version)", "MemTotal" not in probe.parse_meminfo("MemTotal: " + "9" * 5000 + " kB\nMemFree: 5 kB\n") and probe.parse_meminfo("MemTotal: " + "9" * 5000 + " kB\nMemFree: 5 kB\n")["MemFree"] == 5)
check("online with letters", probe.parse_cpu_list("a-z") == [])
check("dumpsys meminfo cut mid-line", bridge.parse_meminfo_processes("Total PSS by process:\n    123,456K: com.x (pid")["processes"] == [])
check("dumpsys battery with a boolean where a number goes", bridge.parse_battery("  level: true\n  temperature: 350\n") is None or True)
check("/proc/stat with too few fields", bridge.parse_proc_stat("cpu 1 2\n") is None)
check("top with a header and no rows", bridge.parse_top("  PID USER S[%CPU] ARGS\n") == [])
r = fake_cpu_root(cores=1)
with open(os.path.join(r, "cpufreq", "policy0", "scaling_cur_freq"), "w") as f:
    f.write("notanumber\n")
check("a frequency file with text: 0, not a crash", probe.frequencies(r)[0]["cur_mhz"] == 0 and probe.frequencies(r)[0]["pct"] is None)

print("HOSTILE - names built to reach a shell")
for bad in ("com.x; rm -rf /", "$(reboot)", "`id`", "com.x && am kill-all", "../../etc", "com.x\nam kill-all", "a" * 5000, ""):
    ok, msg = bridge.force_stop(bad)
    check("force_stop refuses %r" % bad[:20], ok is False and "package" in msg)
appmod, c, H = client()
check("/api/stop with a hostile name: 400", c.post("/api/stop", json={"package": "com.x; id"}, headers=H).status_code == 400)
check("/api/stop with no body: 400", c.post("/api/stop", data="garbage", headers=H).status_code == 400)
check("/api/bridge/pair with a hostile host: refused before adb", c.post("/api/bridge/pair", json={"hostport": "x; id", "code": "123456"}, headers=H).get_json()["ok"] is False)
check("/api/log?n=x: a default, not a 500", c.get("/api/log?n=x", headers=H).status_code == 200)
check("/api/log?n=99999: capped", c.get("/api/log?n=99999", headers=H).status_code == 200)
check("a body over the limit is refused", c.post("/api/stop", data="x" * 70000, headers=dict(H, **{"Content-Type": "application/json"})).status_code in (400, 413))

print("TWICE - the same thing again")
adb_dir = fake_adb("device")
os.environ["PATH"] = adb_dir + os.pathsep + os.environ["PATH"]
appmod.sampler.invalidate(); appmod.sampler.tick()
r1 = c.post("/api/stop", json={"package": "com.termux"}, headers=H).get_json()
r2 = c.post("/api/stop", json={"package": "com.termux"}, headers=H).get_json()
check("stopping an app twice is two ok answers, not an error", r1["ok"] and r2["ok"])
r1 = c.post("/api/phantom/lift", json={}, headers=H).get_json()
r2 = c.post("/api/phantom/lift", json={}, headers=H).get_json()
check("lifting the limit twice is idempotent", r1["ok"] and r2["ok"])
check("refresh twice in a row", c.post("/api/refresh", json={}, headers=H).status_code == 200 and c.post("/api/refresh", json={}, headers=H).status_code == 200)

print("OUT OF ORDER - the bridge dropped mid-way")
os.environ["PATH"] = fake_adb("offline") + os.pathsep + os.environ["PATH"]
appmod.sampler.invalidate("bridge"); appmod.sampler.tick()
s = c.get("/api/status", headers=H).get_json()["status"]
check("an offline device is not 'paired', and the note says offline", not s["bridge"]["paired"] and "offline" in s["bridge"]["note"], s["bridge"])
r = c.post("/api/stop", json={"package": "com.termux"}, headers=H)
check("stop while the bridge is down: 409 with the reason, nothing done", r.status_code == 409 and "bridge" in r.get_json()["error"])
check("the last known process list is kept, not wiped", s["procs"] is not None)

print("ABSENT - adb not installed at all")
real_path = os.environ["PATH"]
os.environ["PATH"] = "/nonexistent-bin"
saved = bridge.shutil.which
bridge.shutil.which = lambda *a, **k: None
saved_exists = os.path.exists
os.path.exists = lambda p: False if p.endswith("/bin/adb") else saved_exists(p)
st = bridge.state()
check("the bridge says adb is not installed, and how to install it", not st["installed"] and "android-tools" in st["note"], st)
os.path.exists = saved_exists
bridge.shutil.which = saved
os.environ["PATH"] = real_path

print("NEVER ANSWERS - an adb that accepts and hangs")
os.environ["PATH"] = fake_adb("device", hang=True) + os.pathsep + os.environ["PATH"]
bridge.ADB_TIMEOUT = 1
t0 = time.time(); st = bridge.state()
check("state() gives up within the deadline and says not paired", time.time() - t0 < 4 and not st["paired"], (round(time.time() - t0, 1), st))
t0 = time.time(); rc, out = bridge.run(["devices"], timeout=1)
check("run() returns 124 with the deadline in the text", rc == 124 and "did not answer" in out, (rc, out))
bridge.ADB_TIMEOUT = 12
t0 = time.time(); rc, out = probe.run(["sh", "-c", "sleep 30"], timeout=0.5)
check("a Termux:API stand-in that never answers is cut off", rc == 124 and time.time() - t0 < 3)

print("a port that is taken")
s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1); taken = s.getsockname()[1]
con = Console(port=taken, home=home)
check("the app starts on the next port and says so", con.wait_for("instead", 25) and wait_port(taken + 1, 15), con.screen()[-300:])
con.key("q"); con.wait_exit(10); con.kill(); s.close()

print("the sampler survives a reader that raises")
appmod.sampler.set("cpu", None)
saved_fn = appmod.probe.frequencies
appmod.probe.frequencies = lambda *a: 1 / 0
appmod.sampler.invalidate(); appmod.sampler.tick()
appmod.probe.frequencies = saved_fn
check("a raising reader is logged, the clock goes on", any(l["event"] == "sampler error" for l in c.get("/api/log", headers=H).get_json()["lines"]))
appmod.sampler.invalidate(); appmod.sampler.tick()
check("and the next tick reads again", c.get("/api/status", headers=H).get_json()["status"]["freq"])
finish("test3_ugly")
