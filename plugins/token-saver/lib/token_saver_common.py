"""Shared helpers for every token-saver hook. Python 3 stdlib only.

Rules every caller relies on:
  * Fail open: nothing here raises into Claude Code. Hooks go through
    run_hook(), which swallows errors, logs them and passes the event through.
  * Fast path: only json/os/sys/time are imported at module load.
  * TOKEN_SAVER_INNER=1 (set on our own background `claude -p` calls) turns
    every hook into a no-op.
  * TOKEN_SAVER_HOME overrides ~/.claude/token-saver (tests, CI).
"""
from __future__ import annotations

import json
import os
import sys
import time

INNER_ENV = "TOKEN_SAVER_INNER"

DEFAULT_CONFIG = {
    "input_router": {"enabled": True, "threshold_tokens": 2000, "model": "haiku"},
    "effort_optimizer": {"enabled": True, "model": "sonnet", "mode": "suggest"},
    "subagent_router": {"enabled": True, "allow_opus": True},
    "cache_clock": {"enabled": True, "ttl_minutes": 60, "keep_warm": False},
    "handoff": {"enabled": True, "threshold_tokens": 250000},
}


# ---------------------------------------------------------------- paths ----

def home() -> str:
    h = os.environ.get("TOKEN_SAVER_HOME") or os.path.join(
        os.path.expanduser("~"), ".claude", "token-saver")
    return h


def path(*parts: str) -> str:
    return os.path.join(home(), *parts)


def _ensure_dirs() -> None:
    for d in ("", "cache", "handoffs", "sessions"):
        os.makedirs(path(d), exist_ok=True)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _append_line(p: str, obj) -> None:
    _ensure_dirs()
    with open(p, "a", encoding="utf-8") as f:
        f.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")


def _write_json_atomic(p: str, obj) -> None:
    _ensure_dirs()
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, p)


# ---------------------------------------------------------------- logging --

def debug(msg: str) -> None:
    try:
        _append_line(path("debug.log"), f"{now_iso()} {msg}")
    except Exception:
        pass


def health(kind: str, mod: str, **fields) -> None:
    try:
        rec = {"ts": now_iso(), "kind": kind, "mod": mod,
               "version": load_state().get("last_seen_version")}
        rec.update(fields)
        _append_line(path("health.jsonl"), rec)
    except Exception:
        pass


def record_error(mod: str, err, session: str | None = None) -> None:
    """Feeds Doctor's circuit breaker (health.jsonl kind=error)."""
    text = f"{type(err).__name__}: {err}" if isinstance(err, BaseException) else str(err)
    debug(f"[{mod}] error session={session}: {text}")
    health("error", mod, session=session, error=text[:300])


# ---------------------------------------------------------------- config ---

def _merge_defaults(cfg: dict) -> dict:
    out = {}
    for mod, defaults in DEFAULT_CONFIG.items():
        cur = cfg.get(mod) if isinstance(cfg.get(mod), dict) else {}
        merged = dict(defaults)
        merged.update(cur)
        out[mod] = merged
    for k, v in cfg.items():          # keep unknown keys (forward compatible)
        out.setdefault(k, v)
    return out


def load_config() -> dict:
    p = path("config.json")
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError("config root is not an object")
        return _merge_defaults(cfg)
    except FileNotFoundError:
        cfg = _merge_defaults({})
        try:
            _write_json_atomic(p, cfg)
        except Exception as e:
            debug(f"[config] could not write defaults: {e}")
        return cfg
    except Exception as e:
        debug(f"[config] corrupt {p} ({e}); using defaults")
        health("config_corrupt", "foundation", error=str(e)[:200])
        return _merge_defaults({})


def save_config(cfg: dict) -> None:
    _write_json_atomic(path("config.json"), cfg)


# ---------------------------------------------------------------- state ----

def load_state() -> dict:
    try:
        with open(path("state.json"), encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    _write_json_atomic(path("state.json"), state)


def _session_file(session_id: str) -> str:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:80]
    return path("sessions", f"{safe}.json")


def session_state(session_id: str | None) -> dict:
    if not session_id:
        return {}
    try:
        with open(_session_file(session_id), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_session_state(session_id: str, data: dict) -> None:
    _write_json_atomic(_session_file(session_id), data)


def is_inner() -> bool:
    return os.environ.get(INNER_ENV) == "1"


def is_enabled(mod: str, session_id: str | None = None, cfg: dict | None = None) -> bool:
    if is_inner():
        return False
    cfg = cfg or load_config()
    if not (cfg.get(mod) or {}).get("enabled", False):
        return False
    if session_state(session_id).get("paused"):
        return False
    return True


# ---------------------------------------------------------------- savings --

def estimate_tokens(text) -> int:
    """Rough estimate: len/4. Always label as an estimate where shown."""
    if text is None:
        return 0
    if not isinstance(text, str):
        text = json.dumps(text)
    return int(len(text) / 4)


def log_saving(mod, session, project, before, after, detail, **extra) -> None:
    rec = {"ts": now_iso(), "mod": mod, "session": session, "project": project,
           "tokens_before": before, "tokens_after": after, "detail": detail}
    rec.update(extra)
    try:
        _append_line(path("savings.jsonl"), rec)
    except Exception as e:
        debug(f"[{mod}] could not log saving: {e}")


# ---------------------------------------------------------------- cards ----

def write_card(tool_use_id: str, mod: str, title: str, lines: list, detail: str | None = None,
               path_: str | None = None) -> None:
    """Info card the shim draws under the tool row with this tool_use_id.
    Plain text only (no emoji). Never raises."""
    if not tool_use_id:
        return
    try:
        safe = "".join(c for c in tool_use_id if c.isalnum() or c in "-_")[:100]
        d = path("cache", "cards")
        os.makedirs(d, exist_ok=True)
        card = {"mod": mod, "title": title, "lines": [str(l) for l in lines][:4], "ts": now_iso()}
        if detail:
            card["detail"] = detail[:4000]
        if path_:
            card["path"] = path_
        _write_json_atomic(os.path.join(d, f"{safe}.json"), card)
    except Exception as e:
        debug(f"[{mod}] could not write card: {e}")


# ---------------------------------------------------------------- transcript

def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def read_transcript(tpath: str | None) -> dict:
    """Latest human prompt, last assistant text, latest real usage, effort.

    context_tokens = input + cache_read + cache_creation of the latest main-thread
    assistant message (what the last request actually carried).
    """
    out = {"last_prompt": None, "last_reply": None, "usage": None,
           "context_tokens": None, "effort": None, "model": None,
           "last_assistant_ts": None}
    if not tpath or not os.path.exists(tpath):
        return out
    try:
        with open(tpath, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"type":"user"' not in line and '"type":"assistant"' not in line \
                        and '"type":"last-prompt"' not in line \
                        and '"type": "user"' not in line and '"type": "assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                t = d.get("type")
                if d.get("isSidechain"):
                    continue
                if t == "last-prompt" and d.get("lastPrompt"):
                    out["last_prompt"] = d["lastPrompt"]
                elif t == "user":
                    msg = d.get("message") or {}
                    origin = (d.get("origin") or {}).get("kind")
                    if d.get("isMeta") or (origin and origin != "human"):
                        continue
                    txt = _text_of(msg.get("content"))
                    if txt.strip():
                        out["last_prompt"] = txt
                elif t == "assistant":
                    msg = d.get("message") or {}
                    txt = _text_of(msg.get("content"))
                    if txt.strip():
                        out["last_reply"] = txt
                    u = msg.get("usage")
                    if isinstance(u, dict):
                        out["usage"] = u
                        out["context_tokens"] = (u.get("input_tokens", 0)
                                                 + u.get("cache_read_input_tokens", 0)
                                                 + u.get("cache_creation_input_tokens", 0))
                    out["effort"] = d.get("effort") or out["effort"]
                    out["model"] = msg.get("model") or out["model"]
                    out["last_assistant_ts"] = d.get("timestamp") or out["last_assistant_ts"]
    except Exception as e:
        debug(f"[transcript] {tpath}: {e}")
    return out


# ---------------------------------------------------------------- EXPECTS --

_TYPES = {"str": str, "int": int, "bool": bool, "dict": dict, "list": list,
          "num": (int, float)}


def _get(event, dotted):
    cur = event
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def check_expects(event: dict, expects: dict, mod: str) -> bool:
    """True if the event matches EXPECTS. On drift: log schema_drift, return False.

    EXPECTS = {"event": "PreToolUse", "tool_name": "Read" (optional),
               "fields": {"tool_input.file_path": "str", "session_id": "str"}}
    A tool_name mismatch is not drift (another tool's event): returns False quietly.
    """
    if not isinstance(event, dict):
        health("schema_drift", mod, missing="<event is not an object>")
        return False
    want_ev = expects.get("event")
    if want_ev and event.get("hook_event_name") != want_ev:
        health("schema_drift", mod, missing="hook_event_name",
               expected=want_ev, got=event.get("hook_event_name"))
        return False
    tools = expects.get("tool_name")
    if tools:
        tools = [tools] if isinstance(tools, str) else tools
        if event.get("tool_name") not in tools:
            return False
    fields = expects.get("fields") or {}
    if isinstance(fields, list):
        fields = {f: None for f in fields}
    for name, typ in fields.items():
        ok, val = _get(event, name)
        if not ok:
            health("schema_drift", mod, missing=name, event=want_ev)
            return False
        if typ and not isinstance(val, _TYPES.get(typ, object)):
            health("schema_drift", mod, missing=name, wrong_type=type(val).__name__,
                   expected=typ, event=want_ev)
            return False
    return True


# ---------------------------------------------------------------- model ----

class ModelResult:
    def __init__(self, text=None, usage=None, ms=0, error=None):
        self.text, self.usage, self.ms, self.error = text, usage, ms, error

    @property
    def ok(self):
        return self.text is not None and self.error is None


DRY_RUN = False


def call_model(model: str, system: str, prompt: str, timeout: float = 45) -> ModelResult:
    """Background call on the user's subscription via `claude -p`.

    No tools, no MCP, no session persistence; TOKEN_SAVER_INNER=1 so our own
    hooks are no-ops inside it. Never raises: check .ok.
    In dry-run, returns TOKEN_SAVER_STUB_REPLY (or a canned line);
    TOKEN_SAVER_STUB_FAIL=timeout|error simulates failure.
    """
    if DRY_RUN or os.environ.get("TOKEN_SAVER_STUB_REPLY") is not None \
            or os.environ.get("TOKEN_SAVER_STUB_FAIL"):
        fail = os.environ.get("TOKEN_SAVER_STUB_FAIL")
        if fail:
            return ModelResult(error=f"stub {fail}")
        return ModelResult(text=os.environ.get("TOKEN_SAVER_STUB_REPLY", "[stub reply]"),
                           usage={"input_tokens": 0, "output_tokens": 0})
    import subprocess
    t0 = time.time()
    env = dict(os.environ)
    env[INNER_ENV] = "1"
    argv = ["claude", "-p", "--model", model, "--tools", "", "--strict-mcp-config",
            "--no-session-persistence", "--output-format", "json",
            "--system-prompt", system]
    try:
        p = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                           timeout=timeout, env=env, cwd=home() if os.path.isdir(home()) else None)
        ms = int((time.time() - t0) * 1000)
        raw = p.stdout.strip()
        data = json.loads(raw[: raw.rfind("}") + 1]) if raw else {}
        if p.returncode != 0 or data.get("is_error"):
            return ModelResult(error=f"exit {p.returncode}: {(data.get('result') or p.stderr)[:200]}", ms=ms)
        return ModelResult(text=data.get("result", ""), usage=data.get("usage"), ms=ms)
    except subprocess.TimeoutExpired:
        return ModelResult(error=f"timeout after {timeout}s", ms=int((time.time() - t0) * 1000))
    except Exception as e:
        return ModelResult(error=f"{type(e).__name__}: {e}", ms=int((time.time() - t0) * 1000))


# ---------------------------------------------------------------- runner ---

class Ctx:
    def __init__(self, mod, event, dry_run):
        self.mod, self.event, self.dry_run = mod, event, dry_run
        self.session = event.get("session_id") if isinstance(event, dict) else None
        self.project = event.get("cwd") if isinstance(event, dict) else None
        self._cfg = None

    @property
    def cfg(self) -> dict:
        if self._cfg is None:
            self._cfg = load_config()
        return self._cfg

    @property
    def mod_cfg(self) -> dict:
        return self.cfg.get(self.mod, {})


def run_hook(mod: str, expects: dict, handler, *, check_enabled: bool = True) -> int:
    """Entry point for every classic hook script. Always exits 0.

    handler(event, ctx) returns a dict (classic hook JSON output) or None
    for pass-through. Anything that goes wrong -> pass-through + logged.
    """
    global DRY_RUN
    DRY_RUN = "--dry-run" in sys.argv
    if is_inner():
        return 0
    event = {}
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        if not check_expects(event, expects, mod):
            return 0
        ctx = Ctx(mod, event, DRY_RUN)
        if check_enabled and not is_enabled(mod, ctx.session, ctx.cfg):
            return 0
        out = handler(event, ctx)
        if out:
            sys.stdout.write(json.dumps(out))
    except Exception as e:
        import traceback
        record_error(mod, e, event.get("session_id") if isinstance(event, dict) else None)
        debug(traceback.format_exc().strip().replace("\n", " | "))
    return 0
