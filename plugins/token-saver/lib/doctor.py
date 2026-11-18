"""Doctor: update detection, conflict scan, health report. Python stdlib only.

Everything here fails open: callers wrap it, and each function returns
something printable even when parts of the check could not run.
Plain text output, no emoji.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

import token_saver_common as ts

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_NAME = "token-saver"
OUR_COMMANDS = {"mods", "savings", "handoff", "keepwarm"}
CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
CHANGELOG_WORDS = re.compile(r"\bhooks?\b|\bplugins?\b|\bmods?\b|status ?line", re.I)
CHANGELOG_TOOLS = re.compile(r"\b(Task|Agent|Read)\b")   # tool names: case-sensitive

# Tools each mod depends on; Doctor warns when one hasn't been seen for a while.
DEPENDS: dict[str, list[str]] = {}


def claude_dir() -> str:
    override = os.environ.get("TOKEN_SAVER_CLAUDE_DIR")
    if override:
        return override.replace("{home}", ts.home())   # tests point inside their temp home
    return os.path.join(os.path.expanduser("~"), ".claude")


# ---------------------------------------------------------------- version --

def current_version() -> str | None:
    fake = os.environ.get("TOKEN_SAVER_FAKE_VERSION")
    if fake:
        return fake
    try:
        p = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5,
                           env={**os.environ, ts.INNER_ENV: "1"})
        m = re.search(r"\d+\.\d+\.\d+", p.stdout)
        return m.group(0) if m else None
    except Exception as e:
        ts.debug(f"[doctor] claude --version failed: {e}")
        return None


def _vkey(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def changelog_lines(old: str, new: str, limit: int = 8) -> list[str]:
    """Lines from versions (old, new] that mention hooks/plugins/tools we use."""
    try:
        src = os.environ.get("TOKEN_SAVER_CHANGELOG_FILE")
        if src:
            with open(src, encoding="utf-8") as f:
                text = f.read()
        else:
            import urllib.request
            req = urllib.request.Request(CHANGELOG_URL, headers={"User-Agent": "token-saver-doctor"})
            with urllib.request.urlopen(req, timeout=6) as r:
                text = r.read(3_000_000).decode("utf-8", "replace")
    except Exception as e:
        ts.debug(f"[doctor] changelog fetch failed: {e}")
        return []
    out, ver = [], None
    lo, hi = _vkey(old), _vkey(new)
    for line in text.splitlines():
        m = re.match(r"^##\s+(\d+\.\d+\.\d+)", line)
        if m:
            ver = _vkey(m.group(1))
            continue
        if ver and lo < ver <= hi and line.startswith("- ") and (CHANGELOG_WORDS.search(line) or CHANGELOG_TOOLS.search(line)):
            out.append(line[2:].strip())
            if len(out) >= limit:
                break
    return out


# ---------------------------------------------------------------- self-test

def run_selftest(budget_s: float = 60, mods=None) -> dict:
    """Runs selftest/selftest.py in a child process. Returns
    {"ok": bool, "passed": n, "total": n, "failures": [...], "by_mod": {...}}."""
    depth = int(os.environ.get("TOKEN_SAVER_SELFTEST_DEPTH", "0"))
    if depth >= 6:   # safety net only; the subset below never reaches Doctor again
        return {"ok": True, "passed": 0, "total": 0, "failures": [], "by_mod": {}, "skipped": "nested"}
    if depth >= 1 and mods is None:
        mods = ["foundation"]      # inside a self-test: foundation cases never invoke Doctor
    argv = [sys.executable, os.path.join(PLUGIN_ROOT, "selftest", "selftest.py"), "--json"] + list(mods or [])
    env = {k: v for k, v in os.environ.items() if k != "TOKEN_SAVER_HOME"}
    env["TOKEN_SAVER_SELFTEST_DEPTH"] = str(depth + 1)
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=budget_s, env=env)
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"ok": False, "passed": 0, "total": 0, "failures": [f"self-test exceeded {budget_s:.0f}s"], "by_mod": {}}
    except Exception as e:
        return {"ok": False, "passed": 0, "total": 0, "failures": [f"self-test could not run: {e}"], "by_mod": {}}
    fails = [f"{m}: {r['case']} ({r['why']})" for m, rows in res.items() for r in rows if not r["ok"]]
    total = sum(len(v) for v in res.values())
    return {"ok": not fails, "passed": total - len(fails), "total": total, "failures": fails, "by_mod": res}


def _summ(st: dict) -> str:
    if st.get("skipped"):
        return "self-test skipped (nested)"
    if st["ok"]:
        return f"self-test passed ({st['passed']}/{st['total']})"
    first = st["failures"][:3]
    more = f" (+{len(st['failures']) - 3} more)" if len(st["failures"]) > 3 else ""
    return f"self-test FAILED {st['total'] - st['passed']}/{st['total']}: " + "; ".join(first) + more


# ---------------------------------------------------------------- conflicts

def _read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _matches(matcher, tool: str) -> bool:
    if matcher in (None, "", "*"):
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return tool in str(matcher)


def _classic_entries(hooks_obj):
    """Yield (event, matcher) from a classic hooks object."""
    if not isinstance(hooks_obj, dict):
        return
    for event, groups in hooks_obj.items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            if isinstance(g, dict):
                yield event, g.get("matcher")


def our_hooks() -> list[tuple[str, str | None]]:
    """(event, matcher) of our own classic hooks, read from our hooks.json."""
    src = os.environ.get("TOKEN_SAVER_OUR_HOOKS_FILE") or os.path.join(PLUGIN_ROOT, "hooks", "hooks.json")
    d = _read_json(src) or {}
    return list(_classic_entries(d.get("hooks")))


def _our_tools() -> list[str]:
    tools = set()
    for ev, m in our_hooks():
        if ev in ("PreToolUse", "PostToolUse") and m:
            for t in re.split(r"\|", m):
                tools.add("mcp__any" if t.startswith("mcp__") else t)
    return sorted(tools)


def _check_classic(source: str, hooks_obj, found: list) -> None:
    ours = our_hooks()
    our_events = {e for e, _ in ours}
    for event, matcher in _classic_entries(hooks_obj):
        if event in ("PreToolUse", "PostToolUse"):
            for our_ev, our_m in ours:
                # their Pre can deny a call our Pre or Post acts on; their Post can
                # replace output our Post reads.
                if our_ev not in ("PreToolUse", "PostToolUse") or (event == "PostToolUse" and our_ev != "PostToolUse"):
                    continue
                for tool in (our_m or "").split("|"):
                    probe = "mcp__x__y" if tool.startswith("mcp__") else tool
                    if probe and _matches(matcher, probe):
                        what = "rewrite its input or deny it" if event == "PreToolUse" else "replace its output"
                        found.append({
                            "key": f"{source}|{event}|{matcher}|{tool}", "severity": "high",
                            "text": f"{source} has a {event} hook on {tool} (matcher {matcher or '*'}); it may {what}, so results depend on run order.",
                            "fix": f"turn off one of them: disable that hook in {source}, or /mods off the token-saver mod using {tool}.",
                        })
        elif event in our_events and event in ("SessionStart", "UserPromptSubmit"):
            found.append({
                "key": f"{source}|{event}", "severity": "info",
                "text": f"{source} also hooks {event} (both run; injected context may duplicate).",
                "fix": "no action needed unless you see duplicated context.",
            })


def _check_module(source: str, path: str, found: list) -> None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except Exception:
        return
    if re.search(r"""on\(\s*['"]tool\.call['"]""", src):
        names = [t for t in ("Read", "Agent", "Task") if re.search(rf"""tool\s*:\s*['"]{t}['"]""", src)]
        if names or not re.search(r"""tool\s*:\s*['"]""", src):
            found.append({
                "key": f"{source}|tool.call|{','.join(names) or '*'}", "severity": "high",
                "text": f"{source} has a function hook on tool calls ({', '.join(names) or 'all tools'}); it may rewrite or block the same calls token-saver acts on.",
                "fix": f"disable one of them (/plugin to disable {source}, or /mods off the overlapping token-saver mod).",
            })
    if re.search(r"""on\(\s*['"]turn\.step['"]""", src):
        found.append({
            "key": f"{source}|turn.step", "severity": "high",
            "text": f"{source} changes model requests (turn.step); it may also set model or effort.",
            "fix": "keep only one router: disable it or /mods off subagent_router / effort_optimizer.",
        })
    for name in re.findall(r"""command\.register\(\s*\{[^}]*?name\s*:\s*['"]([\w-]+)['"]""", src):
        if name in OUR_COMMANDS:
            found.append({
                "key": f"{source}|cmd|{name}", "severity": "medium",
                "text": f"{source} also registers /{name}.",
                "fix": f"rename one of them (token-saver can switch to /ts-{name}).",
            })


def _settings_files(project: str | None) -> list[str]:
    cd = claude_dir()
    files = [os.path.join(cd, "settings.json"), os.path.join(cd, "settings.local.json")]
    if project:
        files += [os.path.join(project, ".claude", "settings.json"),
                  os.path.join(project, ".claude", "settings.local.json")]
    return files


def _enabled_plugins(project: str | None) -> set[str]:
    on = set()
    for f in _settings_files(project):
        d = _read_json(f) or {}
        for k, v in (d.get("enabledPlugins") or {}).items():
            if v:
                on.add(k)
            else:
                on.discard(k)
    return on


def _plugin_paths(project: str | None) -> list[tuple[str, str]]:
    reg = _read_json(os.path.join(claude_dir(), "plugins", "installed_plugins.json")) or {}
    enabled = _enabled_plugins(project)
    out = []
    for pid, installs in (reg.get("plugins") or {}).items():
        if pid.split("@")[0] == PLUGIN_NAME or pid not in enabled:
            continue
        for inst in installs if isinstance(installs, list) else []:
            p = inst.get("installPath")
            if p and os.path.isdir(p):
                out.append((pid, p))
                break
    return out


def scan_signature(project: str | None) -> str:
    paths = _settings_files(project) + [os.path.join(claude_dir(), "plugins", "installed_plugins.json")]
    sig = []
    for p in paths:
        try:
            sig.append(f"{p}:{os.path.getmtime(p):.0f}")
        except OSError:
            sig.append(f"{p}:-")
    return "|".join(sig)


def scan_conflicts(project: str | None) -> list[dict]:
    found: list[dict] = []
    for f in _settings_files(project):
        d = _read_json(f)
        if not isinstance(d, dict):
            continue
        name = f.replace(os.path.expanduser("~"), "~")
        _check_classic(name, d.get("hooks"), found)
        if d.get("statusLine"):
            found.append({
                "key": f"{name}|statusLine", "severity": "info",
                "text": f"{name} sets a custom status line.",
                "fix": "none: Cache Clock shows its own pinned line and never replaces yours.",
            })
    for pid, root in _plugin_paths(project):
        hj = _read_json(os.path.join(root, "hooks", "hooks.json")) or {}
        manifest = _read_json(os.path.join(root, ".claude-plugin", "plugin.json")) or {}
        _check_classic(pid, hj.get("hooks"), found)
        if isinstance(manifest.get("hooks"), dict):
            _check_classic(pid, manifest["hooks"].get("hooks", manifest["hooks"]), found)
        for mod in hj.get("modules") or []:
            _check_module(pid, os.path.normpath(os.path.join(root, "hooks", mod)), found)
        cdir = os.path.join(root, "commands")
        if os.path.isdir(cdir):
            for fn in os.listdir(cdir):
                stem = os.path.splitext(fn)[0]
                if stem in OUR_COMMANDS:
                    found.append({
                        "key": f"{pid}|cmd|{stem}", "severity": "medium",
                        "text": f"{pid} also defines /{stem}.",
                        "fix": f"rename one of them (token-saver can switch to /ts-{stem}).",
                    })
    # de-duplicate by key
    seen, uniq = set(), []
    for c in found:
        if c["key"] not in seen:
            seen.add(c["key"])
            uniq.append(c)
    return uniq


# ---------------------------------------------------------------- health ---

def _recent_health(hours: float = 24) -> list[dict]:
    p = ts.path("health.jsonl")
    if not os.path.exists(p):
        return []
    cutoff = time.time() - hours * 3600
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            try:
                t = time.mktime(time.strptime(r.get("ts", "")[:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                t = 0
            if t >= cutoff:
                rows.append(r)
    return rows


def health_by_mod() -> dict[str, dict]:
    """{mod: {"errors": n, "drift": n, "last_error": str}} over 24 h."""
    out: dict[str, dict] = {}
    for r in _recent_health(24):
        m = out.setdefault(r.get("mod", "?"), {"errors": 0, "drift": 0, "last_error": None, "drift_fields": set()})
        if r.get("kind") == "error":
            m["errors"] += 1
            m["last_error"] = r.get("error")
        elif r.get("kind") == "schema_drift":
            m["drift"] += 1
            m["drift_fields"].add(str(r.get("missing")))
    return out


def health_label(mod: str, cfg: dict, hb: dict, selftest_by_mod: dict | None = None) -> str:
    c = cfg.get(mod, {})
    if c.get("disabled_by") == "doctor":
        return "off (doctor)"
    if selftest_by_mod and any(not r["ok"] for r in selftest_by_mod.get(mod, [])):
        return "FAIL"
    h = hb.get(mod, {})
    if h.get("drift"):
        return f"warn: drift x{h['drift']}"
    if h.get("errors"):
        return f"warn: {h['errors']} err/24h"
    return "ok"


# ---------------------------------------------------------------- report ---

def report(project: str | None = None) -> str:
    ver = current_version() or "unknown"
    st = run_selftest(60)
    state = ts.load_state()
    state["last_selftest"] = {"ts": ts.now_iso(), "ok": st["ok"], "summary": _summ(st)}
    ts.save_state(state)
    cfg = ts.load_config()
    hb = health_by_mod()
    conflicts = scan_conflicts(project)

    rows = [f"token-saver doctor - Claude Code {ver}", ""]
    built = list(st["by_mod"].keys())
    names = built + [m for m in ts.DEFAULT_CONFIG if m not in built]
    for mod in names:
        if mod not in st["by_mod"] and mod in ts.DEFAULT_CONFIG:
            label = "not built yet"
        else:
            label = health_label(mod, cfg, hb, st["by_mod"])
            cases = st["by_mod"].get(mod, [])
            if cases and label == "ok":
                label = f"ok ({len(cases)} checks)"
        rows.append(f"  {mod:18} {label}")
        if cfg.get(mod, {}).get("disabled_by") == "doctor":
            rows.append(f"  {'':18} reason: {cfg[mod].get('reason', '?')}  -> /mods on {mod} to re-enable")
        for f in st["failures"]:
            if f.startswith(mod + ":"):
                rows.append(f"  {'':18} {f[len(mod) + 2:]}")

    drift = sum(h["drift"] for h in hb.values())
    errors = sum(h["errors"] for h in hb.values())
    rows += ["", f"  conflicts: {len(conflicts)}   schema drift (24h): {drift}   errors (24h): {errors}"]
    for c in conflicts:
        rows.append(f"  [{c['severity']}] {c['text']}")
        rows.append(f"         fix: {c['fix']}")
    for mod, h in hb.items():
        if h["drift"]:
            rows.append(f"  drift: {mod} saw events missing {', '.join(sorted(h['drift_fields']))} (passed through unchanged)")
    seen = state.get("events_seen", {})
    expected = sorted({e for e, _ in our_hooks()})
    never = [e for e in expected if e not in seen]
    if never:
        rows.append(f"  never fired yet: {', '.join(never)}")
    for mod, tools in DEPENDS.items():
        for t in tools:
            last = (state.get("tool_last_seen_session") or {}).get(t)
            n = state.get("session_count", 0)
            if last is not None and n - last >= 10:
                rows.append(f"  {mod}: tool {t} not seen in {n - last} sessions (renamed?)")
    rows.append(f"  {_summ(st)}")
    return "\n".join(rows)


# ---------------------------------------------------------------- session --

def on_session_start(event: dict) -> str | None:
    """SessionStart work. Returns one notice (several lines) or None."""
    state = ts.load_state()
    state["session_count"] = int(state.get("session_count", 0)) + 1
    lines: list[str] = []

    ver = current_version()
    last = state.get("last_seen_version")
    if ver and last and ver != last:
        lines.append(f"doctor: Claude Code updated {last} -> {ver}. Ran token-saver self-test: ")
        st = run_selftest(60)
        lines[-1] += _summ(st) + ("." if st["ok"] else ". /mods doctor for details.")
        state["last_selftest"] = {"ts": ts.now_iso(), "ok": st["ok"], "summary": _summ(st)}
        cl = changelog_lines(last, ver)
        if cl:
            lines.append("doctor: release notes that may affect mods:")
            lines += [f"  - {c[:160]}" for c in cl]
    if ver:
        state["last_seen_version"] = ver

    project = event.get("cwd")
    sig = scan_signature(project)
    if sig != state.get("conflict_sig"):
        conflicts = scan_conflicts(project)
        state["conflict_sig"] = sig
        reported = set(state.get("conflicts_reported", []))
        new = [c for c in conflicts if c["key"] not in reported and c["severity"] != "info"]
        for c in new:
            lines.append(f"doctor: conflict [{c['severity']}]: {c['text']} Fix: {c['fix']}")
        state["conflicts_reported"] = sorted(reported | {c["key"] for c in conflicts})
    ts.save_state(state)
    return "\n".join(lines) if lines else None
