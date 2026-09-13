"""
selfupdate.py  --  check what is installed against what GitHub has, and
update in place on confirmation. Copied verbatim from KEYRING_TERMUX (13.9.2026).

This is the U key in the console: check, print the installed version and
the available one, wait for a yes, then pull and restart. It never updates
without that yes, and it never guesses at a version number -- both numbers
come from reading version.py, the local file and the one on origin/main,
never from a changelog or a commit count.

The three functions are deliberately separate rather than one big
"do the update" call, so the console can show the check result BEFORE
asking for confirmation, per Marko's own ask: check, print, then confirm.
"""

import os
import re
import subprocess
import sys

import version as local_version

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE = "origin"
BRANCH = "main"
GIT_TIMEOUT = 20
PIP_TIMEOUT = 300

_VERSION_RE = re.compile(r"APP_VERSION\s*=\s*(\d+)")


class UpdateError(Exception):
    """Raised with a message safe to show directly to the person."""


def is_git_checkout():
    return os.path.isdir(os.path.join(HERE, ".git"))


def installed_version():
    return local_version.APP_VERSION


def _run(args, timeout):
    try:
        return subprocess.run(args, cwd=HERE, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        raise UpdateError(f"{' '.join(args[:2])} did not answer in {timeout}s "
                          f"-- check the network and try again.")
    except FileNotFoundError:
        raise UpdateError(f"'{args[0]}' is not installed.")


def check_remote():
    """Fetch, then read version.py off origin/main without touching the
    working tree. Returns {installed, latest, up_to_date, behind}.

    behind is the commit count between HEAD and origin/main -- a version
    number can be unchanged while there is nothing to pull (nothing has
    landed since), which is a different fact from "up to date because I
    checked and there IS a newer number and it matches what I already have".
    """
    if not is_git_checkout():
        raise UpdateError(f"{HERE} is not a git checkout, cannot self-update. "
                          f"Reinstall with the install script instead.")

    fetch = _run(["git", "fetch", "--quiet", REMOTE, BRANCH], GIT_TIMEOUT)
    if fetch.returncode != 0:
        raise UpdateError("could not reach GitHub: " +
                          (fetch.stderr or "unknown git error").strip().splitlines()[-1])

    show = _run(["git", "show", f"{REMOTE}/{BRANCH}:version.py"], GIT_TIMEOUT)
    if show.returncode != 0:
        raise UpdateError("could not read version.py from " + REMOTE + "/" + BRANCH)

    m = _VERSION_RE.search(show.stdout)
    if not m:
        raise UpdateError("origin's version.py does not have a readable APP_VERSION")
    latest = int(m.group(1))

    behind = _run(["git", "rev-list", "--count", f"HEAD..{REMOTE}/{BRANCH}"], GIT_TIMEOUT)
    behind_n = int(behind.stdout.strip()) if behind.returncode == 0 and behind.stdout.strip().isdigit() else None

    installed = installed_version()
    return {
        "installed": installed,
        "latest": latest,
        "up_to_date": latest <= installed and (behind_n == 0 if behind_n is not None else True),
        "behind": behind_n,
    }


def perform_update():
    """Pull, then refresh dependencies. Raises UpdateError on anything that
    stops the update short; never leaves the working tree half-changed --
    git pull --ff-only either lands cleanly or does not move at all."""
    pull = _run(["git", "pull", "--ff-only"], GIT_TIMEOUT)
    if pull.returncode != 0:
        raise UpdateError("git pull failed: " +
                          (pull.stderr or pull.stdout or "unknown error").strip().splitlines()[-1])

    req = os.path.join(HERE, "requirements.txt")
    if os.path.exists(req):
        pip = _run([sys.executable, "-m", "pip", "install", "--quiet", "-r", req], PIP_TIMEOUT)
        if pip.returncode != 0:
            raise UpdateError("dependencies did not install: " +
                              (pip.stderr or "unknown pip error").strip().splitlines()[-1])

    # a clean single line for the console's flash message, never the raw
    # multi-line git output -- embedded newlines break a status panel built
    # to draw one line, which is exactly what happened the first time this
    # was tested for real: "Updating X..Y\nFast-forward\n..." spilled the
    # box border on a narrow terminal
    summary = (pull.stdout or "").strip().splitlines()
    first = summary[0] if summary else "already at the latest commit"
    return first
