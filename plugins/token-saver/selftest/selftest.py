#!/usr/bin/env python3
"""token-saver self-test: feeds recorded fixtures through each hook script in
--dry-run mode with an isolated TOKEN_SAVER_HOME. No real model calls.

Each mod registers CASES via register(). Doctor imports run_all(); CI runs
tests/run_selftest.py. Python stdlib only.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")


sys.path.insert(0, HERE)
from stlib import CASES, Case, read_json, read_jsonl  # noqa: E402,F401


def run_case(c: Case) -> tuple[bool, str, int]:
    home = tempfile.mkdtemp(prefix="ts-selftest-")
    try:
        if c.setup:
            c.setup(home)
        env = {k: v for k, v in os.environ.items() if not k.startswith("TOKEN_SAVER_")}
        env["TOKEN_SAVER_HOME"] = home
        env["TOKEN_SAVER_SELFTEST_DEPTH"] = str(int(os.environ.get("TOKEN_SAVER_SELFTEST_DEPTH", "0")) + 1)
        env.update(c.env)
        data = ""
        if c.fixture:
            # "{home}/x.json" = a fixture the case's setup wrote into the test home
            fx = c.fixture.replace("{home}", home) if c.fixture.startswith("{home}/") else os.path.join(FIX, c.fixture)
            with open(fx, encoding="utf-8") as f:
                data = f.read().replace("{home}", home)
        t0 = time.time()
        argv = [sys.executable, os.path.join(PLUGIN, c.script)] + (c.args if c.args is not None else ["--dry-run"])
        p = subprocess.run(argv,
                           input=data, capture_output=True, text=True, timeout=30, env=env)
        ms = int((time.time() - t0) * 1000)
        if p.returncode != 0:
            return False, f"exit code {p.returncode}: {p.stderr.strip()[:200]}", ms
        out = None
        if p.stdout.strip():
            try:
                out = json.loads(p.stdout)
            except Exception:
                return False, f"stdout is not valid JSON: {p.stdout[:120]!r}", ms
        ok, why = c.check(out, home, p)
        if ok and c.max_ms and ms > c.max_ms:
            return False, f"too slow: {ms} ms > {c.max_ms} ms", ms
        return ok, why, ms
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


def run_all(mods=None, verbose=True) -> dict:
    load_cases()
    results = {}
    for c in CASES:
        if mods and c.mod not in mods:
            continue
        ok, why, ms = run_case(c)
        results.setdefault(c.mod, []).append({"case": c.name, "ok": ok, "why": why, "ms": ms})
        if verbose:
            print(f"  {'✅' if ok else '❌'} {c.mod:18} {c.name:42} {ms:5d} ms  {'' if ok else why}")
    return results


def load_cases():
    if CASES:
        return
    sys.path.insert(0, HERE)
    import cases  # noqa: F401  (registers CASES)


if __name__ == "__main__":
    as_json = "--json" in sys.argv
    mods = [a for a in sys.argv[1:] if not a.startswith("--")] or None
    res = run_all(mods, verbose=not as_json)
    if as_json:
        print(json.dumps(res))
        sys.exit(0)
    failed = sum(1 for v in res.values() for r in v if not r["ok"])
    total = sum(len(v) for v in res.values())
    print(f"\n{total - failed}/{total} passed")
    sys.exit(1 if failed else 0)
