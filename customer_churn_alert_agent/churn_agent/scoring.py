"""Deterministic churn classification and scoring.

This module is the *only* producer of numeric risk scores. The analyst
subagents have no score field to write into and their prompts forbid inventing
one; the orchestrator copies scores from here verbatim. That split is
deliberate -- an LLM asked to weigh "41 days inactive" against "2 open tickets"
will produce a confident number that is not reproducible across runs.

On why support and review signals are capped:

    Reading quick_commerce_sim.py, `gen_ticket` (line 460) and `gen_review`
    (line 487) draw category, priority, status and rating from fixed weights
    with no reference to the user or to their `active_until` churn cutoff.
    There is no pre-churn degradation encoded in this dataset. Worse, tickets
    are generated per-order, so a dormant customer has fewer tickets purely as
    a recency artifact -- the signal points backwards.

    So friction is a bounded modifier, not a driver. It can sharpen the
    ordering within a band and give the report something to explain, but it
    cannot manufacture risk that behaviour does not already show.
"""

from __future__ import annotations

# A login inside this many days means the account is alive, whatever the orders say.
ALIVE_LOGIN_DAYS = 10
# No login for longer than this, and no orders either, means dormant.
DORMANT_LOGIN_DAYS = 14
# Orders older than this while still logging in = browsing but not buying.
STALE_ORDER_DAYS = 21

# Friction can add at most this much to a behaviour score of 0-100.
MAX_FRICTION = 15

# Login pressure reaches maximum here. Set wider than DORMANT_LOGIN_DAYS so the
# deepest-churned customers stay rankable against each other instead of all
# pinning at 100.
LOGIN_PRESSURE_DAYS = 45

# A customer the state machine calls dormant lands in HIGH even if the weighted
# arithmetic lands just short. Without this floor, `st` and `band` can disagree
# on the same row, which is indefensible in a report a human has to act on.
DORMANT_SCORE_FLOOR = 70

BANDS = ("HIGH", "MEDIUM", "LOW", "CONVERSION_RISK", "NEVER_ACTIVATED")


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def classify(days_login: int, days_order: int, n_orders: int) -> str:
    """Behavioural state. `-1` means the event never happened."""
    if n_orders == 0:
        return "never_ordered"

    never_logged_in = days_login < 0
    if not never_logged_in and days_login <= ALIVE_LOGIN_DAYS:
        # They are showing up. Whether they buy is a separate question.
        if days_order < 0 or days_order > STALE_ORDER_DAYS:
            return "browsing_not_buying"
        return "active"

    if never_logged_in or days_login > DORMANT_LOGIN_DAYS:
        return "dormant"
    return "at_risk"


def behaviour_score(
    days_login: int,
    days_order: int,
    orders_per_week: float,
    confidence: str,
    n_orders: int,
    state: str = "",
) -> int:
    """0-100 churn pressure from behaviour alone. Recency dominates."""
    if n_orders == 0:
        # Never activated. Pressure tracks how long they have been absent.
        return round(100 * _clamp01((days_login if days_login >= 0 else 999) / LOGIN_PRESSURE_DAYS))

    login_pressure = _clamp01(
        (days_login if days_login >= 0 else 999) / LOGIN_PRESSURE_DAYS
    )

    # Overdue relative to *their* rhythm, not a global constant: a weekly buyer
    # 20 days silent is a stronger signal than a monthly buyer 20 days silent.
    expected_gap = 7.0 / orders_per_week if orders_per_week > 0 else 21.0
    order_pressure = _clamp01(
        (days_order if days_order >= 0 else 999) / max(2 * expected_gap, 21.0)
    )

    if confidence == "high":
        weights = (0.50, 0.50)
    else:
        # Thin baseline: lean on login recency, which needs no baseline at all.
        weights = (0.70, 0.30)

    score = round(100 * (weights[0] * login_pressure + weights[1] * order_pressure))
    if state == "dormant":
        score = max(score, DORMANT_SCORE_FLOOR)
    return score


def friction_modifier(unresolved_tickets: int, high_priority: int, negative_reviews: int) -> int:
    """Bounded corroboration from support and review signals. Never a driver."""
    raw = 5 * min(unresolved_tickets, 2) + 3 * min(high_priority, 1) + 2 * min(negative_reviews, 1)
    return min(MAX_FRICTION, raw)


def band(score: int, state: str) -> str:
    """Risk band. Two states get their own band because the intervention differs."""
    if state == "never_ordered":
        return "NEVER_ACTIVATED"
    if state == "browsing_not_buying":
        return "CONVERSION_RISK"
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"
