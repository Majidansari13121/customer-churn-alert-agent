"""Login and ordering behaviour -- the primary churn signal.

Login recency and order recency are reported as *separate* features and never
blended. The distinction carries real information: a customer who logged in
four days ago but last ordered six weeks ago has a conversion problem, not a
churn problem, and order recency alone cannot tell those apart.

Baseline cadence is measured over the *prior* window rather than all history,
so a customer's recent dormancy does not dilute the very baseline it should be
measured against. It is tenure-denominated -- dividing order count by the span
between a customer's first and last order gives someone with a single order an
infinite-looking rate, which lands the most dormant buyer at the top of the
cadence table.
"""

from __future__ import annotations

from churn_agent import db
from churn_agent.metrics import days_since, window_start
from churn_agent.config import as_of_iso
from churn_agent.scoring import classify

LEGEND = {
    "u": "user_id",
    "dl": "days_since_last_login (-1 = never)",
    "do": "days_since_last_order (-1 = never)",
    "orec": "orders_in_recent_window",
    "opw": "baseline_orders_per_week (prior window, tenure-denominated)",
    "fc": "baseline confidence: high (>=3 prior orders) | low",
    "spd": "spend_change_pct, recent weekly rate vs prior weekly rate",
    "st": "active | at_risk | dormant | browsing_not_buying | never_ordered",
}


def _rows_by_user(sql: str, params: tuple = ()) -> dict[int, tuple]:
    return {r[0]: tuple(r)[1:] for r in db.query(sql, params)}


def cohort(window_days: int = 30, baseline_days: int = 90) -> dict:
    """Usage metrics for every customer, ranked most-inactive first."""
    recent_start = window_start(window_days)
    prior_start = window_start(window_days + baseline_days)

    signup = _rows_by_user(
        "SELECT user_id, created_at FROM users WHERE user_type='CUSTOMER'"
    )
    last_login = _rows_by_user(
        "SELECT user_id, MAX(event_timestamp) FROM auth_audit_log "
        "WHERE event_type='LOGIN' AND event_status='SUCCESS' GROUP BY user_id"
    )
    last_order = _rows_by_user("SELECT user_id, MAX(placed_at) FROM orders GROUP BY user_id")
    order_count = _rows_by_user("SELECT user_id, COUNT(*) FROM orders GROUP BY user_id")

    # Cancelled orders still signal engagement, so they count toward recency and
    # volume -- but they are excluded from spend, which should track revenue.
    recent = _rows_by_user(
        "SELECT user_id, COUNT(*), COALESCE(SUM(CASE WHEN order_status!='CANCELLED' "
        "THEN total_amount ELSE 0 END), 0) FROM orders WHERE placed_at >= ? GROUP BY user_id",
        (recent_start,),
    )
    prior = _rows_by_user(
        "SELECT user_id, COUNT(*), COALESCE(SUM(CASE WHEN order_status!='CANCELLED' "
        "THEN total_amount ELSE 0 END), 0) FROM orders "
        "WHERE placed_at >= ? AND placed_at < ? GROUP BY user_id",
        (prior_start, recent_start),
    )

    rows = []
    for uid in db.customer_ids():
        dl = days_since(last_login.get(uid, (None,))[0])
        do = days_since(last_order.get(uid, (None,))[0])
        n_orders = order_count.get(uid, (0,))[0]

        n_recent, spend_recent = recent.get(uid, (0, 0.0))
        n_prior, spend_prior = prior.get(uid, (0, 0.0))

        # Only count the part of the prior window the customer actually existed for.
        signup_days = days_since(signup.get(uid, (None,))[0])
        prior_days = min(baseline_days, max(signup_days - window_days, 0))
        prior_weeks = max(prior_days / 7.0, 1.0)
        opw = n_prior / prior_weeks

        recent_weekly = spend_recent / max(window_days / 7.0, 1.0)
        prior_weekly = spend_prior / prior_weeks
        if prior_weekly > 0:
            spd = round(100 * (recent_weekly - prior_weekly) / prior_weekly)
        else:
            spd = 0 if recent_weekly == 0 else 999

        rows.append({
            "u": uid,
            "dl": dl,
            "do": do,
            "orec": n_recent,
            "opw": round(opw, 2),
            "fc": "high" if n_prior >= 3 else "low",
            "spd": max(-100, min(999, spd)),
            "st": classify(dl, do, n_orders),
        })

    # Ranked in the tool so the model never has to sort numbers itself.
    # "Never" (-1) sorts as maximally inactive, not as zero.
    rows.sort(
        key=lambda r: (
            r["dl"] if r["dl"] >= 0 else 9999,
            r["do"] if r["do"] >= 0 else 9999,
        ),
        reverse=True,
    )

    states: dict[str, list[int]] = {}
    for r in rows:
        states.setdefault(r["st"], []).append(r["u"])

    return {
        "as_of": as_of_iso(),
        "recent_window_days": window_days,
        "baseline_window_days": baseline_days,
        "n_customers": len(rows),
        "legend": LEGEND,
        "rows": rows,
        "by_state": states,
    }


def customer_detail(user_id: int, limit: int = 12) -> dict:
    """Session and order timeline for one customer, for explaining a ranking."""
    who = db.query(
        "SELECT full_name, city, account_status, created_at FROM users WHERE user_id=?",
        (user_id,),
    )
    if not who:
        return {"error": f"No such user_id: {user_id}"}

    logins = db.query(
        "SELECT event_timestamp, device_type, app_version FROM auth_audit_log "
        "WHERE user_id=? AND event_type='LOGIN' AND event_status='SUCCESS' "
        "ORDER BY event_timestamp DESC LIMIT ?",
        (user_id, limit),
    )
    failed = db.query(
        "SELECT COUNT(*) c FROM auth_audit_log WHERE user_id=? AND event_type='LOGIN_FAILED'",
        (user_id,),
    )[0]["c"]
    orders = db.query(
        "SELECT placed_at, order_status, ROUND(total_amount, 2) amt FROM orders "
        "WHERE user_id=? ORDER BY placed_at DESC LIMIT ?",
        (user_id, limit),
    )

    return {
        "as_of": as_of_iso(),
        "u": user_id,
        "name": who[0]["full_name"],
        "city": who[0]["city"],
        "account_status": who[0]["account_status"],
        "signed_up_days_ago": days_since(who[0]["created_at"]),
        "failed_logins_all_time": failed,
        "recent_logins": [
            {"at": r["event_timestamp"], "dev": r["device_type"], "ver": r["app_version"]}
            for r in logins
        ],
        "recent_orders": [
            {"at": r["placed_at"], "st": r["order_status"], "amt": r["amt"]} for r in orders
        ],
    }
