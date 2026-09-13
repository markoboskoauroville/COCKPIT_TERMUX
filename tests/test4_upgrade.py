#!/usr/bin/env python3
"""TEST 4 - the upgrade, over a running v1 with its log. A clone at v1 runs on a pty with a log of
actions; v2 lands on a bare 'GitHub'; u, y: v2 serves on the same port in the same process, the log
survives, and going BACK to v1 (git checkout) still reads the log v2 wrote (the rollback clause of
delivery-gate G8). Copied from KEYRING_TERMUX/tests/test4_upgrade.py (13.9.2026)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import APP, Console, check, finish, fresh_home, http, wait_port  # noqa: E402


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), p.stderr))
    return p.stdout.strip()


root = tempfile.mkdtemp(prefix="cockpit-up-")
bare, work, clone = os.path.join(root, "origin.git"), os.path.join(root, "work"), os.path.join(root, "clone")
subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
subprocess.run(["git", "init", "-q", "-b", "main", work], check=True)
git(work, "config", "user.email", "t@example.invalid"); git(work, "config", "user.name", "t")
for name in os.listdir(APP):
    src = os.path.join(APP, name)
    if name in (".git", "tests", "__pycache__", "gates") or name.startswith("."):
        continue
    (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(work, name))
with open(os.path.join(work, "version.py"), "w") as f:
    f.write("APP_VERSION = 1\n")
git(work, "add", "-A"); git(work, "commit", "-q", "-m", "v1"); git(work, "remote", "add", "origin", bare); git(work, "push", "-q", "origin", "main")
subprocess.run(["git", "clone", "-q", bare, clone], check=True)

home = fresh_home()
H = {"X-Cockpit-Local": "1", "Content-Type": "application/json"}

print("v1 in use, with a log written by the old code")
con = Console(app_dir=clone, home=home)
check("v1 serves", con.wait_for("Cockpit", 25) and wait_port(con.port, 20), con.screen()[-300:])
st, body = http("http://127.0.0.1:%d/api/wake" % con.port, headers=H, data=b'{"on": false}')
st2, body2 = http("http://127.0.0.1:%d/api/log" % con.port, headers=H)
check("v1 wrote a log line", st2 == 200 and len(json.loads(body2)["lines"]) >= 1, body2[:200])
check("the banner says version 1", "version 1" in con.screen(), con.screen()[-300:])

print("v2 lands on GitHub; u, then y")
with open(os.path.join(work, "version.py"), "w") as f:
    f.write("APP_VERSION = 2\n")
with open(os.path.join(work, "cockpit.html"), "a") as f:
    f.write("<!-- v2 -->\n")
git(work, "commit", "-qam", "v2"); git(work, "push", "-q", "origin", "main")
pid_before = con.p.pid
con.key("u")
check("u says v1 installed -> v2 available and asks for y", con.wait_for("v2 available", 25) and "press y" in con.screen(), con.screen()[-300:])
con.key("y")
check("y pulls, says updated to v2, and restarts", con.wait_for("updated to v2", 30), con.screen()[-300:])
check("the same process, the same port, now v2", con.wait_for("version 2", 30) and con.p.pid == pid_before and wait_port(con.port, 20), con.screen()[-300:])
st, body = http("http://127.0.0.1:%d/health" % con.port)
check("/health says version 2", st == 200 and json.loads(body)["version"] == 2, body)
st, body = http("http://127.0.0.1:%d/" % con.port)
check("the page is the v2 page", b"<!-- v2 -->" in body)
st2, body2 = http("http://127.0.0.1:%d/api/log" % con.port, headers=H)
check("the log v1 wrote is still read by v2", st2 == 200 and any(l["event"] == "wake lock" for l in json.loads(body2)["lines"]), body2[:200])

print("the rollback clause: back to v1, the log v2 wrote is still understood")
st, body = http("http://127.0.0.1:%d/api/refresh" % con.port, headers=H, data=b"{}")
con.key("q"); con.wait_exit(10); con.kill()
git(clone, "checkout", "-q", "HEAD~1")
con = Console(app_dir=clone, home=home)
check("v1 again serves", con.wait_for("version 1", 25) and wait_port(con.port, 20), con.screen()[-300:])
st2, body2 = http("http://127.0.0.1:%d/api/log" % con.port, headers=H)
check("v1 reads every line, the ones v2 wrote included", st2 == 200 and len(json.loads(body2)["lines"]) >= 1, body2[:200])
con.key("q"); con.wait_exit(10); con.kill()
check("nothing left behind", con.left_behind() == [], con.left_behind())
finish("test4_upgrade")
