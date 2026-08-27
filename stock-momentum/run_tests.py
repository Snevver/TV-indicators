#!/usr/bin/env python3
"""Run every test_*.py under bot/ and web/. `python run_tests.py`.

Each test file is a plain-assert script with its own __main__ runner and no
framework, so this just shells out to each one in its own directory (they
`import momentum_bot` / `import config` relative to where they live) and adds up
the exit codes. Anything that needs a package it does not have prints "skip" and
exits 0.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable

files = sorted(p for d in ("bot", "web") for p in (HERE / d).glob("test_*.py"))
if not files:
    sys.exit("no test files found")

failed = []
for f in files:
    print(f"\n=== {f.parent.name}/{f.name} " + "=" * (40 - len(f.name)), flush=True)
    rc = subprocess.run([PY, f.name], cwd=f.parent).returncode
    if rc != 0:
        failed.append(f"{f.parent.name}/{f.name}")

print("\n" + "=" * 52)
if failed:
    print("FAILED: " + ", ".join(failed))
    sys.exit(1)
print(f"all {len(files)} test files passed")
