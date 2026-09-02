"""Deterministic metric computation over the quick-commerce database.

Everything in this package is plain Python returning plain dicts: no LLM, no
API key, no LangChain. `main.py --no-llm` exercises all of it, which is how the
numbers get validated independently of any agent wiring.

Two conventions hold throughout:

* **No nulls.** "Never happened" is `-1`, not `None`. Nulls cost tokens and
  push the model into three-valued reasoning it gets wrong.
* **Short keys plus a legend.** Payloads land in an LLM context window, so rows
  use `dl`/`do`/`o30` and each result carries a one-time `legend` mapping.
"""

from __future__ import annotations

from datetime import datetime

from churn_agent.config import freeze_as_of


def days_since(timestamp: str | None) -> int:
    """Whole days from `timestamp` to the frozen clock. -1 if it never happened.

    Both sides are naive IST, matching how the simulator writes rows.
    """
    if not timestamp:
        return -1
    delta = freeze_as_of() - datetime.fromisoformat(timestamp)
    return max(0, delta.days)


def window_start(days: int) -> str:
    """ISO cutoff `days` before the frozen clock, for binding into SQL.

    Always prefer this over SQLite's datetime('now'), which returns UTC and is
    5h30m adrift from the stored IST timestamps.
    """
    from datetime import timedelta

    return (freeze_as_of() - timedelta(days=days)).isoformat(sep=" ", timespec="seconds")
