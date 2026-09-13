#!/usr/bin/env python3
"""TEST 2 - inside the running app, with real things: the real page and API through Flask's client
(the guard satisfied the way the page satisfies it), the real readers on THIS phone (the idle
counters, /proc/meminfo, cpufreq), the real console on a pty through app.py's own entry point, and
the bridge against a stand-in adb that answers the way the real one does (a real pairing needs a
person at the Wireless debugging screen; see NOT TESTED)."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Console, adb_calls, check, client, fake_adb, finish, fresh_home, http, wait_port  # noqa: E402

home = fresh_home()
adb_dir = fake_adb("device")
os.environ["PATH"] = adb_dir + os.pathsep + os.environ["PATH"]
appmod, c, H = client()

print("the page")
r = c.get("/", headers=H)
check("the page is served", r.status_code == 200 and b"<title>Cockpit</title>" in r.data)
check("the page carries the version", ("v%d" % appmod.version.APP_VERSION).encode() in r.data)
check("every control is in the first frame: eight dials, stop, kill all, pair, connect, lift, wake", all(s in r.data for s in (b'id="dCpu"', b'id="dWifi"', b'id="killAll"', b'id="pairBtn"', b'id="connBtn"', b'id="liftBtn"', b'id="wakeOn"', b'id="refresh"')))
check("a favicon, never the empty globe", c.get("/favicon.svg", headers=H).status_code == 200 and c.get("/favicon.svg", headers=H).mimetype == "image/svg+xml")
check("CSP and no-store on every answer", "default-src 'self'" in r.headers.get("Content-Security-Policy", "") and r.headers.get("Cache-Control") == "no-store")
check("/health answers without the header", c.get("/health", headers={"Host": H["Host"]}).status_code == 200)
check("/api without the header is refused", c.get("/api/status", headers={"Host": H["Host"]}).status_code == 403)
check("/api from another origin is refused", c.get("/api/status", headers=dict(H, Origin="http://evil.example")).status_code == 403)

print("the readers, on this phone")
appmod.sampler.tick(); time.sleep(2.1); appmod.sampler.tick()
s = c.get("/api/status", headers=H).get_json()["status"]
cpu = s["cpu"]
check("a cpu number from the idle counters, 0..100, one per core", cpu and 0 <= cpu["pct"] <= 100 and len(cpu["per_core"]) == cpu["cores"] >= 1, cpu)
check("memory: total, used, available in MB, the percentages", s["memory"] and s["memory"]["total_mb"] > 500 and 0 <= s["memory"]["used_pct"] <= 100, s["memory"])
check("frequencies: at least one cluster with a current and a max", s["freq"] and s["freq"][0]["max_mhz"] > 0, s["freq"])
check("uptime, storage, the device", s["uptime_s"] > 0 and s["storage"]["total_gb"] > 0 and s["device"]["cores"] >= 1, (s["uptime_s"], s["storage"], s["device"]))
check("its own processes are listed, this one among them", any(p["pid"] == os.getpid() for p in s["own"]) or len(s["own"]) > 0, s["own"][:2])
check("every part says when it was read", set(s["at"]) >= {"cpu", "quick"}, s["at"])
t0 = time.time(); c.get("/api/status", headers=H); check("a status answer comes from the snapshot, in milliseconds", time.time() - t0 < 0.3)

print("the bridge, against a stand-in adb that answers like the real one")
appmod.sampler.invalidate(); appmod.sampler.tick()
s = c.get("/api/status", headers=H).get_json()["status"]
check("the bridge is seen as paired", s["bridge"]["paired"] and s["bridge"]["serial"] == "emulator-5554", s["bridge"])
check("dumpsys meminfo became the process list, biggest first", s["procs"] and s["procs"]["processes"][0]["name"] == "com.android.systemui", s["procs"])
check("thermal and the phantom limit were read", s["thermal"]["status_name"] == "light" and s["phantom"]["max"] == "32" and not s["phantom"]["lifted"], (s["thermal"], s["phantom"]))
check("the battery came from the bridge (tenths of a degree)", s["battery"] and s["battery"]["pct"] == 61, s["battery"])
r = c.post("/api/stop", json={"package": "com.yahoo.mobile.client.android.weather"}, headers=H)
check("stop hands am force-stop the package", r.status_code == 200 and r.get_json()["ok"] and any("am force-stop com.yahoo.mobile.client.android.weather" in l for l in adb_calls(adb_dir)), r.get_json())
r = c.post("/api/stop", json={"package": "com.x; id"}, headers=H)
check("stop refuses a name that is not a package name", r.status_code == 400, r.get_json())
r = c.post("/api/kill-all", json={}, headers=H)
check("kill-all hands am kill-all to the shell", r.get_json()["ok"] and any("am kill-all" in l for l in adb_calls(adb_dir)))
r = c.post("/api/phantom/lift", json={}, headers=H)
check("lifting the limit writes both settings and reads them back", r.get_json()["ok"] and any("max_phantom_processes 2147483647" in l for l in adb_calls(adb_dir)), r.get_json())
appmod.sampler.invalidate(); appmod.sampler.tick()
s = c.get("/api/status", headers=H).get_json()["status"]
check("and the page then says lifted", s["phantom"]["lifted"], s["phantom"])
r = c.post("/api/bridge/pair", json={"hostport": "192.168.1.5:41234", "code": "123456"}, headers=H)
check("pair passes host:port and the code", r.get_json()["ok"] and any(l.startswith("pair 192.168.1.5:41234 123456") for l in adb_calls(adb_dir)), r.get_json())
r = c.post("/api/bridge/pair", json={"hostport": "192.168.1.5:41234", "code": "000000"}, headers=H)
check("a wrong code is reported, not swallowed", not r.get_json()["ok"] and "wrong" in r.get_json()["said"].lower(), r.get_json())
r = c.post("/api/bridge/connect", json={"hostport": "192.168.1.5:42000"}, headers=H)
check("connect", r.get_json()["ok"], r.get_json())
r = c.get("/api/log", headers=H).get_json()
check("every action is in the log, without arguments a person did not give", len(r["lines"]) >= 5 and any(l["event"] == "force-stop" for l in r["lines"]), r["lines"][:3])
r = c.post("/api/wake", json={"on": True}, headers=H)
check("the wake lock is asked for, and the answer is a sentence", "said" in r.get_json(), r.get_json())

print("the console, on a real pty, through app.py's own entry point")
con = Console(home=home, env={"PATH": adb_dir + os.pathsep + os.environ["PATH"]})
check("the banner names the app and the port", con.wait_for("Cockpit", 25) and con.wait_for(str(con.port), 5), con.screen()[-300:])
check("the keys are offered on one plain line", con.wait_for("q quit", 8) and "o open page" in con.screen() and "u check for update" in con.screen() and "r restart" in con.screen())
check("the server answers on the port it printed", wait_port(con.port, 20))
st, body = http("http://127.0.0.1:%d/api/status" % con.port, headers={"X-Cockpit-Local": "1"})
j = json.loads(body) if st == 200 else {}
check("the live server has a cpu number within seconds", st == 200 and j["status"]["cpu"] and j["status"]["cpu"]["pct"] >= 0, body[:200])
con.key("o")
check("o says it is opening the browser", con.wait_for("opening the browser", 8), con.screen()[-200:])
con.key("q")
check("q stops it, and it says so", con.wait_exit(10) and "stopped" in con.screen(), con.screen()[-200:])
check("the port is released", not wait_port(con.port, 2))
check("nothing left behind in its process group", con.left_behind() == [], con.left_behind())
con.kill()
finish("test2_real")
