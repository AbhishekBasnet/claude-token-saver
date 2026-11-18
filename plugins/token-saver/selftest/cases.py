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


# ---------------------------------------------------------------- handoff
import time as _time  # noqa: E402


def _transcript(ctx_tokens, sidechain_ctx=None):
    def setup(home):
        rows = [
            {"type": "user", "message": {"role": "user", "content": "hi"}, "origin": {"kind": "human"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
             "usage": {"input_tokens": 10, "cache_read_input_tokens": ctx_tokens - 2010, "cache_creation_input_tokens": 2000,
                       "output_tokens": 50}}},
        ]
        if sidechain_ctx:
            rows.append({"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": [],
                         "usage": {"input_tokens": sidechain_ctx, "output_tokens": 1}}})
        with open(os.path.join(home, "transcript.jsonl"), "w") as f:
            for r in rows:
                f.write(_json.dumps(r) + "\n")
    return setup


def _warned(ctx_k):
    def check(out, home, p):
        msg = (out or {}).get("systemMessage", "")
        if f"context at {ctx_k}k tokens" not in msg or "/handoff" not in msg:
            return False, f"expected warning at {ctx_k}k, got {out}"
        return True, ""
    return check


def _warn_repeat_setup(home):
    _transcript(252_000)(home)
    run_script(home, "hooks/handoff_stop.py", "stop_main.json")


def _warn_step_setup(home):
    _warn_repeat_setup(home)
    _transcript(303_000)(home)


def _latest_setup(age_s=0, project="/tmp/project-a"):
    def setup(home):
        import handoff
        d = in_home(home, handoff.handoff_dir, project or os.getcwd())
        os.makedirs(d, exist_ok=True)
        lp = os.path.join(d, "LATEST.md")
        with open(os.path.join(HERE, "fixtures", "handoff_doc.md")) as src, open(lp, "w") as f:
            f.write(src.read())
        if age_s:
            t = _time.time() - age_s
            os.utime(lp, (t, t))
    return setup


def _clear_loaded(out, home, p):
    ctx = ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
    if not ctx.startswith("[Handoff] Continuing from previous session") or "KeyError: 'id'" not in ctx:
        return False, f"handoff not injected: {str(out)[:200]}"
    import handoff
    d = in_home(home, handoff.handoff_dir, "/tmp/project-a")
    files = os.listdir(d)
    if "LATEST.md" in files or not any(f.startswith("loaded-") for f in files):
        return False, f"LATEST.md not renamed: {files}"
    p2 = run_script(home, "hooks/handoff_start.py", "session_start_clear.json")
    if p2.stdout.strip():
        return False, "loaded twice"
    return True, ""


def _startup_offer(out, home, p):
    msg = (out or {}).get("systemMessage", "")
    if "/handoff load" not in msg or (out or {}).get("hookSpecificOutput"):
        return False, f"expected an offer only (no injection), got {out}"
    return True, ""


def _save_check(out, home, p):
    t = (out or {}).get("text", "")
    if not (out or {}).get("ok") or "Handoff saved:" not in t or "252,000" not in t or "/clear" not in t:
        return False, f"unexpected: {t[:200]}"
    if "sections missing" in t:
        return False, "fixture doc has all sections but a warning was shown"
    import handoff
    d = in_home(home, handoff.handoff_dir, os.getcwd())
    files = os.listdir(d)
    if "LATEST.md" not in files or len(files) != 2:
        return False, f"expected <stamp>.md + LATEST.md, got {files}"
    rows = read_jsonl(home, "savings.jsonl")
    if not rows or rows[-1]["mod"] != "handoff" or rows[-1]["tokens_before"] != 252000 \
            or not (0 < rows[-1]["tokens_after"] < 1000):
        return False, f"saving not logged right: {rows}"
    return True, ""


def _save_bad(out, home, p):
    if (out or {}).get("ok") or "not saved" not in (out or {}).get("text", ""):
        return False, f"non-markdown reply should be refused: {out}"
    return True, ""


def _load_cli(out, home, p):
    o = out or {}
    if "Loaded handoff" not in o.get("text", "") or not (o.get("context") or "").startswith("[Handoff]"):
        return False, f"unexpected: {o}"
    return True, ""


def _save_setup(home):
    pass


register(
    Case("handoff", "Stop below threshold -> silent", "hooks/handoff_stop.py", "stop_main.json", _silent,
         setup=_transcript(120_000), max_ms=300),
    Case("handoff", "Stop at 252k -> warning", "hooks/handoff_stop.py", "stop_main.json", _warned(252),
         setup=_transcript(252_000)),
    Case("handoff", "warned once, same size -> silent", "hooks/handoff_stop.py", "stop_main.json", _silent,
         setup=_warn_repeat_setup),
    Case("handoff", "+50k later -> warns again", "hooks/handoff_stop.py", "stop_main.json", _warned(303),
         setup=_warn_step_setup),
    Case("handoff", "sub-agent Stop / sidechain ignored", "hooks/handoff_stop.py", "stop_subagent.json", _silent,
         setup=_transcript(100_000, sidechain_ctx=900_000)),
    Case("handoff", "/clear -> LATEST injected + renamed, once", "hooks/handoff_start.py",
         "session_start_clear.json", _clear_loaded, setup=_latest_setup()),
    Case("handoff", "startup, fresh handoff -> offer only", "hooks/handoff_start.py",
         "session_start_startup_a.json", _startup_offer, setup=_latest_setup()),
    Case("handoff", "startup, handoff > 24h old -> silent", "hooks/handoff_start.py",
         "session_start_startup_a.json", _silent, setup=_latest_setup(age_s=25 * 3600)),
    Case("handoff", "no handoff for project -> nothing", "hooks/handoff_start.py",
         "session_start_clear.json", _silent),
    Case("handoff", "save: files + saving logged", "lib/ts_cli.py", "handoff_doc.md", _save_check,
         args=["handoff-save", "s-handoff", "252000", '{"cache_read_input_tokens": 250000, "output_tokens": 900}']),
    Case("handoff", "save: non-markdown reply refused", "lib/ts_cli.py", "session_start_startup.json", _save_bad,
         args=["handoff-save", "s-handoff", "1000", "{}"]),
    Case("handoff", "/handoff load returns context", "lib/ts_cli.py", None, _load_cli,
         args=["handoff-load", "s-handoff"], setup=_latest_setup(project=None)),
)


def _notes_check(out, home, p):
    import handoff
    d = in_home(home, handoff.handoff_dir, os.getcwd())
    doc = open(os.path.join(d, "LATEST.md")).read()
    i_title = doc.find("# Handoff")
    i_notes = doc.find("## Notes from the user (verbatim, critical)")
    i_goal = doc.find("## Goal")
    if not (0 <= i_title < i_notes < i_goal):
        return False, "notes section not placed right under the title"
    if "> Prod DB password is in 1Password, never commit it" not in doc or "> Deadline Friday" not in doc:
        return False, "notes not verbatim"
    if "sections missing" in (out or {}).get("text", ""):
        return False, "fixture has all sections incl. 'Ask the user first' but a warning was shown"
    return True, ""


def _prompt_notes(out, home, p):
    t = (out or {}).get("text", "")
    if "## Ask the user first" not in t or "Deadline Friday" not in t:
        return False, "prompt lacks ask-first section or the user's notes"
    return True, ""


register(
    Case("handoff", "user notes inserted verbatim under title", "lib/ts_cli.py", "handoff_doc.md", _notes_check,
         args=["handoff-save", "s-handoff", "252000", "{}",
               "Prod DB password is in 1Password, never commit it\nDeadline Friday"]),
    Case("handoff", "prompt carries notes + ask-first section", "lib/ts_cli.py", None, _prompt_notes,
         args=["handoff-prompt", "s-handoff", "Deadline Friday"]),
)


# ---------------------------------------------------------------- cache clock
CLOCK = "hooks/cache_clock_stop.py"


def _clock_transcript(gap_min=None, cache_read=48_000):
    """A transcript whose latest human prompt came gap_min after a previous
    clock file's last_activity, and whose first reply read cache_read tokens."""
    def setup(home):
        now = _time.time()
        prompt_t = now - 5
        ts_iso = _time.strftime("%Y-%m-%dT%H:%M:%S.000Z", _time.gmtime(prompt_t))
        rows = [
            {"type": "user", "timestamp": ts_iso, "origin": {"kind": "human"},
             "message": {"role": "user", "content": "next question"}},
            {"type": "assistant", "timestamp": ts_iso, "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
             "usage": {"input_tokens": 12, "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": 300,
                       "output_tokens": 40}}},
        ]
        with open(os.path.join(home, "transcript.jsonl"), "w") as f:
            for r in rows:
                f.write(_json.dumps(r) + "\n")
        if gap_min is not None:
            os.makedirs(os.path.join(home, "cache"), exist_ok=True)
            with open(os.path.join(home, "cache", "clock-s-handoff.json"), "w") as f:
                _json.dump({"session": "s-handoff", "last_activity": prompt_t - gap_min * 60,
                            "ttl_minutes": 60, "expires_at": prompt_t - gap_min * 60 + 3600}, f)
    return setup


def _clock_written(out, home, p):
    c = read_json(home, "cache/clock-s-handoff.json")
    if not c:
        return False, "clock file not written"
    left = c["expires_at"] - _time.time()
    if not (3590 <= left <= 3600) or c["context_tokens"] != 48_312:
        return False, f"expected full 60 min TTL and ctx 48,312, got {left:.0f}s / {c.get('context_tokens')}"
    if out is not None:
        return False, f"Stop hook must be silent, got {out}"
    return True, ""


def _observed(expect):
    def check(out, home, p):
        rows = [r for r in read_jsonl(home, "savings.jsonl") if r.get("mod") == "cache_clock"]
        if not expect:
            return (not rows, f"expected no entry, got {rows}")
        if len(rows) != 1:
            return False, f"expected one observed entry, got {rows}"
        r = rows[0]
        if r.get("kind") != "observed" or r.get("observed_tokens") != 48_000 \
                or r.get("tokens_before") is not None or r.get("tokens_after") is not None:
            return False, f"entry must be observed-only (no before/after): {r}"
        return True, ""
    return check


def _clock_off_setup(home):
    _clock_transcript()(home)
    import token_saver_common as T
    cfg = in_home(home, T.load_config)
    cfg["cache_clock"]["enabled"] = False
    in_home(home, T.save_config, cfg)


def _clock_absent(out, home, p):
    if read_json(home, "cache/clock-s-handoff.json") or read_json(home, "cache/clock-s-sub.json"):
        return False, "clock file written when it should not be"
    return True, ""


def _ping_restarts(out, home, p):
    c = read_json(home, "cache/clock-s-handoff.json")
    if not c or c.get("source") != "keepwarm" or c["expires_at"] - _time.time() < 3590:
        return False, f"ping did not restart the clock: {c}"
    if c.get("context_tokens") != 48_312:
        return False, "ping lost the context size"
    return True, ""



register(
    Case("cache_clock", "Stop -> clock file with full TTL + ctx", CLOCK, "stop_main.json", _clock_written,
         setup=_clock_transcript(), max_ms=300),
    Case("cache_clock", "warm hit after 25 min gap -> observed, not saved", CLOCK, "stop_main.json",
         _observed(True), setup=_clock_transcript(gap_min=25)),
    Case("cache_clock", "gap under 10 min -> nothing logged", CLOCK, "stop_main.json",
         _observed(False), setup=_clock_transcript(gap_min=4)),
    Case("cache_clock", "gap past TTL (cold) -> nothing logged", CLOCK, "stop_main.json",
         _observed(False), setup=_clock_transcript(gap_min=75)),
    Case("cache_clock", "mod off -> no clock file", CLOCK, "stop_main.json", _clock_absent,
         setup=_clock_off_setup),
    Case("cache_clock", "sub-agent Stop -> ignored", CLOCK, "stop_subagent.json", _clock_absent,
         setup=_clock_transcript()),
)


def _ping_setup_ctx(home):
    _clock_transcript(gap_min=55)(home)
    p = os.path.join(home, "cache", "clock-s-handoff.json")
    c = _json.load(open(p))
    c["context_tokens"] = 48_312
    _json.dump(c, open(p, "w"))


register(
    Case("cache_clock", "keep-warm ping restarts the clock", "lib/ts_cli.py", None, _ping_restarts,
         args=["keepwarm-log", "s-handoff", '{"cache_read_input_tokens": 48000}'], setup=_ping_setup_ctx),
)


# ---------------------------------------------------------------- sub-agent router
ROUTE = "hooks/subagent_route.py"


def _main_transcript(model="claude-opus-5-5"):
    def setup(home):
        rows = [{"type": "user", "origin": {"kind": "human"}, "message": {"role": "user", "content": "go"}},
                {"type": "assistant", "message": {"role": "assistant", "model": model, "content": [],
                 "usage": {"input_tokens": 5, "cache_read_input_tokens": 40000, "cache_creation_input_tokens": 0,
                           "output_tokens": 10}}}]
        with open(os.path.join(home, "transcript.jsonl"), "w") as f:
            for r in rows:
                f.write(_json.dumps(r) + "\n")
    return setup


def _routed(model):
    def check(out, home, p):
        ui = (((out or {}).get("hookSpecificOutput") or {}).get("updatedInput") or {})
        if ui.get("model") != model:
            return False, f"expected model={model}, got {out}"
        if not ui.get("prompt") or not ui.get("description"):
            return False, "updatedInput dropped the original fields"
        if (out.get("hookSpecificOutput") or {}).get("permissionDecision"):
            return False, "must not make a permission decision"
        card = read_json(home, "cache/cards/toolu_route1.json")
        if not card or model not in card["lines"][0]:
            return False, f"card missing or wrong: {card}"
        return True, ""
    return check


def _untouched(out, home, p):
    if out is not None:
        return False, f"expected pass-through, got {out}"
    if read_json(home, "cache/cards/toolu_route1.json"):
        return False, "card written for an untouched call"
    return True, ""


def _route_off_setup(home):
    _main_transcript()(home)
    import token_saver_common as T
    cfg = in_home(home, T.load_config)
    cfg["subagent_router"]["enabled"] = False
    in_home(home, T.save_config, cfg)


def _no_opus_setup(home):
    _main_transcript()(home)
    import token_saver_common as T
    cfg = in_home(home, T.load_config)
    cfg["subagent_router"]["allow_opus"] = False
    in_home(home, T.save_config, cfg)


def _agent_run_setup(home):
    """A routed call happened (session state), then the sub-agent ran on haiku."""
    _main_transcript()(home)
    run_script(home, ROUTE, "pre_agent_explore.json")
    prompt = "Find every API route defined in this repo and list the files and handlers."
    rows = [{"type": "user", "isSidechain": True, "message": {"role": "user", "content": prompt}}]
    for i in range(3):
        rows.append({"type": "assistant", "isSidechain": True, "message": {
            "id": f"msg_{i}", "role": "assistant", "model": "claude-haiku-5-5", "content": [],
            "usage": {"input_tokens": 100, "output_tokens": 1000, "cache_read_input_tokens": 50_000,
                      "cache_creation_input_tokens": 10_000,
                      "cache_creation": {"ephemeral_5m_input_tokens": 10_000, "ephemeral_1h_input_tokens": 0}}}})
    rows.append(dict(rows[-1]))                       # same request id twice: counted once
    with open(os.path.join(home, "agent.jsonl"), "w") as f:
        for r in rows:
            f.write(_json.dumps(r) + "\n")


def _agent_logged(out, home, p):
    rows = [r for r in read_jsonl(home, "savings.jsonl") if r.get("mod") == "subagent_router"]
    if len(rows) != 1:
        return False, f"expected one savings entry, got {rows}"
    r = rows[0]
    # 3 requests: in 300, out 3000, read 150k, write(5m) 30k
    want_opus = (300 * 4 + 3000 * 20 + 150_000 * 0.20 + 30_000 * 4 * 1.25) / 1e6
    want_haiku = (300 * 0.10 + 3000 * 0.50 + 150_000 * 0.01 + 30_000 * 0.10 * 1.25) / 1e6
    if abs(r["usd_main_est"] - want_opus) > 1e-6 or abs(r["usd_actual_est"] - want_haiku) > 1e-6:
        return False, f"cost mismatch: {r}"
    if r["requests"] != 3 or r.get("tokens_before") is not None:
        return False, f"requests or token fields wrong: {r}"
    st = read_json(home, "sessions/s-route.json") or {}
    if st.get("subagent_routes"):
        return False, "route record not cleared after logging"
    return True, ""


def _savings_has_usd(out, home, p):
    t = (out or {}).get("text", "")
    if "subagent_router" not in t or "~$0.23" not in t or "n/a" not in t:
        return False, f"/savings does not show the routed $: {t[:400]}"
    return True, ""


def _savings_usd_setup(home):
    _agent_run_setup(home)
    run_script(home, "hooks/subagent_stop.py", "subagent_stop.json")


register(
    Case("subagent_router", "exploration sub-agent -> haiku", ROUTE, "pre_agent_explore.json", _routed("haiku"),
         setup=_main_transcript(), max_ms=400),
    Case("subagent_router", "Task tool name (-p) -> haiku", ROUTE, "pre_task_explore.json", _routed("haiku"),
         setup=_main_transcript()),
    Case("subagent_router", "security review -> stays on opus", ROUTE, "pre_agent_security.json", _untouched,
         setup=_main_transcript()),
    Case("subagent_router", "explicit model -> untouched", ROUTE, "pre_agent_explicit.json", _untouched,
         setup=_main_transcript()),
    Case("subagent_router", "mod off -> default model", ROUTE, "pre_agent_explore.json", _untouched,
         setup=_route_off_setup),
    Case("subagent_router", "writing code -> sonnet", ROUTE, "pre_agent_code.json", _routed("sonnet"),
         setup=_main_transcript()),
    Case("subagent_router", "unclear -> haiku classifier decides", ROUTE, "pre_agent_unclear.json", _routed("sonnet"),
         setup=_main_transcript(), env={"TOKEN_SAVER_STUB_REPLY": "sonnet"}),
    Case("subagent_router", "classifier fails -> untouched", ROUTE, "pre_agent_unclear.json", _untouched,
         setup=_main_transcript(), env={"TOKEN_SAVER_STUB_FAIL": "timeout"}),
    Case("subagent_router", "main on sonnet: never routes up", ROUTE, "pre_agent_code.json", _untouched,
         setup=_main_transcript("claude-sonnet-5-5")),
    Case("subagent_router", "allow_opus off -> security capped at sonnet", ROUTE, "pre_agent_security.json",
         _routed("sonnet"), setup=_no_opus_setup),
    Case("subagent_router", "SubagentStop -> real usage, $ diff logged", "hooks/subagent_stop.py",
         "subagent_stop.json", _agent_logged, setup=_agent_run_setup),
    Case("subagent_router", "/savings shows routed $", "lib/ts_cli.py", None, _savings_has_usd,
         args=["savings", "s-route", "all"], setup=_savings_usd_setup),
)


def _main_from_start_setup(home):
    """No assistant reply in the transcript yet (first turn of a -p run): the
    model SessionStart reported (sonnet) must be used, not the opus default."""
    open(os.path.join(home, "transcript.jsonl"), "w").close()
    os.makedirs(os.path.join(home, "sessions"), exist_ok=True)
    with open(os.path.join(home, "sessions", "s-route.json"), "w") as f:
        _json.dump({"main_model": "claude-sonnet-5-5"}, f)


register(
    Case("subagent_router", "no reply yet: main model from SessionStart", ROUTE, "pre_agent_code.json", _untouched,
         setup=_main_from_start_setup, env={**EMPTY_CLAUDE}),
)


# ---------------------------------------------------------------- input router
IR = "hooks/input_route.py"


def _ir_setup(prompt="what did they decide about pricing?", files=True):
    def setup(home):
        rows = [{"type": "user", "origin": {"kind": "human"}, "message": {"role": "user", "content": prompt}}]
        with open(os.path.join(home, "transcript.jsonl"), "w") as f:
            for r in rows:
                f.write(_json.dumps(r) + "\n")
        if files:
            with open(os.path.join(home, "notes.md"), "w") as f:      # ~20k tokens est.
                f.write("\n".join(f"Speaker {i % 4}: discussion point {i} about pricing and hiring." for i in range(1400)))
            with open(os.path.join(home, "big.py"), "w") as f:        # ~3k tokens est.
                f.write("\n".join(f"def f{i}(x):\n    return x + {i}\n" for i in range(400)))
            os.makedirs(os.path.join(home, ".git", "logs"), exist_ok=True)
            with open(os.path.join(home, ".git", "logs", "HEAD"), "w") as f:
                f.write("x" * 20000)
    return setup


def _digested(tool_use_id, path_name):
    def check(out, home, p):
        upd = ((out or {}).get("hookSpecificOutput") or {}).get("updatedToolOutput")
        body = upd["file"]["content"] if isinstance(upd, dict) else upd
        if not isinstance(body, str) or not body.startswith("[Input Router] Haiku digest of") or "[stub reply]" not in body:
            return False, f"no digest delivered: {str(out)[:200]}"
        if path_name not in body or "offset/limit" not in body:
            return False, "digest must give the full path and the offset/limit hint"
        rows = [r for r in read_jsonl(home, "savings.jsonl") if r.get("mod") == "input_router"]
        if len(rows) != 1 or not rows[0]["tokens_before"] > rows[0]["tokens_after"]:
            return False, f"saving not logged: {rows}"
        if not read_json(home, f"cache/cards/{tool_use_id}.json"):
            return False, "card not written"
        return True, ""
    return check


def _struct_kept(out, home, p):
    ok, why = _digested("toolu_read2", "review.md")(out, home, p)
    if not ok:
        return ok, why
    upd = out["hookSpecificOutput"]["updatedToolOutput"]
    if not isinstance(upd, dict) or upd.get("type") != "text" or upd["file"].get("filePath", "").endswith("review.md") is False:
        return False, f"structured Read result not kept: {str(upd)[:200]}"
    if upd["file"]["numLines"] != upd["file"]["content"].count("\n") + 1:
        return False, "numLines not updated"
    return True, ""


def _passthrough(out, home, p):
    if out is not None:
        return False, f"expected untouched, got {str(out)[:200]}"
    if [r for r in read_jsonl(home, "savings.jsonl") if r.get("mod") == "input_router"]:
        return False, "saving logged for an untouched read"
    return True, ""


def _timeout_check(out, home, p):
    ok, why = _passthrough(out, home, p)
    if not ok:
        return ok, why
    log = open(os.path.join(home, "debug.log")).read()
    if "digest failed" not in log or "timeout" not in log:
        return False, "timeout not in debug.log"
    return True, ""


def _bypass_setup(home):
    _ir_setup()(home)
    os.makedirs(os.path.join(home, "sessions"), exist_ok=True)
    with open(os.path.join(home, "sessions", "s-read.json"), "w") as f:
        _json.dump({"bypass_once": [os.path.join(home, "notes.md")]}, f)


def _bypass_consumed(out, home, p):
    ok, why = _passthrough(out, home, p)
    if not ok:
        return ok, why
    if (read_json(home, "sessions/s-read.json") or {}).get("bypass_once"):
        return False, "bypass_once not consumed"
    return True, ""


def _mcp_setup(home):
    _ir_setup()(home)
    big = {"issues": [{"id": i, "title": f"Issue {i}: login fails on Safari", "body": "Steps to reproduce " * 12,
                       "assignee": {"name": "Ana", "avatar_url": "https://x/a.png"}, "labels": [], "milestone": None,
                       "attachment": "QUJD" * 300} for i in range(60)]}
    fx = os.path.join(HERE, "fixtures", "post_mcp.json")
    d = _json.load(open(fx))
    d["tool_response"] = [{"type": "text", "text": _json.dumps(big)}]     # MCP results are content blocks
    # run_script reads fixtures from the plugin folder, so stage a copy in home
    with open(os.path.join(home, "post_mcp_filled.json"), "w") as f:
        _json.dump(d, f)


def _mcp_check(out, home, p):
    upd = ((out or {}).get("hookSpecificOutput") or {}).get("updatedMCPToolOutput")
    text = _json.dumps(upd)
    if not isinstance(upd, list) or upd[0].get("type") != "text" \
            or not upd[0]["text"].startswith("[Input Router] Haiku digest of mcp__tracker__list_issues"):
        return False, f"no MCP digest in the tool's own shape: {text[:200]}"
    rows = read_jsonl(home, "savings.jsonl")
    kinds = {r.get("kind") for r in rows if r.get("mod") == "input_router"}
    if kinds != {"mcp_preclean", "mcp_digest"}:
        return False, f"expected pre-clean and digest entries, got {kinds}"
    raw = [r for r in rows if r.get("kind") == "mcp_digest"][0]["path"]
    if not os.path.exists(raw) or "avatar_url" not in open(raw).read():
        return False, "raw result not saved in full"
    return True, ""


register(
    Case("input_router", "~20k-token .md -> digest, path, saving", IR, "post_read_md.json",
         _digested("toolu_read1", "notes.md"), setup=_ir_setup(), max_ms=600),
    Case("input_router", "structured Read result kept in shape", IR, "post_read_struct.json", _struct_kept,
         setup=_ir_setup()),
    Case("input_router", "3k-token .py -> untouched", IR, "post_read_py.json", _passthrough, setup=_ir_setup()),
    Case("input_router", "Read with offset/limit -> untouched", IR, "post_read_slice.json", _passthrough,
         setup=_ir_setup()),
    Case("input_router", 'prompt says "verbatim" -> untouched', IR, "post_read_md.json", _passthrough,
         setup=_ir_setup("quote the pricing part verbatim please")),
    Case("input_router", "file about to be edited -> untouched", IR, "post_read_md.json", _passthrough,
         setup=_ir_setup("update notes.md with the new pricing")),
    Case("input_router", ".git file -> untouched", IR, "post_read_git.json", _passthrough, setup=_ir_setup()),
    Case("input_router", ".pdf -> untouched (by design)", IR, "post_read_pdf.json", _passthrough, setup=_ir_setup()),
    Case("input_router", "read-full-instead button -> once", IR, "post_read_md.json", _bypass_consumed,
         setup=_bypass_setup),
    Case("input_router", "forced Haiku timeout -> passes through", IR, "post_read_md.json", _timeout_check,
         setup=_ir_setup(), env={"TOKEN_SAVER_STUB_FAIL": "timeout"}),
)


register(
    Case("input_router", "MCP result: pre-clean, digest, raw saved", IR, "{home}/post_mcp_filled.json", _mcp_check,
         setup=_mcp_setup),
)


# ---------------------------------------------------------------- effort optimizer
# Two steps, as the shim runs them: effort-check (at submit: heuristics, or "ask"
# Haiku), then effort-decide (once the current level is known).
CLI = "lib/ts_cli.py"


def _classified(level):
    def check(out, home, p):
        c = (out or {}).get("classification") or {}
        if (out or {}).get("action") != "classified" or c.get("recommended") != level or c.get("confidence", 0) < 0.7:
            return False, f"expected classification {level}, got {out}"
        return True, ""
    return check


def _suggests(level, current):
    def check(out, home, p):
        a = out or {}
        if f"Run /effort {level}" not in (a.get("text") or "") or f"effort is {current}" not in a["text"] or a.get("apply"):
            return False, f"expected a suggestion {current} -> {level}, got {a}"
        return True, ""
    return check


def _nothing(out, home, p):
    a = out or {}
    if a.get("text") or a.get("apply") or a.get("action") not in ("none", "done"):
        return False, f"expected nothing shown, got {a}"
    return True, ""


def _asks_model(out, home, p):
    a = out or {}
    if a.get("action") != "ask" or a.get("model") != "haiku" or "Current effort: high" not in a.get("prompt", "") \
            or "sort it out" not in a.get("prompt", ""):
        return False, f"expected a Haiku prompt with the current level, got {str(a)[:200]}"
    return True, ""


def _eo_dup_setup(home):
    run_script(home, CLI, "effort_low.json", args=["effort-decide", "s-eo", "high"])


def _eo_cfg(**kw):
    def setup(home):
        import token_saver_common as T
        cfg = in_home(home, T.load_config)
        cfg["effort_optimizer"].update(kw)
        in_home(home, T.save_config, cfg)
    return setup


def _eo_auto(out, home, p):
    a = out or {}
    if a.get("apply") != "low" or "effort high -> low" not in (a.get("text") or ""):
        return False, f"expected auto apply low, got {a}"
    rows = [r for r in read_jsonl(home, "savings.jsonl") if r.get("mod") == "effort_optimizer"]
    if len(rows) != 1 or rows[0].get("kind") != "effort_lowered" or rows[0].get("tokens_before") is not None:
        return False, f"lowering not logged (tokens n/a): {rows}"
    return True, ""


def _eo_auto_twice_setup(home):
    _eo_cfg(mode="auto")(home)
    run_script(home, CLI, "effort_low.json", args=["effort-decide", "s-eo", "high"])


def _eo_auto_again(out, home, p):
    if (out or {}).get("apply") != "low":
        return False, f"second high->low change not applied in auto mode: {out}"
    return True, ""


register(
    Case("effort_optimizer", '"rename ... userId" -> classified low (free)', CLI, "prompt_rename.txt",
         _classified("low"), args=["effort-check", "s-eo", "high"], max_ms=400),
    Case("effort_optimizer", '"rename" on high -> suggests low', CLI, "effort_low.json",
         _suggests("low", "high"), args=["effort-decide", "s-eo", "high"]),
    Case("effort_optimizer", '"design the CI/CD ... k8s" -> classified high', CLI, "prompt_cicd.txt",
         _classified("high"), args=["effort-check", "s-eo", "low"]),
    Case("effort_optimizer", '"CI/CD" on low -> suggests high', CLI, "effort_high.json",
         _suggests("high", "low"), args=["effort-decide", "s-eo", "low"]),
    Case("effort_optimizer", '"thanks" -> no model call, nothing shown', CLI, "prompt_thanks.txt", _nothing,
         args=["effort-check", "s-eo", "high"]),
    Case("effort_optimizer", "already on the right level -> nothing", CLI, "effort_low.json", _nothing,
         args=["effort-decide", "s-eo", "low"]),
    Case("effort_optimizer", "unclear -> asks Haiku (in background)", CLI, "prompt_unclear.txt", _asks_model,
         args=["effort-check", "s-eo", "high"]),
    Case("effort_optimizer", "Haiku reply parsed", CLI, "model_effort_low.json", _classified("low"),
         args=["effort-model", "s-eo"]),
    Case("effort_optimizer", "confidence < 0.7 -> nothing", CLI, "model_effort_unsure.json", _nothing,
         args=["effort-decide", "s-eo", "high"]),
    Case("effort_optimizer", "current level unknown -> nothing", CLI, "effort_low.json", _nothing,
         args=["effort-decide", "s-eo", ""]),
    Case("effort_optimizer", "same suggestion twice in a row -> once", CLI, "effort_low.json", _nothing,
         args=["effort-decide", "s-eo", "high"], setup=_eo_dup_setup),
    Case("effort_optimizer", "auto mode -> applies, logs lowering", CLI, "effort_low.json", _eo_auto,
         args=["effort-decide", "s-eo", "high"], setup=_eo_cfg(mode="auto")),
    Case("effort_optimizer", "auto mode: same change twice -> applied again", CLI, "effort_low.json", _eo_auto_again,
         args=["effort-decide", "s-eo", "high"], setup=_eo_auto_twice_setup),
    Case("effort_optimizer", "mod off -> nothing", CLI, "prompt_rename.txt", _nothing,
         args=["effort-check", "s-eo", "high"], setup=_eo_cfg(enabled=False)),
)
