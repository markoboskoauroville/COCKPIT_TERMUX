"""
version.py  --  the single number everything else reads.

One whole number per modules/versioning.md: v1, v2, v3, never a dot. Every change, however small, is
a new number. Bumped by hand on every commit that touches this app. Kept in its own file so
selfupdate.py can read it off origin/main without importing app.py.

v1: 13.9.2026, the first cockpit.
"""

APP_VERSION = 1
