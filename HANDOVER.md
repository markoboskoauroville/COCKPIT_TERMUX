# HANDOVER: COCKPIT_TERMUX (13.9.2026)

## What it is

The phone's health on one page, and the hand on it: the CPU number made from the cores' idle
counters, RAM and swap from /proc/meminfo, the clusters' frequencies, battery and wifi through
Termux:API once a minute, and, over the ADB bridge, every process with its memory, force-stop,
kill-all, thermal, the real /proc/stat and the phantom-process limit. Built 13.9.2026 in one session
with the Android companion app (COCKPIT_ANDROID, the status-bar number and the notification).

## Where it runs

    cockpit                     ~/COCKPIT_TERMUX/app.py through the launcher ~/COCKPIT_TERMUX/cockpit,
                                on the PATH as $PREFIX/bin/cockpit and ~/.local/bin/cockpit
    http://127.0.0.1:8860       the page (8860-8875, then any: portpick.py). Loopback only, the
                                guard's three checks on every /api call (localguard.py)
    ~/.cockpit/log.jsonl        the log of actions, 0700 folder, outside the repository
    the shape                   KEYRING_TERMUX: console.py, portpick.py, localguard.py, selfupdate.py
                                copied verbatim and adapted in their first lines

## Decisions of 13.9.2026

- **The CPU number is the idle counters, not /proc/stat.** An app on this phone is denied
  /proc/stat, /proc/loadavg and /proc/uptime (measured from Termux's own shell; the PRoot fakes
  them, which hid this for an hour). `/sys/devices/system/cpu/cpu*/cpuidle/state*/time` is
  readable and is the other side of the same ledger: busy = 1 - idle gained / wall time. When the
  bridge is up the real /proc/stat is read too and both are shown.
- **Killing is the bridge's job.** Android 14+ lets no app kill another (`killBackgroundProcesses`
  is own-package only whatever the target SDK). `am force-stop` over adb is the only kill that
  means anything; the page says so instead of offering a button that does nothing.
- **Two clocks in the sampler.** The idle counters and /proc/meminfo every two seconds on one
  thread; Termux:API, adb and pm on another, because the first version ran them on one clock and
  the CPU number waited five seconds for adb to start its server.
- **Every child process is tracked and killed as a group**, on a timeout and at exit. Test 4 found
  three left behind on quit; Test 3's NEVER ANSWERS proves the deadline. `console.py`'s page
  opener gained `timeout -k 5 30` for the same reason; KEYRING_TERMUX, SHOP_FINDER and
  MAHA_TRANSCRIBE should pull that line.
- **Bounded digit runs in the meminfo parser**: a five-thousand-digit line raised ValueError out
  of Python's int() limit (Test 3, MALFORMED).
- **Port 8860**, the first free hundred-block above the keyring's 8842 (ports.md).
- **Public repository** since 13.9.2026 (Marko: the install line must work without a login); the
  installer clones with plain git, or through `gh` when it is logged in.

## Measured after the record (13.9.2026, later the same day)

The app ran once under Termux's own python (3.14.6), outside the PRoot, through the installed
`cockpit` command (a runit service started it; the PRoot's shell read it over HTTP): the banner,
the page, `/health`, a CPU number (11 %), memory, battery from Termux:API, 105 packages from pm.
So the readers are proven in the app domain, not only in the PRoot whose /proc is partly fake.

## What is left, in order

1. **A real pairing on this phone** (Wireless debugging is a person's screen): the bridge was
   tested against a stand-in adb that answers the way the real one does. The first real
   `pair` + `connect` is the first real Test 2 of section 3.
2. **The page in a real browser at 390 px**: the layout was reasoned, not seen.
3. The Android app opens this page from its notification; the two agree on the CPU number
   because they read the same counters.
4. Labels for packages (`pm` gives names only); a per-app "last used" from usage stats over
   the bridge (`dumpsys usagestats` is large; parse it lazily).
5. The keyring's, finder's and transcriber's `console.py` pull the bounded opener.
