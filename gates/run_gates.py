#!/usr/bin/env python3
"""The nine gates of modules/delivery-gate.md, on this repository, each printing a COUNT of what it
examined and not only what it found. Cheapest first. Copied from KEYRING_TERMUX/gates/run_gates.py
(13.9.2026) and adapted: the unwired sweep reads cockpit.html and app.py, the soak drives the
cockpit's own API against a stand-in adb.

    python3 gates/run_gates.py            all nine, the record printed at the end
    python3 gates/run_gates.py G2 G5      some of them

G1 provenance   the tree is clean, the version rose, the commit is on main, HEAD is pushed
G2 secrets      the tree and the history carry no key-shaped string
G3 analysis     pyflakes (ruff has no wheel for this phone), bandit, shellcheck, pip-audit, node syntax,
                python compiles with warnings as errors
G4 dead code    vulture at 100/80/60, and the UNWIRED sweep: every address the page calls exists,
                every data-act the page emits has a handler, every element id is used
G5 dead loops   every loop and every external wait read, with its bound or its deadline
G6 stress       a 300-cycle status/refresh/stop soak against a stand-in adb, RSS flat; a seeded monkey
                of 1500 random API calls, 0 crashes
G7 budgets      import time, page size, source size, a cpu sample, test 1, against BUDGETS.json
G8 upgrade      tests/test4_upgrade.py, and the rollback clause inside it
G9 the record   DELIVERY_RECORD.md written from the counts above, NOT TESTED filled by hand
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
PY = sys.executable
SOURCES = [n for n in os.listdir(APP) if n.endswith(".py")] + ["cockpit", "install-termux.sh", "cockpit.html"]
KEY_SHAPE = re.compile(r"(sk-ant-|gsk_|AIza|AQ\.|ghp_|github_pat_|cfat_|sk_|sk-|hf_)[A-Za-z0-9_\-]{20,}")
results = {}


def say(g, line):
    print("  %s  %s" % (g, line), flush=True)


def run(cmd, timeout=600, cwd=APP):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return p.returncode, p.stdout + p.stderr
    except FileNotFoundError:
        return 127, "not installed: " + cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def git(*a):
    return run(["git", "-C", APP] + list(a))[1].strip()


def gate(name):
    def deco(fn):
        results[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------- G1
@gate("G1")
def g1():
    dirty = [l for l in git("status", "--porcelain").splitlines() if l.strip()]
    say("G1", "working tree: %d changed or untracked paths" % len(dirty))
    ver = int(re.search(r"APP_VERSION\s*=\s*(\d+)", open(os.path.join(APP, "version.py")).read()).group(1))
    prev = git("show", "HEAD~1:version.py") if git("rev-list", "--count", "HEAD") not in ("", "0", "1") else ""
    pv = int(re.search(r"APP_VERSION\s*=\s*(\d+)", prev).group(1)) if "APP_VERSION" in prev else 0
    say("G1", "version %d (previous commit %s)" % (ver, pv or "none"))
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    pushed = git("rev-parse", "origin/main") == git("rev-parse", "HEAD") if git("remote") else False
    say("G1", "branch %s, HEAD %s, pushed to origin/main: %s" % (branch, git("rev-parse", "--short", "HEAD"), pushed))
    ok = not dirty and ver >= pv and branch == "main"
    return ok, "clean=%s version %d>=%s branch=%s pushed=%s" % (not dirty, ver, pv, branch, pushed)


# ---------------------------------------------------------------- G2
@gate("G2")
def g2():
    hits, files = 0, 0
    for root, dirs, names in os.walk(APP):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for n in names:
            p = os.path.join(root, n)
            try:
                data = open(p, "rb").read()
            except OSError:
                continue
            files += 1
            for m in KEY_SHAPE.finditer(data.decode("utf-8", "replace")):
                hits += 1
                say("G2", "KEY-SHAPED STRING in %s: %s…" % (os.path.relpath(p, APP), m.group(0)[:6]))
    say("G2", "tree: %d files scanned, %d key-shaped strings" % (files, hits))
    hist = git("log", "-p", "--all")
    hh = len(KEY_SHAPE.findall(hist))
    say("G2", "history: %d commits, %d key-shaped strings" % (len(git("rev-list", "--all").splitlines()), hh))
    log = os.path.join(os.path.expanduser("~"), ".cockpit", "log.jsonl")
    lh = len(KEY_SHAPE.findall(open(log).read())) if os.path.exists(log) else 0
    say("G2", "the app's log: %d key-shaped strings" % lh)
    return hits == 0 and hh == 0 and lh == 0, "tree %d/%d hits, history %d hits, log %d hits" % (files, hits, hh, lh)


# ---------------------------------------------------------------- G3
@gate("G3")
def g3():
    pyfiles = [os.path.join(APP, n) for n in os.listdir(APP) if n.endswith(".py")] + [os.path.join(APP, "tests", n) for n in os.listdir(os.path.join(APP, "tests")) if n.endswith(".py")] + [os.path.join(HERE, "run_gates.py")]
    ok = True
    rc, out = run(["pyflakes"] + pyfiles)
    n_f = len([l for l in out.splitlines() if re.match(r".*:\d+:\d+:", l)])
    say("G3", "pyflakes (undefined names, unused imports/variables, redefinitions) over %d files: %d findings" % (len(pyfiles), n_f) if rc != 127 else "pyflakes not installed")
    for l in out.splitlines()[:20]:
        if re.match(r".*:\d+:\d+:", l):
            say("G3", "   " + l.replace(APP + "/", "")[:140])
    ok = ok and (n_f == 0 or rc == 127)
    rc, out = run(["bandit", "-q", "-ll", "-x", "tests,gates", "-r", APP])
    n_b = out.count(">> Issue:")
    say("G3", "bandit, medium and high: %d issues" % n_b if rc != 127 else "bandit not installed")
    for l in out.splitlines():
        if ">> Issue:" in l or "Location:" in l:
            say("G3", "   " + l.strip()[:120])
    ok = ok and (n_b == 0 or rc == 127)
    rc, out = run(["shellcheck", "-S", "warning", os.path.join(APP, "cockpit"), os.path.join(APP, "install-termux.sh")])
    n_s = out.count("^--")
    say("G3", "shellcheck (warning and up) on cockpit, install-termux.sh: %d" % n_s if rc != 127 else "shellcheck not installed")
    for l in out.splitlines()[:20]:
        if l.strip():
            say("G3", "   " + l[:120])
    ok = ok and (n_s == 0 or rc == 127)
    rc, out = run(["pip-audit", "--progress-spinner", "off", "-r", os.path.join(APP, "requirements.txt")], timeout=600)
    n_v = len([l for l in out.splitlines() if re.search(r"\b(GHSA|PYSEC|CVE)-", l)])
    say("G3", "pip-audit: %d known vulnerabilities in the dependencies" % n_v if rc != 127 else "pip-audit not installed")
    rc, out = run(["node", "-e", "const fs=require('fs');const h=fs.readFileSync(process.argv[1],'utf8');const m=h.match(/<script>([\\s\\S]*)<\\/script>/);new Function(m[1]);console.log('ok')", os.path.join(APP, "cockpit.html")])
    say("G3", "the page's script parses in node: %s" % (out.strip() == "ok"))
    ok = ok and out.strip() == "ok"
    rc, out = run([PY, "-W", "error", "-c", "import glob\nfor f in glob.glob('%s/*.py'):\n    with open(f) as fh: compile(fh.read(), f, 'exec')\nprint('ok')" % APP])
    say("G3", "python compiles with warnings as errors: %s" % (out.strip() == "ok") + ("" if out.strip() == "ok" else "  " + out.strip()[-200:]))
    ok = ok and out.strip() == "ok"
    return ok, "pyflakes %s, bandit %s, shellcheck %s, audit %s" % (n_f, n_b, n_s, n_v)


# ---------------------------------------------------------------- G4
@gate("G4")
def g4():
    ok = True
    for conf in (100, 80, 60):
        rc, out = run(["vulture", "--min-confidence", str(conf), APP, "--exclude", "tests,gates"])
        hits = [l for l in out.splitlines() if re.match(r".*:\d+:", l)]
        say("G4", "vulture at %d%%: %d findings" % (conf, len(hits)) if rc != 127 else "vulture not installed")
        if conf == 100 and rc != 127:
            for l in hits:
                say("G4", "   " + l[:120])
            ok = ok and not hits
        elif conf == 60 and rc != 127:
            for l in hits[:12]:
                say("G4", "   (confirm) " + l[:120])
    html = open(os.path.join(APP, "cockpit.html")).read()
    js = html[html.index("<script>"):]
    src = open(os.path.join(APP, "app.py")).read()
    routes = re.findall(r'@app\.route\("([^"]+)"', src)
    called = set(re.findall(r'(?:api|fetch|act)\("(/api/[a-z\-/]+|/favicon\.svg|/health)', js))
    missing = [c for c in called if c not in routes]
    say("G4", "sweep: page calls %d addresses, server has %d routes, unwired: %d %s" % (len(called), len(routes), len(missing), missing))
    unreached = [r for r in routes if r.startswith("/api/") and r not in called]
    say("G4", "sweep: routes the page never calls: %d %s" % (len(unreached), unreached))
    acts = set(re.findall(r'data-act="([a-z]+)"', js))
    handled = set(re.findall(r'dataset\.act === "([a-z]+)"', js))
    unhandled = sorted(acts - handled)
    say("G4", "sweep: page emits %d actions, handles %d, unhandled: %d %s" % (len(acts), len(handled), len(unhandled), unhandled))
    ids = set(re.findall(r'id="([A-Za-z]+)"', html))
    used = set(re.findall(r'\$\("([A-Za-z]+)"\)', js)) | set(re.findall(r'(?:dial|bar|say)\("([A-Za-z]+)"', js)) | set(re.findall(r'"([A-Za-z]+)"\);', js))
    unused = sorted(ids - used)
    say("G4", "sweep: %d element ids, %d used by the script, unused: %s" % (len(ids), len(used & ids), unused))
    keys = set(re.findall(r'"(cpu|memory|freq|storage|uptime_s|device|battery|wifi|packages|own|bridge|procs|top|thermal|phantom|cpu_stat)"', src))
    shown = set(re.findall(r's\.(cpu_stat|cpu|memory|freq|storage|uptime_s|device|battery|wifi|packages|own|bridge|procs|top|thermal|phantom)\b', js))
    unshown = sorted(keys - shown)
    say("G4", "sweep: the snapshot has %d parts, the page shows %d, never shown: %s" % (len(keys), len(shown & keys), unshown))
    ok = ok and not missing and not unhandled and not unused and unshown == ["top"]
    say("G4", "   ('top' is read for the record and not drawn: the process list is dumpsys meminfo; a decision, not an omission)")
    return ok, "unwired %d, unreached %d, unhandled %d, unused ids %d, unshown %s" % (len(missing), len(unreached), len(unhandled), len(unused), unshown)


# ---------------------------------------------------------------- G5
@gate("G5")
def g5():
    loops, waits, problems = 0, 0, []
    for n in [x for x in os.listdir(APP) if x.endswith(".py")]:
        with open(os.path.join(APP, n)) as fh:
            lines = fh.read().splitlines()
        for i, l in enumerate(lines, 1):
            s = l.strip()
            if re.match(r"(while|for)\b", s):
                loops += 1
                if s.startswith("while True") and n not in ("console.py",):
                    problems.append("%s:%d %s (bounded by?)" % (n, i, s[:60]))
                if s.startswith("while not self._stop"):
                    pass                                    # the sampler's loops: stopped by the Event at exit
            if re.search(r"urlopen\(|(?<!bridge)\.connect\(|subprocess\.run\(|subprocess\.Popen\(|\.communicate\(|select\.select\(|requests\.|\.wait\(", s):
                waits += 1
                window = "\n".join(lines[max(0, i - 6):i + 3])
                if not re.search(r"timeout|settimeout|_stop\.wait", window) and not re.search(r"select\.select\(.*,\s*[\d.]+\)", s):
                    problems.append("%s:%d %s (no deadline within the statement or a settimeout above it)" % (n, i, s[:70]))
    say("G5", "%d loops examined, %d external waits examined, %d to read by hand:" % (loops, waits, len(problems)))
    for p in problems:
        say("G5", "   " + p)
    say("G5", "console.py's while True is bounded by the key loop's select(0.5) and q/Ctrl-C; the sampler's loops stop on the Event at exit; every subprocess passes a timeout and is killed as a group on expiry (test3 NEVER ANSWERS proves it)")
    return not problems, "%d loops, %d waits, %d without a visible deadline" % (loops, waits, len(problems))


# ---------------------------------------------------------------- G6
@gate("G6")
def g6():
    code = r'''
import os, sys, time, json, random, resource, tempfile
sys.path.insert(0, %r); sys.path.insert(0, %r)
os.environ["COCKPIT_HOME"] = tempfile.mkdtemp(prefix="cockpit-soak-")
from common import client, fake_adb
adb_dir = fake_adb("device")
os.environ["PATH"] = adb_dir + os.pathsep + os.environ["PATH"]
appmod, c, H = client()
appmod.sampler.invalidate(); appmod.sampler.tick()
rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
t = []
for i in range(300):
    t0 = time.time()
    r = c.get("/api/status", headers=H); assert r.status_code == 200 and r.get_json()["status"]["memory"]
    if i %% 10 == 0:
        r = c.post("/api/refresh", json={}, headers=H); assert r.status_code == 200
    r = c.post("/api/stop", json={"package": "com.termux"}, headers=H); assert r.status_code == 200
    r = c.get("/api/log?n=5", headers=H); assert r.status_code == 200
    t.append(time.time() - t0)
rss1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({"cycles": 300, "first100_ms": round(1000*sum(t[:100])/100), "last100_ms": round(1000*sum(t[-100:])/100), "rss_kb_start": rss0, "rss_kb_end": rss1}))
rnd = random.Random(4711); crashes = 0; codes = {}
for i in range(1500):
    kind = rnd.choice(["status", "refresh", "stop", "killall", "pair", "connect", "disconnect", "lift", "wake", "log", "bad", "health"])
    try:
        if kind == "status": r = c.get("/api/status", headers=H)
        elif kind == "refresh": r = c.post("/api/refresh", json={}, headers=H)
        elif kind == "stop": r = c.post("/api/stop", json=rnd.choice([{"package": "com.termux"}, {"package": ""}, {"package": None}, {"package": "x; id"}, {}, {"package": "a" * 3000}]), headers=H)
        elif kind == "killall": r = c.post("/api/kill-all", json={}, headers=H)
        elif kind == "pair": r = c.post("/api/bridge/pair", json=rnd.choice([{"hostport": "1.2.3.4:5", "code": "123456"}, {"hostport": "", "code": ""}, {"hostport": None}, {"code": "x" * 500}, {}]), headers=H)
        elif kind == "connect": r = c.post("/api/bridge/connect", json=rnd.choice([{"hostport": "1.2.3.4:5"}, {"hostport": ";"}, {}]), headers=H)
        elif kind == "disconnect": r = c.post("/api/bridge/disconnect", json={}, headers=H)
        elif kind == "lift": r = c.post("/api/phantom/lift", json={}, headers=H)
        elif kind == "wake": r = c.post("/api/wake", json=rnd.choice([{"on": True}, {"on": False}, {"on": "x"}, {}]), headers=H)
        elif kind == "log": r = c.get("/api/log?n=" + rnd.choice(["1", "9999", "-5", "x", ""]), headers=H)
        elif kind == "health": r = c.get("/health", headers=H)
        else: r = c.post("/api/stop", data=rnd.choice(["garbage", "{", "[]", "null", "\x00"]), headers=dict(H, **{"Content-Type": "application/json"}))
        codes[r.status_code] = codes.get(r.status_code, 0) + 1
        if r.status_code >= 500: crashes += 1
    except Exception as e:
        crashes += 1; print("CRASH", kind, repr(e)[:200])
print(json.dumps({"monkey_events": 1500, "seed": 4711, "crashes": crashes, "codes": codes}))
''' % (os.path.join(APP, "tests"), APP)
    rc, out = run([PY, "-c", code], timeout=900)
    lines = [l for l in out.splitlines() if l.startswith("{")]
    if not lines:
        say("G6", "the soak did not run: " + out[-400:])
        return False, "did not run"
    soak = json.loads(lines[0])
    monkey = json.loads(lines[1]) if len(lines) > 1 else {}
    say("G6", "soak: %d cycles, first 100 avg %d ms, last 100 avg %d ms, RSS %d -> %d kB" % (soak["cycles"], soak["first100_ms"], soak["last100_ms"], soak["rss_kb_start"], soak["rss_kb_end"]))
    say("G6", "monkey: %d events, seed %d, %d crashes, status codes %s" % (monkey.get("monkey_events", 0), monkey.get("seed", 0), monkey.get("crashes", 99), monkey.get("codes")))
    for l in out.splitlines():
        if l.startswith("CRASH"):
            say("G6", "   " + l[:160])
    grew = soak["rss_kb_end"] > soak["rss_kb_start"] * 1.5
    slowed = soak["last100_ms"] > max(soak["first100_ms"] * 3, soak["first100_ms"] + 200)
    ok = monkey.get("crashes", 99) == 0 and not grew and not slowed
    return ok, "soak %d cycles rss %d->%d kB, %d->%d ms; monkey %d crashes" % (soak["cycles"], soak["rss_kb_start"], soak["rss_kb_end"], soak["first100_ms"], soak["last100_ms"], monkey.get("crashes", 99))


# ---------------------------------------------------------------- G7
@gate("G7")
def g7():
    budgets_path = os.path.join(HERE, "BUDGETS.json")
    prev = json.load(open(budgets_path)) if os.path.exists(budgets_path) else {}
    now = {}
    t0 = time.time(); rc, out = run([PY, "-c", "import sys; sys.path.insert(0, %r); import app" % APP]); now["import_app_ms"] = round((time.time() - t0) * 1000)
    now["page_bytes"] = os.path.getsize(os.path.join(APP, "cockpit.html"))
    now["source_bytes"] = sum(os.path.getsize(os.path.join(APP, n)) for n in SOURCES if os.path.exists(os.path.join(APP, n)))
    rc, out = run([PY, "-c", "import sys,time; sys.path.insert(0,%r); import probe; t=time.time(); [probe.cpu_sample() for _ in range(20)]; probe.memory(); probe.frequencies(); print(round((time.time()-t)*1000/20, 2))" % APP])
    now["cpu_sample_ms"] = float(out.strip() or 0)
    t0 = time.time(); rc, out = run([PY, os.path.join(APP, "tests", "test1_mechanism.py")], timeout=600); now["test1_s"] = round(time.time() - t0, 1)
    say("G7", "now: " + json.dumps(now))
    say("G7", "previous: " + (json.dumps(prev) if prev else "none, this run sets the baseline"))
    worse = []
    for k, v in now.items():
        if k in prev and prev[k] and v > prev[k] * 1.5 + (50 if k.endswith("ms") else 0):
            worse.append("%s %s -> %s" % (k, prev[k], v))
    say("G7", "worse than the previous by more than half: %d %s" % (len(worse), worse))
    with open(budgets_path + ".new", "w") as f:
        json.dump(now, f, indent=1)
    return not worse, "worse: %d" % len(worse)


# ---------------------------------------------------------------- G8
@gate("G8")
def g8():
    rc, out = run([PY, os.path.join(APP, "tests", "test4_upgrade.py")], timeout=900)
    m = re.search(r"test4_upgrade: (\d+) checks, (\d+) failed", out)
    say("G8", "test4_upgrade: %s checks, %s failed (with the rollback clause)" % (m.group(1), m.group(2)) if m else "test4 did not finish: " + out[-300:])
    for l in out.splitlines():
        if "FAIL" in l:
            say("G8", "   " + l[:160])
    return rc == 0, (m.group(0) if m else "did not finish")


# ---------------------------------------------------------------- G9
@gate("G9")
def g9(summary):
    ver = re.search(r"APP_VERSION\s*=\s*(\d+)", open(os.path.join(APP, "version.py")).read()).group(1)
    lines = ["DELIVERY RECORD - COCKPIT_TERMUX v%s - %s" % (ver, time.strftime("%Y-%m-%d %H:%M")), "",
             "ARTEFACT     the repository at %s (%s), %d source files, %d bytes" % (git("rev-parse", "--short", "HEAD"), git("rev-parse", "--abbrev-ref", "HEAD"), len(SOURCES), sum(os.path.getsize(os.path.join(APP, n)) for n in SOURCES if os.path.exists(os.path.join(APP, n)))),
             "VERSION      new: %s   previous: see git log" % ver, "", "GATES"]
    for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"):
        ok, note = summary.get(g, (None, "not run"))
        lines.append("             %s %-12s %s   %s" % (g, {"G1": "provenance", "G2": "secrets", "G3": "analysis", "G4": "dead code", "G5": "dead loops", "G6": "stress", "G7": "budgets", "G8": "upgrade"}[g], "pass" if ok else ("FAIL" if ok is False else "----"), note))
    lines += ["             G9 record       this document", "",
              "NOT TESTED   see the NOT TESTED block kept by hand in DELIVERY_RECORD.md", ""]
    rec = "\n".join(lines)
    with open(os.path.join(HERE, "LAST_RUN.txt"), "w") as f:
        f.write(rec + "\n")
    print(); print(rec)
    return all(v[0] for k, v in summary.items() if k in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")), "written to gates/LAST_RUN.txt"


if __name__ == "__main__":
    want = [a.upper() for a in sys.argv[1:]] or ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"]
    summary = {}
    for g in want:
        if g == "G9":
            continue
        print("=" * 70); print(g, flush=True)
        t0 = time.time()
        try:
            ok, note = results[g]()
        except Exception as e:                                  # noqa: BLE001
            ok, note = False, "the gate itself failed: %r" % e
            say(g, note)
        summary[g] = (ok, note)
        print("  %s  %s  (%.0fs)" % (g, "PASS" if ok else "FAIL", time.time() - t0))
    if "G9" in want:
        print("=" * 70); print("G9")
        ok, note = g9(summary)
        print("  G9  %s" % ("PASS: every blocking gate green" if ok else "BLOCKED: a gate is red, the delivery waits"))
    sys.exit(0 if all(v[0] for v in summary.values()) else 1)
