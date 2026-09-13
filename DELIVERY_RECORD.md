# DELIVERY RECORD, COCKPIT_TERMUX

The nine gates (modules/delivery-gate.md), run on the phone with `python3 gates/run_gates.py`.
The last run's counts are in `gates/LAST_RUN.txt` (ignored by git) and pasted below at each
delivery. **The NOT TESTED block is written by hand and is the most valuable part.**

## v1, 13.9.2026

NOT TESTED   a real Wireless-debugging pairing and a real `am force-stop` on this phone (the bridge
             ran against a stand-in adb that answers like the real one; the parsers ran on real
             dumpsys output captured from this phone); the page in a real browser at 390 px; the
             page's live polling for an hour (the soak is Flask's test client, 300 cycles);
             Termux:Boot; waitress under load; a phone without Termux:API (battery and wifi then
             stay dim, by design, unmeasured); mutation testing

ACCEPTED     G1's "built by CI" is not met: there is no CI on this repository; the artefact is the
             repository at a commit. The middle band of delivery-gate.md §12.

KNOWN        the wifi dial stays dim on this phone until Termux:API is given the Location
             permission (it answers <unknown ssid> and rssi -127 without it)

GATES_PASTE
