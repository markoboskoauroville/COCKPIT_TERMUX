"""
version.py  --  the single number everything else reads.

One whole number per modules/versioning.md: v1, v2, v3, never a dot. Every change, however small, is
a new number. Bumped by hand on every commit that touches this app. Kept in its own file so
selfupdate.py can read it off origin/main without importing app.py.

v1: 13.9.2026, the first cockpit.
v2: 13.9.2026, the same day: the bridge remembers its serial, the page opener is bounded, the gates run green.
"""

APP_VERSION = 2
