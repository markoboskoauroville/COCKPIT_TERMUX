"""
console.py  --  the terminal side of the Cockpit.

Copied verbatim from KEYRING_TERMUX/console.py (13.9.2026): the logo, the name and the banner line
changed, nothing else. Fix it there and pull it here.

Rebuilt 4.9.2026 to match MAHA_COMMUTE's own server console
(day-commute's `main()`), after the previous design -- a live-redrawing
box dashboard with fixed-width bordered panels -- silently lost most of
its own KEYS row on a narrow Termux screen. A panel built to a fixed
inner width truncates whatever does not fit, and on a ~40 column phone
terminal that meant "[Q] quit" was the only key left on screen; O, U, R
and C were still bound, just invisible.

MAHA_COMMUTE never had that failure mode, because it never draws a box.
It prints a handful of plain lines once, lets the terminal scroll and
wrap the way terminals already know how to, and reacts to key presses
by printing a NEW line rather than repainting an old one. There is no
width this can silently lose content to.

    q            quit
    o            open the page again
    u            check for an update, confirm, then update and restart
    r            restart

DEGRADES HONESTLY. If stdout is not a terminal, there is no key to
press, so it prints the address and serves, exactly as MAHA_COMMUTE does.
"""

import os
import shutil
import subprocess
import sys
import threading
import time

# same palette the app itself and the rest of this server use, so a
# person moving between the browser tab and the terminal sees one look
AMBER = "\033[38;5;214m"
SAND = "\033[38;5;223m"
SLATE = "\033[38;5;245m"
RED = "\033[38;5;203m"
OFF = "\033[0m"

LOGO = [
    " ██████╗ ██████╗  ██████╗██╗  ██╗██████╗ ██╗████████╗",
    "██╔════╝██╔═══██╗██╔════╝██║ ██╔╝██╔══██╗██║╚══██╔══╝",
    "██║     ██║   ██║██║     █████╔╝ ██████╔╝██║   ██║   ",
    "██║     ██║   ██║██║     ██╔═██╗ ██╔═══╝ ██║   ██║   ",
    "╚██████╗╚██████╔╝╚██████╗██║  ██╗██║     ██║   ██║   ",
    " ╚═════╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝   ╚═╝   ",
]


def w(s, colour, enabled=True):
    return f"{colour}{s}{OFF}" if enabled else s


def say(line=""):
    print(line, flush=True)


CHROME = "com.android.chrome"
_HAS_PKG = {}


def has_package(pkg):
    """Is an Android package installed? `pm list packages` answers from Termux's shell and from
    inside the PRoot (termux-proot-working.md §3). Cached: a second per call, and the answer does
    not change while the app runs."""
    if pkg not in _HAS_PKG:
        try:
            r = subprocess.run(["pm", "list", "packages", pkg], capture_output=True, text=True, timeout=10)
            _HAS_PKG[pkg] = ("package:" + pkg) in r.stdout.split()
        except Exception:
            _HAS_PKG[pkg] = False
    return _HAS_PKG[pkg]


def open_page(target):
    """Chrome, whatever the phone's default browser is (Marko, 13.9.2026): termux-open-url takes an
    app package as its second argument. Without Chrome, the default browser; on a Mac, open; on
    Linux, xdg-open. Bounded by timeout(1): a Termux:API call that waits on an app that never
    answers is an orphan Android counts against the phantom-process limit (termux-proot-working.md
    §3). `target` is a port or a whole URL. Returns True when something was started."""
    url = target if str(target).startswith("http") else f"http://127.0.0.1:{target}"
    chain = []
    if shutil.which("termux-open-url"):
        if has_package(CHROME):
            chain.append(["termux-open-url", url, CHROME])
        chain.append(["termux-open-url", url])
    for other in ("open", "xdg-open"):
        if shutil.which(other):
            chain.append([other, url])
    for cmd in chain:
        if shutil.which("timeout"):
            cmd = ["timeout", "-k", "5", "30"] + cmd
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except Exception:
            continue
    return False


def quiet_flask():
    """Werkzeug shouts a red block about development servers. Read as
    broken, it makes every visit feel like an incident. This binds to
    127.0.0.1 only, so the warning's actual concern does not apply."""
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    try:
        import flask.cli
        flask.cli.show_server_banner = lambda *a, **k: None
    except Exception:
        pass
    try:
        import werkzeug.serving as ws
        ws._log = lambda *a, **k: None
    except Exception:
        pass


def serve(app, host, port):
    """Waitress, thread-pooled and pure Python (modules/termux-app.md §3); the dev server, with a
    printed word, when waitress is not installed. Both bind with SO_REUSEADDR."""
    try:
        import waitress
        waitress.serve(app, host=host, port=port, threads=6, _quiet=True, ident="Cockpit")
    except ImportError:
        say("  waitress is not installed (pip install waitress): the development server for now")
        app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)


def is_interactive():
    return sys.stdout.isatty() and sys.stdin.isatty()


def _print_banner(port, colour, snap):
    for row in LOGO:
        say(w(row, AMBER, colour))
    say()
    say("  " + w("Cockpit \u00b7 the phone's health, and the hand on it", SAND, colour) + "   \u00b7   " +
        w(f"http://127.0.0.1:{port}", SLATE, colour))
    s = snap() if snap else {}
    say("  version " + str(s.get("version", "?")) + "   \u00b7   " + w(str(s.get("line", "")), SLATE, colour))
    say()


def _print_keys(colour):
    say("  " + w("q", AMBER, colour) + " quit   " +
        w("o", AMBER, colour) + " open page   " +
        w("u", AMBER, colour) + " check for update   " +
        w("r", AMBER, colour) + " restart")
    try:
        cols = shutil.get_terminal_size((40, 20)).columns
    except Exception:
        cols = 40
    say(w("\u0950" + "\u2500" * max(cols - 3, 0), AMBER, colour))


def run(app, host, port, snapshot=None, note=None, on_check_update=None, on_perform_update=None):
    """Serve, printing plain lines rather than drawing a box.

    Returns "quit" or "restart". on_check_update() -> dict,
    on_perform_update() -> str; both may raise, and a failure is printed
    as one more plain line rather than crashing the console.
    """
    quiet_flask()
    colour = is_interactive()

    if note:
        say(note)
    _print_banner(port, colour, snapshot)

    if not is_interactive():
        say(f"Cockpit \u2014 http://127.0.0.1:{port}")
        serve(app, host, port)
        return "quit"

    _print_keys(colour)

    threading.Thread(target=lambda: serve(app, host, port), daemon=True).start()
    threading.Timer(1.0, open_page, args=(port,)).start()

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    # set while an update is offered; the very next keypress answers that
    # question instead of being read as a command, so a stray key afterwards
    # cannot start (or skip) an update by accident
    awaiting_confirm = [False]
    pending_check = [None]

    def handle_update_check():
        say()
        say("  checking for an update\u2026")
        try:
            info = on_check_update()
        except Exception as e:                                   # noqa: BLE001
            say("  " + w("could not check: " + str(e), RED, colour))
            return
        if info["up_to_date"]:
            say("  " + w(f"v{info['installed']} is already the latest version", SLATE, colour))
            return
        say("  " + w(f"v{info['installed']} installed", SAND, colour) +
            "   \u2192   " + w(f"v{info['latest']} available", AMBER, colour))
        say("  press " + w("y", AMBER, colour) + " to update, any other key cancels")
        pending_check[0] = info
        awaiting_confirm[0] = True

    def handle_update_confirm(ch):
        info = pending_check[0]
        awaiting_confirm[0] = False
        if ch != "y":
            say("  update canceled")
            return None
        say(f"  updating v{info['installed']} \u2192 v{info['latest']}\u2026")
        say("  pulling\u2026")
        try:
            msg = on_perform_update()
        except Exception as e:                                   # noqa: BLE001
            say("  " + w("update failed: " + str(e), RED, colour))
            return None
        say("  " + w(msg, SLATE, colour))
        say("  " + w(f"updated to v{info['latest']}, restarting\u2026", AMBER, colour))
        time.sleep(1.0)
        return "restart"

    action = "quit"
    try:
        tty.setcbreak(fd)
        while True:
            r, _, _ = select.select([fd], [], [], 0.5)
            if not r:
                continue
            ch = os.read(fd, 1).decode(errors="ignore").lower()

            if awaiting_confirm[0]:
                result = handle_update_confirm(ch)
                if result:
                    action = result
                    break
                continue

            if ch in ("q", "\x03", "\x04"):
                action = "quit"
                break
            if ch == "r":
                say("  restarting\u2026")
                action = "restart"
                break
            if ch == "o":
                ok = open_page(port)
                say("  " + ("opening the browser" if ok else
                            w("no way to open a browser from here", RED, colour)))
            elif ch == "u" and on_check_update:
                handle_update_check()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    if action == "quit":
        say(w("  stopped.", SLATE, colour))
    return action
