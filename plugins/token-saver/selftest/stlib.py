"""Shared self-test types and helpers (imported by selftest.py and cases.py)."""
import json
import os


class Case:
    def __init__(self, mod, name, script, fixture, check, env=None, setup=None,
                 max_ms=None):
        self.mod, self.name, self.script, self.fixture = mod, name, script, fixture
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
