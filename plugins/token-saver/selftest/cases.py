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
    Case("foundation", "first run: defaults + install notice", "hooks/session_probe.py",
         "session_start_startup.json", _first_run, max_ms=300),
    Case("foundation", "TOKEN_SAVER_INNER=1 -> no-op", "hooks/session_probe.py",
         "session_start_startup.json", _inner_noop, env={"TOKEN_SAVER_INNER": "1"}, max_ms=300),
    Case("foundation", "corrupt config.json -> defaults, logged", "hooks/session_probe.py",
         "session_start_startup.json", _corrupt_check, setup=_corrupt_setup),
    Case("foundation", "missing field -> pass-through + drift", "hooks/session_probe.py",
         "session_start_missing_source.json", _drift_check),
    Case("foundation", "hook raises -> exit 0, error recorded", "hooks/session_probe.py",
         "session_start_startup.json", _crash_check, setup=_crash_setup),
)


# ---------------------------------------------------------------- switchboard
from stlib import in_home  # noqa: E402

CLI = "lib/ts_cli.py"


def _text(out):
    return (out or {}).get("text", "")


def _cfg(home):
    return read_json(home, "config.json") or {}


def _table(out, home, p):
    t = _text(out)
    missing = [m for m in ("input_router", "effort_optimizer", "subagent_router", "cache_clock", "handoff") if m not in t]
    if missing:
        return False, f"table missing {missing}"
    if any(ord(ch) > 0x2500 and ord(ch) not in range(0x2500, 0x2580) for ch in t):
        return False, "output contains emoji/pictographs"
    return True, ""


def _off(out, home, p):
    if _cfg(home).get("input_router", {}).get("enabled") is not False:
        return False, "input_router not disabled in config.json"
    import token_saver_common as ts
    if in_home(home, ts.is_enabled, "input_router", "s1"):
        return False, "is_enabled still true -> a hook would still act"
    return True, ""


def _pause_setup(home):
    import token_saver_common as ts
    import switchboard
    in_home(home, switchboard.mods_cmd, ["pause"], "session-A")


def _pause_isolated(out, home, p):
    import token_saver_common as ts
    a = in_home(home, ts.is_enabled, "handoff", "session-A")
    b = in_home(home, ts.is_enabled, "handoff", "session-B")
    if a or not b:
        return False, f"pause leaked: session-A enabled={a}, session-B enabled={b}"
    if "paused" not in _text(out):
        return False, "table for session-A does not show paused"
    return True, ""


def _expect_text(*needles, absent=()):
    def check(out, home, p):
        t = _text(out)
        for n in needles:
            if n not in t:
                return False, f"expected {n!r} in output, got {t[:160]!r}"
        for n in absent:
            if n in t:
                return False, f"did not expect {n!r} in output"
        return True, ""
    return check


def _set_ok(out, home, p):
    if _cfg(home).get("input_router", {}).get("model") != "sonnet":
        return False, "input_router.model not saved"
    return True, ""


def _set_int(out, home, p):
    if _cfg(home).get("handoff", {}).get("threshold_tokens") != 300000:
        return False, f"threshold not parsed: {_cfg(home).get('handoff')}"
    return True, ""


def _reset_setup(home):
    import switchboard
    in_home(home, switchboard.mods_cmd, ["off", "handoff"], "s1")


def _reset_unconfirmed(out, home, p):
    if _cfg(home)["handoff"]["enabled"] is not False:
        return False, "reset without confirm changed config"
    return _expect_text("/mods reset confirm")(out, home, p)


def _reset_confirmed(out, home, p):
    if _cfg(home)["handoff"]["enabled"] is not True:
        return False, "reset confirm did not restore defaults"
    return True, ""


def _savings_setup(home):
    import token_saver_common as ts
    in_home(home, ts.log_saving, "input_router", "s1", "/p", 18400, 950, "notes.srt digest")
    in_home(home, ts.log_saving, "input_router", "s1", "/p", 5000, 600, "log.txt digest")
    in_home(home, ts.log_saving, "subagent_router", "s1", "/p", None, None, "find routes -> haiku")
    in_home(home, ts.log_saving, "handoff", "s2", "/p", 252000, 4100, "handoff")


def _savings_totals(out, home, p):
    t = _text(out)
    # 17,450 + 4,400 = 21,850 input_router; 247,900 handoff; total 269,750
    for n in ("21,850", "247,900", "269,750", "n/a", "notes.srt digest", "estimate"):
        if n not in t:
            return False, f"expected {n!r} in /savings output"
    return True, ""


def _savings_session(out, home, p):
    t = _text(out)
    if "247,900" in t or "21,850" not in t:
        return False, "session filter wrong (s2 handoff included or s1 missing)"
    return True, ""


register(
    Case("switchboard", "/mods lists every mod, no emoji", CLI, None, _table, args=["mods", "s1", ""]),
    Case("switchboard", "/mods off input_router -> hooks see off", CLI, None, _off, args=["mods", "s1", "off input_router"]),
    Case("switchboard", "/mods pause only affects its session", CLI, None, _pause_isolated,
         args=["mods", "session-A", ""], setup=_pause_setup),
    Case("switchboard", "unknown mod -> lists valid mods", CLI, None,
         _expect_text("unknown mod", "input_router, effort_optimizer"), args=["mods", "s1", "on nope"]),
    Case("switchboard", "set input_router.model sonnet", CLI, None, _set_ok, args=["mods", "s1", "set input_router.model sonnet"]),
    Case("switchboard", "set enum validation", CLI, None, _expect_text("must be one of"),
         args=["mods", "s1", "set effort_optimizer.mode turbo"]),
    Case("switchboard", "set unknown key -> lists keys", CLI, None, _expect_text("Valid keys", "threshold_tokens"),
         args=["mods", "s1", "set handoff.nope 3"]),
    Case("switchboard", "set int with commas", CLI, None, _set_int, args=["mods", "s1", "set handoff.threshold_tokens 300,000"]),
    Case("switchboard", "reset asks to confirm", CLI, None, _reset_unconfirmed, args=["mods", "s1", "reset"], setup=_reset_setup),
    Case("switchboard", "reset confirm restores defaults", CLI, None, _reset_confirmed,
         args=["mods", "s1", "reset confirm"], setup=_reset_setup),
    Case("switchboard", "/savings empty -> friendly message", CLI, None, _expect_text("nothing saved yet"),
         args=["savings", "s1", ""]),
    Case("switchboard", "/savings totals, n/a, top list", CLI, None, _savings_totals,
         args=["savings", "s1", "all"], setup=_savings_setup),
    Case("switchboard", "/savings session filters", CLI, None, _savings_session,
         args=["savings", "s1", "session"], setup=_savings_setup),
)


# ---------------------------------------------------------------- doctor
import json as _json  # noqa: E402
from stlib import run_script  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXDIR = os.path.join(HERE, "fixtures")
DOCTOR = "hooks/doctor_start.py"
EMPTY_CLAUDE = {"TOKEN_SAVER_CLAUDE_DIR": "/nonexistent-claude-dir"}


def _state_setup(**st):
    def setup(home):
        with open(os.path.join(home, "state.json"), "w") as f:
            _json.dump(st, f)
    return setup


def _update_check(out, home, p):
    msg = (out or {}).get("systemMessage", "")
    for n in ("updated 2.1.300 -> 2.1.327", "self-test passed", "truncated tool_input for Read",
              "status line segments"):
        if n not in msg:
            return False, f"missing {n!r} in notice: {msg[:200]!r}"
    for n in ("Future line", "Old line"):
        if n in msg:
            return False, f"changelog range wrong: {n!r} included"
    st = read_json(home, "state.json") or {}
    if st.get("last_seen_version") != "2.1.327" or not st.get("last_selftest", {}).get("ok"):
        return False, f"state not updated: {st}"
    return True, ""


def _silent(out, home, p):
    if out is not None:
        return False, f"expected no notice, got {out}"
    return True, ""


def _conflict_setup(home):
    cd = os.path.join(home, "fake-claude")
    os.makedirs(os.path.join(cd, "plugins"))
    with open(os.path.join(cd, "plugins", "installed_plugins.json"), "w") as f:
        _json.dump({"version": 2, "plugins": {"read-guard@test": [
            {"scope": "user", "installPath": os.path.join(FIXDIR, "conflict_plugin")}]}}, f)
    with open(os.path.join(cd, "settings.json"), "w") as f:
        _json.dump({"enabledPlugins": {"read-guard@test": True}}, f)
    _state_setup(last_seen_version="2.1.327")(home)


def _conflict_check(out, home, p):
    msg = (out or {}).get("systemMessage", "")
    if "read-guard@test has a PreToolUse hook on Read" not in msg or "Fix:" not in msg:
        return False, f"Read conflict not reported with a fix: {msg[:300]!r}"
    if "also defines /savings" not in msg:
        return False, "duplicate /savings command not reported"
    # reported once: a second session start says nothing new
    p2 = run_script(home, DOCTOR, "session_start_startup.json", env={
        "TOKEN_SAVER_CLAUDE_DIR": os.path.join(home, "fake-claude"),
        "TOKEN_SAVER_FAKE_VERSION": "2.1.327",
        "TOKEN_SAVER_OUR_HOOKS_FILE": os.path.join(FIXDIR, "our_hooks_full.json")})
    if p2.stdout.strip():
        return False, f"conflict reported twice: {p2.stdout[:120]}"
    return True, ""


def _drift_setup(home):
    run_script(home, "hooks/session_probe.py", "session_start_missing_source.json")


def _drift_report(out, home, p):
    t = (out or {}).get("text", "")
    if "schema drift (24h): 1" not in t or "missing source" not in t:
        return False, f"doctor report does not show the drift: {t[-400:]!r}"
    return True, ""


def _fault_setup(home):
    for _ in range(2):
        run_script(home, "selftest/fault_hook.py", "session_start_startup.json")


def _breaker_check(out, home, p):
    msg = (out or {}).get("systemMessage", "")
    if "disabled handoff after 3 errors in this session" not in msg:
        return False, f"no breaker notice on 3rd error: {out}"
    c = (read_json(home, "config.json") or {}).get("handoff", {})
    if c.get("enabled") is not False or c.get("disabled_by") != "doctor" or "TimeoutError" not in c.get("reason", ""):
        return False, f"config not auto-disabled with reason: {c}"
    p4 = run_script(home, "selftest/fault_hook.py", "session_start_startup.json")
    if p4.stdout.strip():
        return False, "notice shown again (should be once)"
    import switchboard
    table = in_home(home, switchboard.mods_cmd, [], "fixture-session-1")
    if "off (doctor)" not in table or "reason:" not in table:
        return False, "/mods does not show why"
    on = in_home(home, switchboard.mods_cmd, ["on", "handoff"], "fixture-session-1")
    if (read_json(home, "config.json") or {})["handoff"].get("disabled_by"):
        return False, f"/mods on did not clear disabled_by: {on}"
    return True, ""


def _doctor_crash_check(out, home, p):
    if p.returncode != 0 or out is not None:
        return False, f"doctor failure leaked: rc={p.returncode} out={out}"
    if not any(r["kind"] == "error" and r["mod"] == "doctor" for r in read_jsonl(home, "health.jsonl")):
        return False, "doctor error not logged"
    return True, ""


register(
    Case("doctor", "version change -> self-test + changelog", DOCTOR, "session_start_startup.json", _update_check,
         setup=_state_setup(last_seen_version="2.1.300"),
         env={**EMPTY_CLAUDE, "TOKEN_SAVER_FAKE_VERSION": "2.1.327",
              "TOKEN_SAVER_CHANGELOG_FILE": os.path.join(FIXDIR, "changelog.md")}),
    Case("doctor", "same version, no conflicts -> silent", DOCTOR, "session_start_startup.json", _silent,
         setup=_state_setup(last_seen_version="2.1.327"),
         env={**EMPTY_CLAUDE, "TOKEN_SAVER_FAKE_VERSION": "2.1.327"}, max_ms=300),
    Case("doctor", "dummy plugin on Read -> conflict + fix, once", DOCTOR, "session_start_startup.json",
         _conflict_check, setup=_conflict_setup,
         env={"TOKEN_SAVER_FAKE_VERSION": "2.1.327", "TOKEN_SAVER_CLAUDE_DIR": "{home}/fake-claude",
              "TOKEN_SAVER_OUR_HOOKS_FILE": os.path.join(FIXDIR, "our_hooks_full.json")}),
    Case("doctor", "missing field -> drift shown in /mods doctor", "lib/ts_cli.py", None, _drift_report,
         args=["mods", "s1", "doctor"], setup=_drift_setup,
         env={**EMPTY_CLAUDE, "TOKEN_SAVER_FAKE_VERSION": "2.1.327"}),
    Case("doctor", "mod throws 3x -> disabled, one notice", "selftest/fault_hook.py", "session_start_startup.json",
         _breaker_check, setup=_fault_setup),
    Case("doctor", "doctor itself fails -> session unaffected", DOCTOR, "session_start_startup.json",
         _doctor_crash_check, setup=_crash_setup, env={**EMPTY_CLAUDE, "TOKEN_SAVER_FAKE_VERSION": "2.1.327"}),
)
