# AGENTS.md

## AI Collaboration

This project was built collaboratively with **Claude Sonnet 4.6** (Anthropic).

### Claude's contributions

- Wrote the initial `statusline.py` and `costcount.py` from scratch
- Designed the session-cost delta accounting logic (baseline tracking across day rollover)
- Sourced and verified the pricing constants from published Anthropic pricing
- Wrote the README methodology and platform support sections

### Human contributions

- Project concept and specification
- Review, testing, and validation against real Claude Code sessions
- Publishing and ongoing maintenance

### On AI co-authorship

Claude Code's hooks call `statusline.py` on every API response — meaning this script runs continuously alongside Claude Code during development. It's an odd recursion: Claude helped write the script that reports the cost of Claude writing the script.

The `Built collaboratively with Claude Sonnet 4.6` credit in the README and this file are an honest account of how the code was produced.
