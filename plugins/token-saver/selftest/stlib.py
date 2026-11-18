"""Shared self-test types and helpers (imported by selftest.py and cases.py)."""
import json
import os
import sys

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)


class Case:
    """script is relative to the plugin root (hooks/x.py or lib/ts_cli.py).
    fixture is a file in fixtures/ fed on stdin (None = empty stdin).
    args replaces the default ['--dry-run']."""

    def __init__(self, mod, name, script, fixture, check, env=None, setup=None,
                 max_ms=None, args=None):
        self.mod, self.name, self.script, self.fixture = mod, name, script, fixture
        self.args = args
        self.check, self.env, self.setup, self.max_ms = check, env or {}, setup, max_ms


CASES: list[Case] = []


def register(*cases):
    CASES.extend(cases)


def read_jsonl(home, name):
    p = os.path.join(home, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def read_json(home, name):
    try:
        with open(os.path.join(home, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def in_home(home, fn, *a, **kw):
    """Run fn with TOKEN_SAVER_HOME=home (for setup/check code that imports the lib)."""
    import sys
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)
    old = os.environ.get("TOKEN_SAVER_HOME")
    os.environ["TOKEN_SAVER_HOME"] = home
    try:
        return fn(*a, **kw)
    finally:
        if old is None:
            os.environ.pop("TOKEN_SAVER_HOME", None)
        else:
            os.environ["TOKEN_SAVER_HOME"] = old
