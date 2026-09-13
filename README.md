# COCKPIT_TERMUX, the phone's health and the hand on it

**One page on the phone that says what the phone is doing, and lets you stop what should not be.**
Marko, 13.9.2026: *"a Termux app displaying the health status … a Flask web page, my cockpit of my
Android phone, where I can kill the apps that are taking memory and resources for nothing, and
other tasks a hacker should have in his phone."*

    cockpit                      the server on 127.0.0.1:8860 and the page; q quits it
    cockpit update               pull the newest version and exit (the u key does it live)

## How to install

```bash
curl -fsSL https://raw.githubusercontent.com/markoboskoauroville/COCKPIT_TERMUX/main/install-termux.sh | bash
```

The repository is public (Marko, 13.9.2026), so the line above needs no login: the installer clones
with plain git, or through `gh` when that is logged in. Optional: `pkg install android-tools` for the bridge,
`pkg install termux-api` plus the Termux:API app for battery and wifi.

## What the page shows

1. **now**: the CPU number (0 to 100, from the idle counters of every core, the same number the
   status-bar app shows), each core's bar, the clusters' GHz, RAM used of total with what is
   available, swap, battery with temperature and current, thermal status, storage, wifi. Every
   dial says when it was last read.
2. **in memory**: every process on the phone with its memory (`dumpsys meminfo`, biggest first),
   a **stop** on each (`am force-stop`, the same as App Info's Force stop), and **kill every
   background process** (`am kill-all`). Without the bridge, only Termux's own processes.
3. **the bridge**: pair and connect Wireless debugging; the phantom-process limit (32 orphaned
   child processes and Android kills the app; Termux with Claude Code has hundreds) and the
   button that lifts it; the wake lock.
4. **what happened**: the log of every action.

## Why a bridge at all

An app on Android 14 or newer cannot kill another app, read `/proc/stat`, or list other apps'
processes: `killBackgroundProcesses()` touches only the caller's own package now, whatever it
targets. The one way a person keeps those rights on an unrooted phone is the shell user, and the
shell user is reachable from Termux through `adb` over Wireless debugging. So: Developer options →
Wireless debugging → *Pair device with pairing code*, type the host:port and the code into the
page, then the connect port. The port changes every time Wireless debugging is switched on; the
pairing survives. Without the bridge the page still shows everything the readers can read.

## What this phone lets an app read (measured 13.9.2026, Nothing Phone (2a), Android 16)

    DENIED     /proc/stat  /proc/loadavg  /proc/uptime  /proc/vmstat  /proc/pressure/*
               anyone else's /proc/<pid>, /sys/class/thermal, /sys/class/power_supply
    READABLE   /proc/meminfo, /proc/cpuinfo, /proc/self/*, /sys/devices/system/cpu/* (cpuidle,
               cpufreq), pm list packages, getprop, Termux:API (battery, wifi; seconds per call)

## The shape

KEYRING_TERMUX's, copied file by file and adapted in the first lines: `console.py` (q / o / u / r,
plain lines), `portpick.py` (8860, then the next fifteen, then any), `localguard.py` (three checks on
every /api call), `selfupdate.py`, `version.py`. Two engines of its own: `probe.py` (the readers)
and `bridge.py` (adb). `tests/` are the four tests, `gates/run_gates.py` the nine gates.

```bash
python3 tests/run_all.py        # the four tests
python3 gates/run_gates.py      # the nine gates, the record in gates/LAST_RUN.txt
```
