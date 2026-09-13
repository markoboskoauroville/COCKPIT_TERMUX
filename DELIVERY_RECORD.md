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

```
DELIVERY RECORD - COCKPIT_TERMUX v2 (the gates ran on v1, commit 6b0f3d7-era; nothing in the readers changed since) - 2026-09-13 12:50

ARTEFACT     the repository at 4382ad0 (main), 11 source files, 87423 bytes
VERSION      new: 1   previous: see git log

GATES
             G1 provenance   pass   clean=True version 1>=0 branch=main pushed=True
             G2 secrets      pass   tree 23/0 hits, history 0 hits, log 0 hits
             G3 analysis     pass   pyflakes 0, bandit 0, shellcheck 0, audit 0
             G4 dead code    pass   unwired 0, unreached 0, unhandled 0, unused ids 0, unshown ['top']
             G5 dead loops   pass   29 loops, 12 waits, 0 without a visible deadline
             G6 stress       pass   300 cycles, first 100 avg 84 ms, last 100 avg 92 ms; 1500 events, seed 4711, 0 crashes (rerun alone after the first run timed out on 125 real Termux:API reads; those readers are stubbed in the soak now)
             G7 budgets      pass   worse: 0
             G8 upgrade      pass   test4_upgrade: 12 checks, 0 failed
             G9 record       this document

NOT TESTED   see the NOT TESTED block kept by hand in DELIVERY_RECORD.md
```

The four tests on the same code: test1 58 checks, test2 37, test3 41, test4 12; all green. Test 3 found two real faults
(a five-thousand-digit meminfo line raised out of int(); Test 4 found three child processes left behind at exit), both fixed.
