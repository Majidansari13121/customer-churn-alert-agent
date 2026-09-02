"""Review sentiment.

Same scope caveat as support: ratings here are drawn from fixed weights with no
dependence on the customer or on their churn cutoff, so a "sentiment decline"
trend line is noise dressed as insight. What survives is the concrete detail --
this customer's last review said "Item was stale / expired" -- which is worth
putting in front of a human even though it did not predict anything.

The recent-vs-prior delta is reported only when a customer has enough reviews
for the comparison to mean anything. Below that it is emitted as 0.0 rather
than a number the model would be tempted to narrate.
"""

from __future__ import annotations

from churn_agent import db
from churn_agent.metrics import days_since, window_start
from churn_agent.config import as_of_iso

MIN_REVIEWS_FOR_TREND = 4

LEGEND = {
    "u": "user_id",
    "n": "reviews_in_window",
    "avg": "mean rating 1-5",
    "d": f"recent minus prior mean rating (0.0 when fewer than {MIN_REVIEWS_FOR_TREND} reviews)",
    "neg": "count of ratings <= 2",
    "lastd": "days since most recent review",
    "last": "most recent review title",
}


def cohort(window_days: int = 90, recent_days: int = 30) -> dict:
    """Rating profile per customer, for customers who left any review."""
    start = window_start(window_days)
    recent_cut = window_start(recent_days)

    reviews = db.query(
        "SELECT user_id, rating, review_title, review_text, created_at FROM reviews "
        "WHERE created_at >= ? ORDER BY user_id, created_at",
        (start,),
    )

    grouped: dict[int, list] = {}
    for r in reviews:
        grouped.setdefault(r["user_id"], []).append(r)

    rows = []
    for uid, items in grouped.items():
        ratings = [r["rating"] for r in items]
        recent = [r["rating"] for r in items if r["created_at"] >= recent_cut]
        prior = [r["rating"] for r in items if r["created_at"] < recent_cut]

        if len(items) >= MIN_REVIEWS_FOR_TREND and recent and prior:
            delta = round(sum(recent) / len(recent) - sum(prior) / len(prior), 2)
        else:
            delta = 0.0

        newest = max(items, key=lambda r: r["created_at"])
        rows.append({
            "u": uid,
            "n": len(items),
            "avg": round(sum(ratings) / len(ratings), 1),
            "d": delta,
            "neg": sum(1 for x in ratings if x <= 2),
            "lastd": days_since(newest["created_at"]),
            "last": newest["review_title"] or "",
        })

    rows.sort(key=lambda r: (r["neg"], -r["avg"]), reverse=True)

    n_customers = len(db.customer_ids())
    return {
        "as_of": as_of_iso(),
        "window_days": window_days,
        "recent_days": recent_days,
        "n_customers": n_customers,
        "n_with_reviews": len(rows),
        "legend": LEGEND,
        "rows": rows,
        "detractor_ids": [r["u"] for r in rows if r["neg"] > 0],
        "coverage_warning": (
            f"Only {len(rows)} of {n_customers} customers reviewed in this window, and many "
            "have one or two reviews. Ratings in this dataset are generated independently of "
            "churn, so rating trends do NOT predict it. Quote review text as colour; do not "
            "infer risk from it."
        ),
    }


def customer_detail(user_id: int, limit: int = 10) -> dict:
    """Recent reviews with text, for quoting in a report."""
    items = db.query(
        "SELECT r.rating, r.review_title, r.review_text, r.created_at, p.product_name "
        "FROM reviews r JOIN products p ON p.product_id = r.product_id "
        "WHERE r.user_id=? ORDER BY r.created_at DESC LIMIT ?",
        (user_id, limit),
    )
    return {
        "as_of": as_of_iso(),
        "u": user_id,
        "n": len(items),
        "reviews": [
            {
                "rating": r["rating"],
                "title": r["review_title"],
                "text": r["review_text"],
                "product": r["product_name"],
                "agedays": days_since(r["created_at"]),
            }
            for r in items
        ],
    }
