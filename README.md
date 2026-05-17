# Claude Code Cost Clock

A statusline script for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that shows real-time API cost in the status bar. Tracks daily, weekly, and monthly spending in dollars.

```
Sonnet 4.6 | 5h:29% 7d:52% | D:$0.14 | W:$3.21 | M:$18.50 | sess:$0.03
```

Reading left to right:

| Segment | Meaning |
|---|---|
| `Sonnet 4.6` | Active model |
| `5h:29% 7d:52%` | API quota consumption (macOS only) |
| `D:$0.14` | Today's total cost |
| `W:$3.21` | Rolling 7-day cost |
| `M:$18.50` | Rolling 30-day cost |
| `sess:$0.03` | Cost attributed to this session today |

W and M segments appear automatically once you have history (1+ and 7+ prior days).

## Installation

**30-second setup** — paste this into Claude Code:

> Please set up a custom statusline for me. Do the following:
>
> 1. Download `statusline.py` from `https://github.com/YOUR_USERNAME/claude-code-cost-clock` and save it to `~/.claude/cost_clock.py`
> 2. Run `chmod +x ~/.claude/cost_clock.py`
> 3. Run `claude config set --global statusline "python3 ~/.claude/cost_clock.py"` to enable it

Or manually:

```bash
curl -o ~/.claude/cost_clock.py https://raw.githubusercontent.com/YOUR_USERNAME/claude-code-cost-clock/main/statusline.py
chmod +x ~/.claude/cost_clock.py
claude config set --global statusline "python3 ~/.claude/cost_clock.py"
```

The statusline appears the next time you start a Claude Code session.

## costcount — shareable summaries

`costcount.py` generates copy-pasteable cost summaries from the accumulated history.

```bash
python3 costcount.py           # today + week + month (default)
python3 costcount.py -d        # today only
python3 costcount.py -w        # last 7 days
python3 costcount.py -m        # last 30 days
python3 costcount.py -t        # ASCII table with bar chart
python3 costcount.py --copy    # copy output to clipboard (macOS)
python3 costcount.py --json    # machine-readable JSON
```

Default output:

```
💸 Claude Code
   Today   $0.14  ·     3 sessions
   Week    $3.21  ·    47 sessions
   Month  $18.50  ·   156 sessions
```

Table output (`-t`):

```
💸 Claude Code
   ┌───────┬────────┬──────────┬──────────────┐
   │       │   cost │ sessions │              │
   ├───────┼────────┼──────────┼──────────────┤
   │ Today │  $0.14 │        3 │ █░░░░░░░░░   │
   │  Week │  $3.21 │       47 │ ████████░░   │
   │ Month │ $18.50 │      156 │ ██████████   │
   └───────┴────────┴──────────┴──────────────┘
```

**Optional: auto-print after each session.** Add a [Stop hook](https://docs.anthropic.com/en/docs/claude-code/hooks) to `~/.claude/settings.json`:

```json
"hooks": {
  "Stop": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "python3 '/path/to/costcount.py'"
        }
      ]
    }
  ]
}
```

## How it works

1. **Claude Code calls the script** on every status update (after each API call, during streaming). It pipes a JSON object with session data into stdin.
2. **The script reads `cost.total_cost_usd`** — Claude Code's built-in cumulative session cost — and uses it as the primary cost source. This is the most accurate number available.
3. **Fallback:** If `cost.total_cost_usd` is zero or absent, cost is computed from token counts using published pricing constants (see table below).
4. **Daily totals persist** across sessions in `~/.claude/cost_clock_daily.json`. Multiple concurrent sessions are handled safely with file locking.
5. **At midnight**, the previous day's totals are archived to `~/.claude/cost_clock_history.jsonl` and the daily counter resets. Sessions that span midnight have their baseline updated so yesterday's spend isn't attributed to today.

No cron jobs, no daemons. You just use Claude Code and the numbers accumulate.

### Data files

| File | Purpose |
|---|---|
| `~/.claude/cost_clock_daily.json` | Today's running totals, per-session |
| `~/.claude/cost_clock_history.jsonl` | Historical daily log, one entry per day |
| `~/.claude/cost_clock_quota.json` | Cached quota data (5-minute TTL) |

All files use owner-only permissions (`0600`).

## Pricing constants

The fallback cost computation uses these published rates (as of May 2026):

| Model | Input $/M | Output $/M | Cache read $/M | Cache write $/M |
|---|---|---|---|---|
| Haiku 4.5 | $1.00 | $5.00 | $0.10 | $1.25 |
| Sonnet 4.5 / 4.6 | $3.00 | $15.00 | $0.30 | $3.75 |
| Opus 4.5 / 4.6 / 4.7 | $5.00 | $25.00 | $0.50 | $6.25 |

Cache read = 10% of input (90% discount).
Cache write = 125% of input (5-minute TTL).

Source: [Anthropic pricing](https://www.anthropic.com/pricing)

**When does the fallback apply?** Only when Claude Code doesn't provide `cost.total_cost_usd` — which may happen in older versions or non-standard configurations. If you see the numbers diverge from your Anthropic billing dashboard, the primary source (API cost) is not being provided. Open an issue with your Claude Code version.

## Platform support

| Feature | macOS | Linux | Windows/WSL |
|---|---|---|---|
| Cost tracking | ✓ | ✓ | ✓ |
| Daily/weekly/monthly history | ✓ | ✓ | ✓ |
| API quota display | ✓ | — | — |

The quota display reads the OAuth token from macOS Keychain. On Linux and Windows/WSL the quota segment is silently omitted; everything else works.

**Note:** The quota display uses an **undocumented** Anthropic beta endpoint (`/api/oauth/usage` with `anthropic-beta: oauth-2025-04-20`). It may break without notice. Cost tracking does not depend on it.

## Dependencies

None. Python 3 standard library only (`json`, `os`, `sys`, `subprocess`, `fcntl`, `pathlib`, `datetime`, `urllib`).

`fcntl.flock` is available on macOS and Linux. On Windows outside WSL, the file locking would need an alternative.

## Security

- The OAuth token is read from macOS Keychain and sent only to `api.anthropic.com`. Never written to disk.
- All data files use `0600` permissions (owner read/write only).
- No telemetry, no third-party services, no analytics.

**Risk:** If someone modifies `~/.claude/cost_clock.py`, they get code execution in your user context on every Claude Code update. Same threat model as a shell alias or git hook. Keep the file owner-only writable.

## License

MIT

## Author

YOUR_NAME — [your website]

Built collaboratively with Claude Sonnet 4.6.
