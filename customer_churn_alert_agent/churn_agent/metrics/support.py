"""Support ticket friction.

Scope note: this is corroboration, not prediction. Ticket attributes in this
dataset are drawn independently of churn (see churn_agent.scoring), and half
the cohort has no tickets at all. What this module is genuinely good for is
answering "does this dormant customer have an unresolved complaint sitting
there?" -- which changes the intervention even when it did not predict the risk.

Rows are emitted only for customers with at least one ticket. Twenty rows of
zeroes would be a third of the payload carrying none of the information.
"""

from __future__ import annotations

from churn_agent import db
from churn_agent.metrics import days_since, window_start
from churn_agent.config import as_of_iso

OPEN_STATUSES = ("OPEN", "IN_PROGRESS", "WAITING_ON_CUSTOMER")

LEGEND = {
    "u": "user_id",
    "tk": "tickets_in_window",
    "unres": "unresolved (OPEN | IN_PROGRESS | WAITING_ON_CUSTOMER)",
    "hi": "HIGH or URGENT priority count",
    "cat": "most frequent category",
    "medh": "median hours to resolution (-1 = nothing resolved yet)",
    "lastd": "days since most recent ticket",
}


def _median(values: list[float]) -> float:
    if not values:
        return -1.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def cohort(window_days: int = 90) -> dict:
    """Ticket friction per customer, for customers who raised any."""
    start = window_start(window_days)
    tickets = db.query(
        "SELECT user_id, category, priority, status, created_at, resolved_at "
        "FROM support_tickets WHERE created_at >= ? ORDER BY user_id, created_at",
        (start,),
    )

    grouped: dict[int, list] = {}
    for t in tickets:
        grouped.setdefault(t["user_id"], []).append(t)

    rows = []
    for uid, items in grouped.items():
        unresolved = sum(1 for t in items if t["status"] in OPEN_STATUSES)
        high = sum(1 for t in items if t["priority"] in ("HIGH", "URGENT"))

        categories: dict[str, int] = {}
        for t in items:
            categories[t["category"]] = categories.get(t["category"], 0) + 1
        dominant = max(categories.items(), key=lambda kv: kv[1])[0]

        latencies = []
        for t in items:
            if t["resolved_at"]:
                from datetime import datetime

                delta = datetime.fromisoformat(t["resolved_at"]) - datetime.fromisoformat(
                    t["created_at"]
                )
                latencies.append(delta.total_seconds() / 3600)

        rows.append({
            "u": uid,
            "tk": len(items),
            "unres": unresolved,
            "hi": high,
            "cat": dominant,
            "medh": _median(latencies),
            "lastd": days_since(max(t["created_at"] for t in items)),
        })

    rows.sort(key=lambda r: (r["unres"], r["hi"], r["tk"]), reverse=True)

    n_customers = len(db.customer_ids())
    return {
        "as_of": as_of_iso(),
        "window_days": window_days,
        "n_customers": n_customers,
        "n_with_tickets": len(rows),
        "legend": LEGEND,
        "rows": rows,
        "friction_ids": [r["u"] for r in rows if r["unres"] > 0],
        "coverage_warning": (
            f"Only {len(rows)} of {n_customers} customers raised any ticket in this window. "
            "Ticket attributes in this dataset are generated independently of churn, and "
            "ticket volume tracks order volume -- so absence of tickets is NOT evidence of "
            "health, and presence is NOT evidence of churn. Use these as explanation only."
        ),
    }


def customer_detail(user_id: int, limit: int = 10) -> dict:
    """Full ticket history for one customer."""
    items = db.query(
        "SELECT ticket_id, category, priority, status, subject, created_at, resolved_at "
        "FROM support_tickets WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
    return {
        "as_of": as_of_iso(),
        "u": user_id,
        "n": len(items),
        "tickets": [
            {
                "id": t["ticket_id"],
                "cat": t["category"],
                "pri": t["priority"],
                "st": t["status"],
                "subj": t["subject"],
                "at": t["created_at"],
                "agedays": days_since(t["created_at"]),
                "resolved": bool(t["resolved_at"]),
            }
            for t in items
        ],
    }
