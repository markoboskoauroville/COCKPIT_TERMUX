"""
app.py  --  the Cockpit: the phone's health on one page, and the hand on it. Flask, 127.0.0.1 only.

    cockpit                 start it; the page opens; the console has q / o / u / r
    http://127.0.0.1:8860   the page (8860-8875, then any: portpick.py)

The shape of KEYRING_TERMUX (app.py, console.py, localguard.py, portpick.py, selfupdate.py): the
guard's three checks on every /api/ call, a port that never fails to open, the console every app
here has. Two engines of its own: probe.py reads what an app may read on this phone (the idle
counters that make the CPU number, /proc/meminfo, cpufreq, Termux:API once a minute), and
bridge.py reaches the shell user over adb when Wireless debugging is paired, which is the only
way an unrooted Android 14+ phone lets a person see every process and stop one.

A SAMPLER THREAD, not a reader per request: the CPU number needs two readings two seconds apart,
Termux:API costs seconds, dumpsys meminfo takes a second or two. So one thread keeps a snapshot
and every request answers from it in a millisecond. The snapshot carries the age of each part, so
the page can say "battery: 40 s ago" rather than pretend.
"""
import json
import os
import sys
import threading
import time

from flask import Flask, Response, jsonify, request

import bridge
import localguard
import portpick
import probe
import version

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "cockpit.html")
DEFAULT_PORT = 8860
LIVE_PORT = DEFAULT_PORT
START = time.time()
LOG_DIR = os.environ.get("COCKPIT_HOME") or os.path.join(os.path.expanduser("~"), ".cockpit")
LOG = os.path.join(LOG_DIR, "log.jsonl")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#0b0d10"/>'
           '<path d="M12 40a20 20 0 0 1 40 0" fill="none" stroke="#23303d" stroke-width="7" stroke-linecap="round"/>'
           '<path d="M12 40a20 20 0 0 1 26-19" fill="none" stroke="#f59e0b" stroke-width="7" stroke-linecap="round"/>'
           '<circle cx="32" cy="40" r="4" fill="#f2ddb4"/><path d="M32 40l9-13" stroke="#f2ddb4" stroke-width="4" stroke-linecap="round"/></svg>')

# how often each part is refreshed, in seconds
EVERY = {"cpu": 2, "memory": 2, "freq": 2, "quick": 10, "api": 60, "bridge": 6, "bridge_procs": 8, "bridge_slow": 60}


def log(event, **kw):
    try:
        os.makedirs(LOG_DIR, mode=0o700, exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **kw}) + "\n")
    except OSError:
        pass


class Sampler:
    """One snapshot, refreshed on its own thread; readers never block a request."""

    def __init__(self):
        self.snap = {"at": {}, "cpu": None, "cpu_stat": None, "freq": [], "memory": None, "storage": None, "uptime_s": None,
                     "device": None, "battery": None, "wifi": None, "packages": [], "own": [],
                     "bridge": {"installed": False, "paired": False, "serial": None, "note": "not asked yet"},
                     "procs": None, "top": None, "thermal": None, "phantom": None}
        self._prev_cpu = None
        self._prev_stat = None
        self._last = {}
        self._lock = threading.Lock()
        self._threads = []
        self._pkgs_thread = None
        self._stop = threading.Event()

    def _read_packages(self):
        """pm list packages can take fifteen seconds on this phone: on its own thread, once."""
        self.set("packages", probe.third_party_packages() or ["?"])

    def due(self, key):
        return time.time() - self._last.get(key, 0) >= EVERY[key]

    def mark(self, key):
        self._last[key] = time.time()
        self.snap["at"][key] = round(time.time())

    def set(self, key, value):
        with self._lock:
            self.snap[key] = value

    def tick_fast(self):
        """The two-second readings: the idle counters, the frequencies, /proc/meminfo. Milliseconds."""
        if self.due("cpu"):
            cur = probe.cpu_sample()
            busy = probe.cpu_busy(self._prev_cpu, cur)
            self._prev_cpu = cur
            if busy:
                self.set("cpu", busy)
            self.set("freq", probe.frequencies())
            self.set("memory", probe.memory())
            self.mark("cpu")

    def tick_slow(self):
        """Everything that costs seconds: Termux:API, adb, pm. On its own thread, so a slow adb
        never holds the CPU number back (the first version ran both on one clock and the page
        showed no CPU for five seconds while adb started its server)."""
        s = self.snap
        if self.due("quick"):
            self.set("storage", probe.storage())
            self.set("uptime_s", probe.uptime_s())
            self.set("own", probe.own_processes()[:12])
            if s["device"] is None:
                self.set("device", probe.device())
            if not s["packages"] and not self._pkgs_thread:
                self._pkgs_thread = threading.Thread(target=self._read_packages, daemon=True, name="packages")
                self._pkgs_thread.start()
            self.mark("quick")
        if self.due("api"):
            self.set("battery", probe.battery() or s["battery"])
            self.set("wifi", probe.wifi() or s["wifi"])
            self.mark("api")
        if self.due("bridge"):
            self.set("bridge", bridge.state())
            self.mark("bridge")
        if s["bridge"].get("paired"):
            if self.due("bridge_procs"):
                st = bridge.proc_stat()
                self.set("cpu_stat", bridge.cpu_from_stat(self._prev_stat, st))
                self._prev_stat = st
                self.set("procs", bridge.processes() or s["procs"])
                self.set("top", bridge.top() or s["top"])
                self.mark("bridge_procs")
            if self.due("bridge_slow"):
                self.set("thermal", bridge.thermal() or s["thermal"])
                self.set("phantom", bridge.phantom() or s["phantom"])
                b = bridge.battery()
                if b:
                    self.set("battery", b)
                self.mark("bridge_slow")
        else:
            self._prev_stat = None

    def tick(self):
        """Both, now. Everything here is bounded; a reader that raises is a bug in the reader, and
        it is caught and logged rather than allowed to stop the clock for everything else."""
        for fn in (self.tick_fast, self.tick_slow):
            try:
                fn()
            except Exception as e:                               # noqa: BLE001
                log("sampler error", where=fn.__name__, error=repr(e)[:200])

    def _loop(self, fn, every):
        while not self._stop.is_set():
            try:
                fn()
            except Exception as e:                               # noqa: BLE001
                log("sampler error", where=fn.__name__, error=repr(e)[:200])
            self._stop.wait(every)

    def start(self):
        if not self._threads:
            self._threads = [threading.Thread(target=self._loop, args=(self.tick_fast, 0.5), daemon=True, name="sampler-fast"),
                             threading.Thread(target=self._loop, args=(self.tick_slow, 1.0), daemon=True, name="sampler-slow")]
            for t in self._threads:
                t.start()

    def stop(self):
        self._stop.set()

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self.snap))

    def invalidate(self, *keys):
        """Read these parts again on the next tick (all of them when no key is given)."""
        if not keys:
            self._last = {}
        for k in keys:
            self._last.pop(k, None)


sampler = Sampler()


@app.before_request
def _guard():
    return localguard.check(LIVE_PORT)


@app.after_request
def _headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    return resp


@app.route("/")
def index():
    with open(PAGE, encoding="utf-8") as f:
        html = f.read()
    return Response(html.replace("{{VERSION}}", str(version.APP_VERSION)), mimetype="text/html; charset=utf-8")


@app.route("/favicon.svg")
def favicon():
    return Response(FAVICON, mimetype="image/svg+xml")


@app.route("/favicon.ico")
def favicon_ico():
    return Response(FAVICON, mimetype="image/svg+xml")


@app.route("/health")
def health():
    s = sampler.snapshot()
    return jsonify({"ok": True, "version": version.APP_VERSION, "uptime": round(time.time() - START), "cpu": (s["cpu"] or {}).get("pct"), "bridge": s["bridge"].get("paired")})


def _err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


# ---------------------------------------------------------------- the snapshot
@app.route("/api/status")
def api_status():
    s = sampler.snapshot()
    s["now"] = round(time.time())
    s["version"] = version.APP_VERSION
    return jsonify({"ok": True, "status": s})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Read everything again now, bridge included; a person pressing refresh does not want the
    next tick in six seconds."""
    sampler.invalidate()
    sampler.tick()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- the hand on it
@app.route("/api/stop", methods=["POST"])
def api_stop():
    body = request.get_json(silent=True) or {}
    pkg = str(body.get("package") or "").strip()
    if not bridge.PKG_RE.fullmatch(pkg):
        return _err("not a package name")
    if not sampler.snapshot()["bridge"].get("paired"):
        return _err("the bridge is not connected: pair Wireless debugging first", 409)
    ok, msg = bridge.force_stop(pkg)
    log("force-stop", package=pkg, ok=ok, said=msg[:120])
    sampler.invalidate("bridge_procs")
    return jsonify({"ok": ok, "said": msg})


@app.route("/api/kill-all", methods=["POST"])
def api_kill_all():
    if not sampler.snapshot()["bridge"].get("paired"):
        return _err("the bridge is not connected: pair Wireless debugging first", 409)
    ok, msg = bridge.kill_all()
    log("kill-all", ok=ok, said=msg[:120])
    sampler.invalidate("bridge_procs")
    return jsonify({"ok": ok, "said": msg})


@app.route("/api/bridge/pair", methods=["POST"])
def api_pair():
    body = request.get_json(silent=True) or {}
    ok, msg = bridge.pair(body.get("hostport"), body.get("code"))
    log("pair", ok=ok, said=msg[:120])
    sampler.invalidate("bridge")
    return jsonify({"ok": ok, "said": msg})


@app.route("/api/bridge/connect", methods=["POST"])
def api_connect():
    body = request.get_json(silent=True) or {}
    ok, msg = bridge.connect(body.get("hostport"))
    log("connect", ok=ok, said=msg[:120])
    sampler.invalidate("bridge", "bridge_procs", "bridge_slow")
    return jsonify({"ok": ok, "said": msg})


@app.route("/api/bridge/disconnect", methods=["POST"])
def api_disconnect():
    ok, msg = bridge.disconnect()
    log("disconnect", ok=ok)
    sampler.invalidate("bridge")
    return jsonify({"ok": ok, "said": msg})


@app.route("/api/phantom/lift", methods=["POST"])
def api_phantom_lift():
    if not sampler.snapshot()["bridge"].get("paired"):
        return _err("the bridge is not connected: pair Wireless debugging first", 409)
    ok, msg = bridge.lift_phantom()
    log("phantom lift", ok=ok, said=msg[:200])
    sampler.invalidate("bridge_slow")
    return jsonify({"ok": ok, "said": msg})


@app.route("/api/wake", methods=["POST"])
def api_wake():
    body = request.get_json(silent=True) or {}
    want = bool(body.get("on", True))
    rc, out = probe.run(["termux-wake-lock" if want else "termux-wake-unlock"], timeout=10)
    log("wake lock", on=want, rc=rc)
    return jsonify({"ok": rc == 0, "said": ("wake lock held" if want else "wake lock released") if rc == 0 else out.strip()[:120]})


@app.route("/api/log")
def api_log():
    try:
        n = min(max(int(request.args.get("n", 30)), 1), 500)
    except ValueError:
        n = 30
    try:
        with open(LOG, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
    except OSError:
        lines = []
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return jsonify({"ok": True, "lines": out})


def console_snapshot():
    s = sampler.snapshot()
    cpu = (s["cpu"] or {}).get("pct")
    mem = s["memory"] or {}
    return {"version": version.APP_VERSION,
            "line": "cpu %s%%  ram %s/%s MB  bridge %s" % (cpu if cpu is not None else "?", mem.get("used_mb", "?"), mem.get("total_mb", "?"), "up" if s["bridge"].get("paired") else "down")}


if __name__ == "__main__":
    import console as term
    import selfupdate
    requested = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            requested = int(sys.argv[1])
        except ValueError:
            print("ignoring invalid port argument %r, using %d" % (sys.argv[1], DEFAULT_PORT))
    LIVE_PORT, note = portpick.pick("127.0.0.1", requested)
    # serve at once: the first tick reads Termux:API and pm, which take seconds, and a server
    # that opens its page ten seconds late looks broken on the one screen that matters
    sampler.start()
    for _ in range(35):
        if sampler.snap["cpu"]:
            break
        time.sleep(0.1)
    action = term.run(app, "127.0.0.1", LIVE_PORT, snapshot=console_snapshot, note=note,
                      on_check_update=selfupdate.check_remote, on_perform_update=selfupdate.perform_update)
    sampler.stop()
    left = probe.stop_children() + bridge.stop_children()
    if left:
        log("exit", children_stopped=left)
    if action == "restart":
        os.execv(sys.executable, [sys.executable] + sys.argv)
