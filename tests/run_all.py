#!/usr/bin/env python3
"""The four tests, in order, each in its own process (four-tests.md: if one fails, run all four again)."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
results = {}
for name in ("test1_mechanism", "test2_real", "test3_ugly", "test4_upgrade"):
    print("=" * 70); print(name); print("=" * 70, flush=True)
    p = subprocess.run([sys.executable, os.path.join(HERE, name + ".py")], timeout=1200)
    results[name] = p.returncode
print()
for k, v in results.items():
    print("  %-18s %s" % (k, "ok" if v == 0 else "FAILED (%d)" % v))
sys.exit(1 if any(results.values()) else 0)
