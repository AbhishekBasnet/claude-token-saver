"""Cache Clock: when does this session's prompt cache go cold?

The Stop hook writes cache/clock-<session>.json after every main-thread reply:
  {"session", "last_activity" (epoch s), "ttl_minutes", "expires_at" (epoch s),
   "context_tokens", "written"}
The shim reads it on a 30 s timer and pins one plain-text status line.

Honesty rule: a warm-cache hit after a gap is *observed*, not caused by the
clock (the clock only shows a countdown), so it is logged with
observed_tokens and no tokens_before/tokens_after. /savings shows it as n/a
and never adds it to the total.
"""
from __future__ import annotations

import json
import os
import time

import token_saver_common as ts

GAP_S = 10 * 60          # a "gap" worth noting: more than 10 min since the last reply


def clock_path(session: str) -> str:
    safe = "".join(c for c in session if c.isalnum() or c in "-_")[:80]
    return ts.path("cache", f"clock-{safe}.json")


def read_clock(session: str | None) -> dict | None:
    if not session:
        return None
    try:
        with open(clock_path(session), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def write_clock(session: str, last_activity: float, ttl_minutes: float,
                context_tokens: int | None, source: str = "reply") -> dict:
    d = {"session": session, "keep_warm": keep_warm_on(session), "last_activity": round(last_activity, 3),
         "ttl_minutes": ttl_minutes, "expires_at": round(last_activity + ttl_minutes * 60, 3),
         "context_tokens": context_tokens, "source": source, "written": ts.now_iso()}
    ts._write_json_atomic(clock_path(session), d)
    return d


def _epoch(iso: str | None) -> float | None:
    """Transcript timestamps are UTC ISO-8601 with a Z (2026-11-18T07:32:47.038Z)."""
    if not iso:
        return None
    try:
        import calendar
        return calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


def turn_start(tpath: str | None, max_bytes: int = 4_000_000) -> dict | None:
    """The latest human prompt of the main thread and the first reply's usage
    after it: {"prompt_ts": epoch, "usage": {...}} (usage may be None)."""
    if not tpath or not os.path.exists(tpath):
        return None
    try:
        size = os.path.getsize(tpath)
        with open(tpath, "rb") as f:
            f.seek(max(0, size - max_bytes))
            raw = f.read()
        lines = raw.split(b"\n")
        if size > max_bytes:
            lines = lines[1:]
        prompt_ts, first_usage = None, None
        for line in lines:
            if b'"user"' not in line and b'"assistant"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("isSidechain"):
                continue
            t = d.get("type")
            if t == "user":
                msg = d.get("message") or {}
                origin = (d.get("origin") or {}).get("kind")
                if d.get("isMeta") or (origin and origin != "human"):
                    continue
                if ts._text_of(msg.get("content")).strip():
                    prompt_ts, first_usage = _epoch(d.get("timestamp")), None
            elif t == "assistant" and prompt_ts is not None and first_usage is None:
                u = (d.get("message") or {}).get("usage")
                if isinstance(u, dict):
                    first_usage = u
        if prompt_ts is None:
            return None
        return {"prompt_ts": prompt_ts, "usage": first_usage}
    except Exception as e:
        ts.debug(f"[cache_clock] turn_start {tpath}: {e}")
        return None


def on_stop(event: dict, cfg: dict) -> None:
    sid = event.get("session_id")
    tpath = event.get("transcript_path")
    ttl = float(cfg.get("ttl_minutes", 60) or 60)
    prev = read_clock(sid)
    now = time.time()
    # Claude Code may flush this turn's reply to the transcript a moment after
    # Stop fires: wait up to ~1 s for a reply newer than the turn's prompt.
    ts0 = turn_start(tpath)
    for _ in range(4):
        if ts0 is None or ts0.get("usage"):
            break
        time.sleep(0.25)
        ts0 = turn_start(tpath)
    last = ts.last_usage(tpath)
    write_clock(sid, now, ttl, last["context_tokens"] if last else None)
    st = ts.session_state(sid)
    if st.get("keepwarm_pings"):
        st["keepwarm_pings"] = 0            # you replied: a new idle stretch, a fresh ping budget
        ts.save_session_state(sid, st)

    # Observed (not caused): did this turn start on a warm cache after a gap?
    if not prev:
        return None
    if not ts0 or not ts0.get("usage"):
        return None
    gap = ts0["prompt_ts"] - float(prev.get("last_activity", 0))
    if gap <= GAP_S or gap > float(prev.get("ttl_minutes", ttl)) * 60:
        return None
    cached = int(ts0["usage"].get("cache_read_input_tokens", 0) or 0)
    if cached <= 0:
        return None
    ts.log_saving("cache_clock", sid, event.get("cwd"), None, None,
                  f"warm cache after {int(gap // 60)} min gap: {cached:,} tokens read from cache "
                  "(observed, not caused by the clock)",
                  kind="observed", observed_tokens=cached, gap_s=int(gap))
    return None


def on_keepwarm_ping(session: str, usage: dict | None) -> None:
    """A keep-warm ping is a model request over the same prefix: it restarts the TTL."""
    prev = read_clock(session) or {}
    ttl = float(prev.get("ttl_minutes") or ts.load_config()["cache_clock"].get("ttl_minutes", 60))
    write_clock(session, time.time(), ttl, prev.get("context_tokens"), source="keepwarm")


# ---------------------------------------------------------------- keep warm
# Verified 2026-11-18: a tool-less $.model.fork 50 min after the last message
# read the session's 40k-token prefix from cache, and the next real message at
# +70 min read it again (40,492 cached); without the ping it rewrote 39,008.

def keep_warm_on(session: str | None) -> bool:
    cfg = ts.load_config().get("cache_clock", {})
    flag = ts.session_state(session).get("keepwarm") if session else None
    return bool(cfg.get("keep_warm", False) if flag is None else flag)


def max_pings() -> int:
    return int(ts.load_config().get("cache_clock", {}).get("keep_warm_max_pings", 8))


def ping_due(session: str, now: float | None = None) -> tuple[bool, str]:
    """Ping ~5 min before expiry (or at half the TTL when it is shorter),
    never on a cold cache (that would rewrite it all), at most max_pings per idle stretch."""
    if not ts.is_enabled("cache_clock", session) or not keep_warm_on(session):
        return False, "keep-warm off"
    c = read_clock(session)
    if not c:
        return False, "no reply yet"
    now = now or time.time()
    left = float(c["expires_at"]) - now
    ttl_s = float(c.get("ttl_minutes", 60)) * 60
    lead = min(300.0, ttl_s / 2)
    if left <= 0:
        return False, "cache already cold"
    if left > lead:
        return False, f"{int(left // 60)} min left"
    n = int(ts.session_state(session).get("keepwarm_pings", 0))
    if n >= max_pings():
        return False, f"max {max_pings()} pings reached"
    return True, f"{int(left)} s left, ping {n + 1} of {max_pings()}"


def set_keep_warm(session: str, on: bool) -> None:
    st = ts.session_state(session)
    st["keepwarm"] = on
    st["keepwarm_pings"] = 0
    ts.save_session_state(session, st)
    c = read_clock(session)
    if c:                                   # refresh the flag the shim reads
        c["keep_warm"] = on
        ts._write_json_atomic(clock_path(session), c)
