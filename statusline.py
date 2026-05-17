#!/usr/bin/env python3
"""Claude Code cost clock statusline.

Displays real-time API cost in the Claude Code status bar.
Tracks daily, weekly, and monthly spending.

Example output:
  Sonnet 4.6 | 5h:29% 7d:52% | D:$0.14 | W:$3.21 | M:$18.50 | sess:$0.03

Primary cost source: Claude Code's built-in cost.total_cost_usd field.
Fallback: computed from token counts using published pricing constants.

Pricing constants (per million tokens, as of May 2026):
  Model                 Input    Output   Cache read   Cache write
  Haiku 4.5             $1.00    $5.00    $0.10        $1.25
  Sonnet 4.5/4.6        $3.00    $15.00   $0.30        $3.75
  Opus 4.5/4.6/4.7      $5.00    $25.00   $0.50        $6.25

Source: https://www.anthropic.com/pricing

Zero dependencies — Python 3 standard library only.

Built collaboratively with Claude Sonnet 4.6.
"""

import fcntl
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from datetime import date, timedelta

CACHE_DIR = Path.home() / ".claude"
DAILY_FILE  = CACHE_DIR / "cost_clock_daily.json"
HISTORY_FILE = CACHE_DIR / "cost_clock_history.jsonl"
QUOTA_CACHE  = CACHE_DIR / "cost_clock_quota.json"
QUOTA_TTL    = 300  # seconds between quota API calls

# ── Pricing table ──────────────────────────────────────────────────────────────
# (input $/M, output $/M, cache_read $/M, cache_write_5min $/M)
# Cache read  = 0.10 × input  (90% discount)
# Cache write = 1.25 × input  (5-minute TTL; 2× for 1-hour TTL)
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-4-5":     (1.00,  5.00, 0.10, 1.25),
    "claude-sonnet-4-5":    (3.00, 15.00, 0.30, 3.75),
    "claude-sonnet-4-6":    (3.00, 15.00, 0.30, 3.75),
    "claude-opus-4-5":      (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-6":      (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-7":      (5.00, 25.00, 0.50, 6.25),
}
DEFAULT_PRICING = (3.00, 15.00, 0.30, 3.75)  # Sonnet tier fallback


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(path: Path, obj: dict) -> None:
    """Atomic write with owner-only permissions."""
    tmp = path.with_suffix(".tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
            f.flush()
            os.fsync(f.fileno())
        os.rename(str(tmp), str(path))
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass


def _model_pricing(model_id: str) -> tuple[float, float, float, float]:
    if model_id in PRICING:
        return PRICING[model_id]
    for key, val in PRICING.items():
        if model_id.startswith(key):
            return val
    return DEFAULT_PRICING


def _compute_cost(model_id: str, fresh_in: int, output: int,
                  cache_read: int, cache_write: int) -> float:
    """Fallback: derive cost from token counts."""
    p_in, p_out, p_cr, p_cw = _model_pricing(model_id)
    return (
        fresh_in    / 1_000_000 * p_in  +
        output      / 1_000_000 * p_out +
        cache_read  / 1_000_000 * p_cr  +
        cache_write / 1_000_000 * p_cw
    )


def fmt_cost(usd: float) -> str:
    if usd < 0.0001:
        return "$0.00"
    if usd < 0.01:
        return f"${usd:.4f}"
    if usd < 1:
        return f"${usd:.3f}"
    if usd < 10:
        return f"${usd:.2f}"
    if usd < 1_000:
        return f"${usd:.1f}"
    return f"${usd:,.0f}"


# ── Quota (macOS only, undocumented beta endpoint) ─────────────────────────────

def _get_oauth_token() -> str | None:
    user = os.environ.get("USER", "")
    attempts = []
    if user:
        attempts.append(["security", "find-generic-password",
                         "-s", "Claude Code-credentials", "-a", user, "-w"])
    attempts.append(["security", "find-generic-password",
                     "-s", "Claude Code-credentials", "-w"])
    for cmd in attempts:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if r.returncode != 0:
                continue
            raw = r.stdout.strip()
            try:
                creds = json.loads(raw)
                oauth = creds.get("claudeAiOauth", {})
                if isinstance(oauth, dict) and "accessToken" in oauth:
                    exp = oauth.get("expiresAt", 0)
                    if isinstance(exp, (int, float)) and exp > 0:
                        if exp / 1000 < time.time():
                            continue  # expired
                    return oauth["accessToken"]
                for key in ("accessToken", "access_token"):
                    if key in creds:
                        return creds[key]
            except json.JSONDecodeError:
                return raw
        except Exception:
            continue
    return None


def fetch_quota() -> tuple[float | None, float | None]:
    """Return (5h_utilization%, 7d_utilization%) or (None, None)."""
    cache = _load(QUOTA_CACHE)
    now = time.time()
    if cache and now - cache.get("ts", 0) < QUOTA_TTL:
        return cache.get("q5"), cache.get("q7")

    tok = _get_oauth_token()
    if not tok:
        return cache.get("q5"), cache.get("q7")

    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "anthropic-beta": "oauth-2025-04-20",
                "Authorization": f"Bearer {tok}",
            },
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        q5 = data.get("five_hour", {}).get("utilization")
        q7 = data.get("seven_day",  {}).get("utilization")
        _save(QUOTA_CACHE, {"q5": q5, "q7": q7, "ts": now})
        return q5, q7
    except Exception:
        return cache.get("q5"), cache.get("q7")


# ── Daily cost accumulator ─────────────────────────────────────────────────────

def update_daily(
    sid: str,
    session_cost_usd: float,   # from cost.total_cost_usd (0 if unavailable)
    s_in: int, s_out: int,     # cumulative session token counts
    cu_cache_read: int,         # per-call cache metrics from current_usage
    cu_cache_write: int,
    model_id: str,
) -> tuple[float, float]:
    """Accumulate costs with file locking. Returns (daily_cost, session_today_cost)."""
    today = date.today().isoformat()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    lock_fd = os.open(str(DAILY_FILE.with_suffix(".lock")),
                      os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        d = _load(DAILY_FILE)

        # ── Day rollover ───────────────────────────────────────────────────────
        if d.get("date") != today:
            # Archive yesterday to history
            if d.get("date") and d.get("cost", 0) > 0:
                line = json.dumps({
                    "date":     d["date"],
                    "cost":     round(d["cost"], 6),
                    "sessions": len(d.get("sessions", {})),
                })
                try:
                    fd2 = os.open(str(HISTORY_FILE),
                                  os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    os.write(fd2, (line + "\n").encode())
                    os.close(fd2)
                except Exception:
                    pass
            # Carry forward sessions with updated baselines so sessions that
            # span midnight don't attribute yesterday's spend to today.
            baselines: dict = {}
            for s_id, sv in d.get("sessions", {}).items():
                baselines[s_id] = {
                    "lc":  sv.get("sc", 0),   # cost baseline = end-of-yesterday sc
                    "sc":  sv.get("sc", 0),
                    "li":  sv.get("i",  0),
                    "lcr": sv.get("cr", 0),
                    "lcw": sv.get("cw", 0),
                    "i":   sv.get("i",  0),
                    "o":   sv.get("o",  0),
                    "cr":  sv.get("cr", 0),
                    "cw":  sv.get("cw", 0),
                    "dc":  0.0,
                    "m":   sv.get("m",  "?"),
                    "n":   0,
                }
            d = {"date": today, "sessions": baselines, "cost": 0.0}

        # ── Per-session update ─────────────────────────────────────────────────
        prev = d.get("sessions", {}).get(sid, {})
        prev_lc  = prev.get("lc",  0.0)   # cost baseline for today
        prev_li  = prev.get("li",  0)
        prev_lcr = prev.get("lcr", 0)
        prev_lcw = prev.get("lcw", 0)
        prev_cr  = prev.get("cr",  0)
        prev_cw  = prev.get("cw",  0)

        # Detect a new API call (same heuristic as energy monitor)
        new_call = (
            s_in > prev_li
            or cu_cache_read  != prev_lcr
            or cu_cache_write != prev_lcw
        )
        acc_cr = prev_cr + cu_cache_read  if new_call else prev_cr
        acc_cw = prev_cw + cu_cache_write if new_call else prev_cw

        # Cost delta for this session today
        if session_cost_usd > 0:
            # Use the authoritative value from Claude Code
            session_today_cost = max(0.0, session_cost_usd - prev_lc)
        else:
            # Fallback: accumulate from token deltas
            di   = max(0, s_in  - prev.get("i", 0))
            do_  = max(0, s_out - prev.get("o", 0))
            d_cr = max(0, acc_cr - prev_cr)
            d_cw = max(0, acc_cw - prev_cw)
            session_today_cost = (prev.get("dc", 0.0)
                                  + _compute_cost(model_id, di, do_, d_cr, d_cw))

        sessions = d.get("sessions", {})
        sessions[sid] = {
            "lc":  prev_lc,
            "sc":  session_cost_usd,
            "i":   s_in,  "o":   s_out,
            "cr":  acc_cr, "cw":  acc_cw,
            "li":  s_in,  "lcr": cu_cache_read, "lcw": cu_cache_write,
            "dc":  session_today_cost,
            "m":   model_id,
            "n":   prev.get("n", 0) + (1 if new_call else 0),
        }
        d["sessions"] = sessions
        d["cost"] = sum(s.get("dc", 0.0) for s in sessions.values())
        _save(DAILY_FILE, d)
        return d["cost"], session_today_cost

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _load_history() -> dict[str, dict]:
    days: dict = {}
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    days[entry["date"]] = entry
                except Exception:
                    pass
    return days


def weekly_monthly_cost(daily_cost: float) -> tuple[float, float]:
    today = date.today()
    days  = _load_history()
    yesterday = (today - timedelta(days=1)).isoformat()
    w_start   = (today - timedelta(days=6)).isoformat()
    m_start   = (today - timedelta(days=29)).isoformat()

    w_cost = m_cost = daily_cost
    for dt_str, entry in days.items():
        if w_start <= dt_str <= yesterday:
            w_cost += entry.get("cost", 0.0)
        if m_start <= dt_str <= yesterday:
            m_cost += entry.get("cost", 0.0)
    return w_cost, m_cost


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        data = {}

    model    = data.get("model", {}).get("display_name", "?")
    model_id = data.get("model", {}).get("id", "?")
    ctx      = data.get("context_window", {})
    ctx_pct  = ctx.get("used_percentage")
    sid      = data.get("session_id", "unknown")

    # Primary cost source (authoritative when available)
    session_cost_usd = float(data.get("cost", {}).get("total_cost_usd") or 0)

    # Token counts for fallback cost computation + new-call detection
    s_in  = ctx.get("total_input_tokens", 0)
    s_out = ctx.get("total_output_tokens", 0)
    cu    = ctx.get("current_usage") or {}
    cu_cr = cu.get("cache_read_input_tokens", 0)
    cu_cw = cu.get("cache_creation_input_tokens", 0)

    daily_cost, session_today = update_daily(
        sid, session_cost_usd, s_in, s_out, cu_cr, cu_cw, model_id)
    w_cost, m_cost = weekly_monthly_cost(daily_cost)
    q5, q7 = fetch_quota()

    parts = [model]

    if ctx_pct is not None:
        parts.append(f"Ctx:{ctx_pct}%")

    if q5 is not None:
        q_str = f"5h:{q5:.0f}%"
        if q7 is not None:
            q_str += f" 7d:{q7:.0f}%"
        parts.append(q_str)

    # Always show daily; only show W/M once history exists
    history_days = len(_load_history())
    cost_parts = [f"D:{fmt_cost(daily_cost)}"]
    if history_days >= 1:
        cost_parts.append(f"W:{fmt_cost(w_cost)}")
    if history_days >= 7:
        cost_parts.append(f"M:{fmt_cost(m_cost)}")
    parts.append(" ".join(cost_parts))

    # Session cost (helps attribute spend to the current task)
    if session_today >= 0.0001:
        parts.append(f"sess:{fmt_cost(session_today)}")

    print(" | ".join(parts), end="")


if __name__ == "__main__":
    main()
