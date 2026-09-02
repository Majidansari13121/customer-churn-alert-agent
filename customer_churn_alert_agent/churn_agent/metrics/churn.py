"""Fuses the three domains into per-customer churn scores.

This is the single source of truth for every number in the final report. The
orchestrating agent calls it once and copies the values out; it does not
recompute, adjust, or average them.
"""

from __future__ import annotations

from churn_agent import db
from churn_agent.config import as_of_iso
from churn_agent.metrics import reviews as reviews_metrics
from churn_agent.metrics import support as support_metrics
from churn_agent.metrics import usage as usage_metrics
from churn_agent.scoring import band, behaviour_score, friction_modifier

BAND_ORDER = {"HIGH": 0, "CONVERSION_RISK": 1, "MEDIUM": 2, "NEVER_ACTIVATED": 3, "LOW": 4}

LEGEND = {
    "u": "user_id",
    "score": "0-100 churn risk (behaviour + capped friction)",
    "band": "HIGH | MEDIUM | LOW | CONVERSION_RISK | NEVER_ACTIVATED",
    "bhv": "behaviour component of score",
    "fric": "friction component, capped at 15",
    "st": "behavioural state",
    "dl": "days since last login (-1 = never)",
    "do": "days since last order (-1 = never)",
    "opw": "baseline orders per week",
    "unres": "unresolved tickets",
    "neg": "negative reviews (rating <= 2)",
}


def scores(top_n: int = 0, window_days: int = 30, baseline_days: int = 90) -> dict:
    """Ranked churn scores for the whole cohort.

    `top_n=0` returns every customer; a positive value truncates the row list
    while leaving the band counts computed over the full cohort.
    """
    usage = usage_metrics.cohort(window_days=window_days, baseline_days=baseline_days)
    support = support_metrics.cohort()
    review = reviews_metrics.cohort()

    support_by_user = {r["u"]: r for r in support["rows"]}
    review_by_user = {r["u"]: r for r in review["rows"]}

    rows = []
    for u in usage["rows"]:
        uid = u["u"]
        n_orders_known = u["do"] >= 0

        bhv = behaviour_score(
            days_login=u["dl"],
            days_order=u["do"],
            orders_per_week=u["opw"],
            confidence=u["fc"],
            n_orders=1 if n_orders_known else 0,
            state=u["st"],
        )

        s = support_by_user.get(uid, {})
        r = review_by_user.get(uid, {})
        fric = friction_modifier(
            unresolved_tickets=s.get("unres", 0),
            high_priority=s.get("hi", 0),
            negative_reviews=r.get("neg", 0),
        )

        total = min(100, bhv + fric)
        rows.append({
            "u": uid,
            "score": total,
            "band": band(total, u["st"]),
            "bhv": bhv,
            "fric": fric,
            "st": u["st"],
            "dl": u["dl"],
            "do": u["do"],
            "opw": u["opw"],
            "unres": s.get("unres", 0),
            "neg": r.get("neg", 0),
        })

    rows.sort(key=lambda x: (BAND_ORDER.get(x["band"], 9), -x["score"]))

    counts: dict[str, int] = {}
    for x in rows:
        counts[x["band"]] = counts.get(x["band"], 0) + 1

    return {
        "as_of": as_of_iso(),
        "n_customers": len(rows),
        "band_counts": counts,
        "legend": LEGEND,
        "rows": rows[:top_n] if top_n else rows,
        "scoring_note": (
            "Scores are computed deterministically in churn_agent/scoring.py. "
            "Behaviour (login and order recency vs the customer's own cadence) is the "
            "driver; support and review friction is capped at 15 points because those "
            "signals are generated independently of churn in this dataset and cannot "
            "move a healthy customer into a risk band on their own."
        ),
    }


def with_names(score_rows: list[dict]) -> list[dict]:
    """Attach display names. Done late, only for rows that reach the report."""
    names = db.customer_names()
    return [{**r, "name": names.get(r["u"], f"user {r['u']}")} for r in score_rows]
