"""Self-test cases, one block per mod. Every mod built after Doctor adds its
block here in the same commit."""
import os
from stlib import Case, register, read_json, read_jsonl


# ---------------------------------------------------------------- foundation

def _first_run(out, home, p):
    if not out or "token-saver: installed" not in out.get("systemMessage", ""):
        return False, f"expected install message, got {out}"
    cfg = read_json(home, "config.json")
    if not cfg or cfg["handoff"]["threshold_tokens"] != 250000:
        return False, "default config.json not created"
    if "SessionStart" not in (read_json(home, "state.json") or {}).get("events_seen", {}):
        return False, "events_seen not recorded"
    return True, ""


def _inner_noop(out, home, p):
    if out is not None or p.stdout.strip():
        return False, f"expected no output, got {p.stdout[:80]!r}"
    if os.listdir(home):
        return False, f"expected no files written, got {os.listdir(home)}"
    return True, ""


def _corrupt_setup(home):
    with open(os.path.join(home, "config.json"), "w") as f:
        f.write("{ this is not json")


def _corrupt_check(out, home, p):
    h = read_jsonl(home, "health.jsonl")
    if not any(r["kind"] == "config_corrupt" for r in h):
        return False, "config_corrupt not logged to health.jsonl"
    log = open(os.path.join(home, "debug.log")).read()
    if "using defaults" not in log:
        return False, "debug.log does not say defaults were used"
    return True, ""


def _drift_check(out, home, p):
    if out is not None:
        return False, f"expected pass-through, got {out}"
    h = read_jsonl(home, "health.jsonl")
    if not any(r["kind"] == "schema_drift" and r.get("missing") == "source" for r in h):
        return False, f"schema_drift for 'source' not logged: {h}"
    return True, ""


def _crash_setup(home):
    os.makedirs(os.path.join(home, "state.json"))   # save_state() will fail


def _crash_check(out, home, p):
    if out is not None:
        return False, f"expected pass-through after error, got {out}"
    h = read_jsonl(home, "health.jsonl")
    if not any(r["kind"] == "error" and r["mod"] == "foundation" for r in h):
        return False, "error not recorded for the circuit breaker"
    return True, ""


register(
    Case("foundation", "first run: defaults + install notice", "session_probe.py",
         "session_start_startup.json", _first_run, max_ms=300),
    Case("foundation", "TOKEN_SAVER_INNER=1 -> no-op", "session_probe.py",
         "session_start_startup.json", _inner_noop, env={"TOKEN_SAVER_INNER": "1"}, max_ms=300),
    Case("foundation", "corrupt config.json -> defaults, logged", "session_probe.py",
         "session_start_startup.json", _corrupt_check, setup=_corrupt_setup),
    Case("foundation", "missing field -> pass-through + drift", "session_probe.py",
         "session_start_missing_source.json", _drift_check),
    Case("foundation", "hook raises -> exit 0, error recorded", "session_probe.py",
         "session_start_startup.json", _crash_check, setup=_crash_setup),
)
