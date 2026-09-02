"""LangChain tools for the customer churn Deep Agent.

The deterministic metric modules do the real data work. These wrappers are the
LLM boundary: they deliberately return compact, stable payloads so the agent
can reason about the important evidence without exhausting the model's context
or the Groq TPM limit.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.tools import tool

from churn_agent.metrics import churn as churn_metrics
from churn_agent.metrics import reviews as reviews_metrics
from churn_agent.metrics import support as support_metrics
from churn_agent.metrics import usage as usage_metrics


@lru_cache(maxsize=8)
def _usage_cohort(window_days: int, baseline_days: int) -> dict:
    return usage_metrics.cohort(window_days=window_days, baseline_days=baseline_days)


@lru_cache(maxsize=8)
def _support_cohort(window_days: int) -> dict:
    return support_metrics.cohort(window_days=window_days)


@lru_cache(maxsize=8)
def _reviews_cohort(window_days: int, recent_days: int) -> dict:
    return reviews_metrics.cohort(window_days=window_days, recent_days=recent_days)


@lru_cache(maxsize=8)
def _churn_scores(top_n: int) -> dict:
    return churn_metrics.scores(top_n=top_n)


@tool
def usage_cohort_metrics(window_days: int = 30, baseline_days: int = 90) -> dict:
    """Return compact usage evidence for customers needing attention.

    The deterministic usage metric still evaluates the full cohort. Only the
    relevant rows are exposed to the LLM because churn_scores is authoritative
    for ranking and scoring.
    """
    result = _usage_cohort(window_days, baseline_days)
    relevant_states = {"dormant", "browsing_not_buying", "at_risk", "never_ordered"}

    rows = [
        {
            "u": r["u"],
            "dl": r["dl"],
            "do": r["do"],
            "orec": r["orec"],
            "opw": r["opw"],
            "fc": r["fc"],
            "spd": r["spd"],
            "st": r["st"],
        }
        for r in result["rows"]
        if r["st"] in relevant_states
    ][:12]

    return {
        "as_of": result["as_of"],
        "window_days": window_days,
        "baseline_days": baseline_days,
        "n_customers": result["n_customers"],
        "rows": rows,
    }


@tool
def usage_customer_detail(user_id: int) -> dict:
    """Inspect one customer's usage timeline."""
    return usage_metrics.customer_detail(user_id, limit=8)


@tool
def support_cohort_metrics(window_days: int = 90) -> dict:
    """Return compact support friction evidence only.

    Support is corroboration, not a churn predictor, in this dataset.
    """
    result = _support_cohort(window_days)
    rows = [
        {
            "u": r["u"],
            "tk": r["tk"],
            "unres": r["unres"],
            "hi": r["hi"],
            "cat": r["cat"],
            "medh": r["medh"],
            "lastd": r["lastd"],
        }
        for r in result["rows"]
        if r["unres"] > 0 or r["hi"] > 0
    ][:10]

    return {
        "as_of": result["as_of"],
        "window_days": window_days,
        "n_customers": result["n_customers"],
        "n_with_tickets": result["n_with_tickets"],
        "rows": rows,
        "caveat": "Support data cannot predict churn; use it only to explain flagged customers.",
    }


@tool
def support_customer_detail(user_id: int) -> dict:
    """Inspect one customer's recent support tickets."""
    return support_metrics.customer_detail(user_id, limit=6)


@tool
def review_cohort_metrics(window_days: int = 90, recent_days: int = 30) -> dict:
    """Return compact negative-review evidence only.

    Reviews are corroboration, not a churn predictor, in this dataset.
    """
    result = _reviews_cohort(window_days, recent_days)
    rows = [
        {
            "u": r["u"],
            "n": r["n"],
            "avg": r["avg"],
            "d": r["d"],
            "neg": r["neg"],
            "lastd": r["lastd"],
            "last": r["last"],
        }
        for r in result["rows"]
        if r["neg"] > 0
    ][:10]

    return {
        "as_of": result["as_of"],
        "window_days": window_days,
        "recent_days": recent_days,
        "n_customers": result["n_customers"],
        "n_with_reviews": result["n_with_reviews"],
        "rows": rows,
        "caveat": "Review ratings/trends cannot predict churn; use reviews only as complaint evidence.",
    }


@tool
def review_customer_detail(user_id: int) -> dict:
    """Inspect one customer's recent reviews."""
    return reviews_metrics.customer_detail(user_id, limit=6)


@tool
def churn_scores(top_n: int = 8) -> dict:
    """Return deterministic churn scores and bands.

    This is the ONLY source of risk scores and bands. Never calculate or
    modify these values in the LLM layer.
    """
    top_n = max(1, min(int(top_n), 8))
    result = _churn_scores(top_n)

    # The legend is documentation, not reasoning data, so keep it out of the
    # model context. The tool docstring and orchestrator prompt define the keys.
    return {
        "as_of": result["as_of"],
        "n_customers": result["n_customers"],
        "band_counts": result["band_counts"],
        "rows": result["rows"],
        "scoring_note": result["scoring_note"],
    }


USAGE_TOOLS = [usage_cohort_metrics, usage_customer_detail]
SUPPORT_TOOLS = [support_cohort_metrics, support_customer_detail]
REVIEW_TOOLS = [review_cohort_metrics, review_customer_detail]
ORCHESTRATOR_TOOLS = [churn_scores]
