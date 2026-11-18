"""/mods and /savings: pure functions that return the text to show.

Called by the shim through ts_cli.py; output goes to the transcript as
display-only text (never sent to the model). Plain text, no emoji.
"""
from __future__ import annotations

import json
import os
import time

import token_saver_common as ts

# USD per million input tokens, Anthropic first-party list prices
# (claude-api reference, cached 2026-11-03). Subscription users don't pay these;
# /savings labels $ as an API-equivalent estimate.
PRICES = {
    "opus":   {"input": 4.00, "cache_read": 0.20, "label": "Opus 5.5"},
    "sonnet": {"input": 2.00, "cache_read": 0.10, "label": "Sonnet 5.5"},
    "haiku":  {"input": 0.10, "cache_read": None, "label": "Haiku 5.5"},
    "fable":  {"input": 8.00, "cache_read": 0.20, "label": "Fable 5.2"},
}
PRICE_SOURCE = "list prices cached 2026-11-03"

MODS = list(ts.DEFAULT_CONFIG.keys())
ENUMS = {
    ("input_router", "model"): ["haiku", "sonnet"],
    ("effort_optimizer", "model"): ["haiku", "sonnet"],
    ("effort_optimizer", "mode"): ["suggest", "auto"],
}


# ---------------------------------------------------------------- /mods ----

def _fmt_val(v):
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, int) and v >= 10000:
        return f"{v:,}"
    return str(v)


def mods_table(session: str | None) -> str:
    cfg = ts.load_config()
    paused = ts.session_state(session).get("paused")
    lines = ["token-saver mods" + ("   [paused for this session]" if paused else ""), ""]
    lines.append(f"  {'mod':18} {'state':16} settings")
    lines.append(f"  {'-' * 18} {'-' * 16} {'-' * 40}")
    for mod in MODS:
        c = cfg.get(mod, {})
        if c.get("enabled"):
            state = "on"
        elif c.get("disabled_by") == "doctor":
            state = "off (doctor)"
        else:
            state = "off"
        if paused and c.get("enabled"):
            state = "on (paused)"
        settings = "  ".join(f"{k}={_fmt_val(v)}" for k, v in c.items()
                             if k not in ("enabled", "disabled_by", "reason"))
        lines.append(f"  {mod:18} {state:16} {settings}")
        if c.get("disabled_by") == "doctor" and c.get("reason"):
            lines.append(f"  {'':18} {'':16} reason: {c['reason']}")
    lines += ["", "  /mods on|off <mod>   /mods set <mod>.<key> <value>   /mods pause|resume   /mods reset"]
    return "\n".join(lines)


def _parse_value(raw: str, current):
    low = raw.strip().lower()
    if isinstance(current, bool):
        if low in ("on", "true", "yes", "1"):
            return True
        if low in ("off", "false", "no", "0"):
            return False
        raise ValueError("expected on/off")
    if isinstance(current, int):
        try:
            return int(raw.replace(",", "").replace("_", ""))
        except ValueError:
            raise ValueError("expected a whole number")
    return raw.strip()


def _unknown_mod(name: str) -> str:
    return f"token-saver: unknown mod '{name}'. Valid mods: {', '.join(MODS)}"


def mods_cmd(args: list[str], session: str | None) -> str:
    if not args:
        return mods_table(session)
    sub = args[0].lower()

    if sub in ("on", "off"):
        if len(args) < 2:
            return f"token-saver: usage /mods {sub} <mod>. Valid mods: {', '.join(MODS)}"
        mod = args[1]
        if mod not in MODS:
            return _unknown_mod(mod)
        cfg = ts.load_config()
        cfg[mod]["enabled"] = sub == "on"
        if sub == "on":
            cfg[mod].pop("disabled_by", None)
            cfg[mod].pop("reason", None)
        ts.save_config(cfg)
        return f"token-saver: {mod} is now {sub}. Applies from the next event."

    if sub == "set":
        if len(args) < 3 or "." not in args[1]:
            return "token-saver: usage /mods set <mod>.<key> <value>  e.g. /mods set input_router.model sonnet"
        mod, key = args[1].split(".", 1)
        if mod not in MODS:
            return _unknown_mod(mod)
        cfg = ts.load_config()
        valid_keys = [k for k in ts.DEFAULT_CONFIG[mod] if k != "enabled"]
        if key not in valid_keys:
            return f"token-saver: unknown key '{key}' for {mod}. Valid keys: {', '.join(valid_keys)}"
        raw = " ".join(args[2:])
        try:
            val = _parse_value(raw, ts.DEFAULT_CONFIG[mod][key])
        except ValueError as e:
            return f"token-saver: bad value '{raw}' for {mod}.{key}: {e}"
        allowed = ENUMS.get((mod, key))
        if allowed and val not in allowed:
            return f"token-saver: {mod}.{key} must be one of: {', '.join(allowed)}"
        if isinstance(val, int) and not isinstance(val, bool) and val <= 0:
            return f"token-saver: {mod}.{key} must be greater than 0"
        cfg[mod][key] = val
        ts.save_config(cfg)
        return f"token-saver: {mod}.{key} = {_fmt_val(val)}"

    if sub in ("pause", "resume"):
        if not session:
            return "token-saver: no session id available, cannot pause."
        st = ts.session_state(session)
        st["paused"] = sub == "pause"
        ts.save_session_state(session, st)
        if sub == "pause":
            return "token-saver: all mods paused for this session only. /mods resume to undo."
        return "token-saver: mods resumed for this session."

    if sub == "reset":
        if len(args) > 1 and args[1].lower() == "confirm":
            ts.save_config(json.loads(json.dumps(ts.DEFAULT_CONFIG)))
            return "token-saver: config restored to defaults."
        return ("token-saver: this restores every mod's settings to defaults "
                "(your on/off choices and thresholds are lost).\n"
                "Run /mods reset confirm to proceed.")

    if sub == "doctor":
        return "token-saver: doctor is not built yet (build step 2)."

    return (f"token-saver: unknown subcommand '{args[0]}'.\n"
            "  /mods                       list mods\n"
            "  /mods on|off <mod>          toggle a mod\n"
            "  /mods set <mod>.<key> <v>   change a setting\n"
            "  /mods pause | resume        this session only\n"
            "  /mods reset                 restore defaults (asks to confirm)\n"
            "  /mods doctor                health report")


# ---------------------------------------------------------------- /savings -

def _parse_ts(s: str) -> float:
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return 0.0


def _saved(r) -> int | None:
    b, a = r.get("tokens_before"), r.get("tokens_after")
    if isinstance(b, (int, float)) and isinstance(a, (int, float)):
        return int(b - a)
    return None


def _money(tokens: int | None) -> str:
    if not tokens:
        return "-"
    return f"~${tokens / 1e6 * PRICES['opus']['input']:,.2f}"


def savings_cmd(args: list[str], session: str | None) -> str:
    rows = []
    p = ts.path("savings.jsonl")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    scope = (args[0].lower() if args else "7d")
    now = time.time()
    day0 = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    if scope == "session":
        sel, title = [r for r in rows if session and r.get("session") == session], "this session"
    elif scope == "today":
        sel, title = [r for r in rows if _parse_ts(r.get("ts", "")) >= day0], "today"
    elif scope in ("all", "all-time"):
        sel, title = rows, "all time"
    elif scope in ("7d", "week"):
        sel, title = [r for r in rows if _parse_ts(r.get("ts", "")) >= now - 7 * 86400], "last 7 days"
    else:
        return "token-saver: usage /savings [today|7d|all|session]"

    if not sel:
        return (f"token-saver: nothing saved yet ({title}). "
                "Savings appear here as mods act; every entry is logged to "
                "~/.claude/token-saver/savings.jsonl.")

    per: dict[str, dict] = {}
    for r in sel:
        m = per.setdefault(r.get("mod", "?"), {"events": 0, "saved": 0, "measured": False})
        m["events"] += 1
        s = _saved(r)
        if s is not None:
            m["saved"] += s
            m["measured"] = True

    lines = [f"Token Saver - {title}", ""]
    lines.append(f"  {'mod':18} {'events':>7} {'tokens saved':>14} {'est. $':>10}")
    total = 0
    for mod, m in sorted(per.items(), key=lambda kv: -kv[1]["saved"]):
        saved = f"{m['saved']:,}" if m["measured"] else "n/a"
        lines.append(f"  {mod:18} {m['events']:>7} {saved:>14} {_money(m['saved']) if m['measured'] else '-':>10}")
        total += m["saved"]
    lines.append("  " + "-" * 52)
    lines.append(f"  {'total':18} {'':>7} {total:>14,} {_money(total):>10}")

    top = sorted((r for r in sel if (_saved(r) or 0) > 0), key=lambda r: -_saved(r))[:5]
    if top:
        lines += ["", "  biggest single savings"]
        for r in top:
            lines.append(f"  {_saved(r):>10,}  {r.get('mod', '?'):16} {str(r.get('detail', ''))[:60]}")

    lines += ["", f"  Token counts are as logged by each mod (some are len/4 estimates).",
              f"  $ = API-equivalent at Opus 5.5 input price (${PRICES['opus']['input']:.2f}/M, {PRICE_SOURCE});",
              "  on a subscription this is quota, not money. Estimates only."]
    return "\n".join(lines)
