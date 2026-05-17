#!/usr/bin/env python3
"""costcount — shareable cost summaries from claude-code-cost-clock history.

Usage:
  python3 costcount.py           # today + week + month (default)
  python3 costcount.py -d        # today only
  python3 costcount.py -w        # last 7 days
  python3 costcount.py -m        # last 30 days
  python3 costcount.py -t        # ASCII table with bar chart
  python3 costcount.py --copy    # copy output to clipboard (macOS)
  python3 costcount.py --json    # machine-readable JSON

Built collaboratively with Claude Sonnet 4.6.
"""

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

CACHE_DIR    = Path.home() / ".claude"
DAILY_FILE   = CACHE_DIR / "cost_clock_daily.json"
HISTORY_FILE = CACHE_DIR / "cost_clock_history.jsonl"


def load_history() -> dict[str, dict]:
    days: dict = {}
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    e = json.loads(line)
                    days[e["date"]] = e
                except Exception:
                    pass
    return days


def today_cost() -> tuple[float, int]:
    """Return (cost, sessions) from today's live file."""
    try:
        d = json.loads(DAILY_FILE.read_text())
        if d.get("date") == date.today().isoformat():
            cost = d.get("cost", 0.0)
            sessions = len(d.get("sessions", {}))
            return cost, sessions
    except Exception:
        pass
    return 0.0, 0


def range_totals(days: dict[str, dict], start: date, end: date,
                 today_c: float, today_s: int) -> tuple[float, int]:
    today_str = date.today().isoformat()
    cost = sessions = 0
    for dt_str, e in days.items():
        d = date.fromisoformat(dt_str)
        if start <= d <= end and dt_str != today_str:
            cost     += e.get("cost",     0.0)
            sessions += e.get("sessions", 0)
    if start <= date.today() <= end:
        cost     += today_c
        sessions += today_s
    return cost, sessions


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


def bar(value: float, maximum: float, width: int = 10) -> str:
    if maximum <= 0:
        return "░" * width
    filled = round(value / maximum * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def plain_output(rows: list[tuple[str, float, int]]) -> str:
    lines = ["💸 Claude Code"]
    label_w = max(len(r[0]) for r in rows)
    cost_w  = max(len(fmt_cost(r[1])) for r in rows)
    for label, cost, sessions in rows:
        lines.append(f"   {label:<{label_w}}  {fmt_cost(cost):>{cost_w}}  ·  {sessions:>4} sessions")
    return "\n".join(lines)


def table_output(rows: list[tuple[str, float, int]]) -> str:
    max_cost = max(r[1] for r in rows) if rows else 1.0
    label_w = max(len(r[0]) for r in rows)
    cost_w  = max(len(fmt_cost(r[1])) for r in rows)

    sep = f"   ├{'─'*(label_w+2)}┼{'─'*(cost_w+2)}┼{'─'*8}┼{'─'*12}┤"
    top = f"   ┌{'─'*(label_w+2)}┬{'─'*(cost_w+2)}┬{'─'*8}┬{'─'*12}┐"
    bot = f"   └{'─'*(label_w+2)}┴{'─'*(cost_w+2)}┴{'─'*8}┴{'─'*12}┘"
    hdr = f"   │ {'':>{label_w}} │ {'cost':>{cost_w}} │ {'sessions':>6} │ {'':12} │"

    lines = ["💸 Claude Code", top, hdr, sep]
    for label, cost, sessions in rows:
        b = bar(cost, max_cost, 10)
        lines.append(
            f"   │ {label:>{label_w}} │ {fmt_cost(cost):>{cost_w}} │ {sessions:>6} │ {b:12} │"
        )
    lines.append(bot)
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Cost summary for claude-code-cost-clock")
    p.add_argument("-d", "--day",   action="store_true", help="Today only")
    p.add_argument("-w", "--week",  action="store_true", help="Last 7 days only")
    p.add_argument("-m", "--month", action="store_true", help="Last 30 days only")
    p.add_argument("-t", "--table", action="store_true", help="ASCII table view")
    p.add_argument("--copy",        action="store_true", help="Copy to clipboard")
    p.add_argument("--json",        action="store_true", help="JSON output")
    args = p.parse_args()

    today = date.today()
    days  = load_history()
    today_c, today_s = today_cost()

    has_week  = any(
        today - timedelta(days=6) <= date.fromisoformat(dt) < today
        for dt in days
    )
    has_month = any(
        today - timedelta(days=29) <= date.fromisoformat(dt) < today
        for dt in days
    )

    rows: list[tuple[str, float, int]] = []

    if args.day or (not args.week and not args.month):
        rows.append(("Today", today_c, today_s))

    if args.week or (not args.day and not args.month):
        if has_week or args.week:
            c, s = range_totals(days, today - timedelta(days=6), today, today_c, today_s)
            rows.append(("Week", c, s))

    if args.month or (not args.day and not args.week):
        if has_month or args.month:
            c, s = range_totals(days, today - timedelta(days=29), today, today_c, today_s)
            rows.append(("Month", c, s))

    if args.json:
        out = [{"period": r[0], "cost_usd": round(r[1], 6), "sessions": r[2]}
               for r in rows]
        print(json.dumps(out, indent=2))
        return

    text = table_output(rows) if args.table else plain_output(rows)
    print(text)

    if args.copy:
        try:
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            print("\n(copied to clipboard)")
        except Exception:
            print("\n(pbcopy not available — copy manually)", file=sys.stderr)


if __name__ == "__main__":
    main()
