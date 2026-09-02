"""Terminal rendering.

ASCII only: the default Windows console codepage raises UnicodeEncodeError on
box-drawing characters and currency symbols, which would crash the run at the
very last step after all the model work is already paid for.
"""

from __future__ import annotations

import textwrap

from churn_agent import db
from churn_agent.metrics.churn import BAND_ORDER

WIDTH = 78

BAND_HEADINGS = {
    "HIGH": "HIGH RISK - likely churned, win-back",
    "CONVERSION_RISK": "CONVERSION RISK - still visiting, not buying",
    "NEVER_ACTIVATED": "NEVER ACTIVATED - signed up, never ordered",
    "MEDIUM": "MEDIUM RISK - watch",
    "LOW": "LOW RISK - healthy",
}


def _rule(char: str = "-") -> str:
    return char * WIDTH


def _wrap(text: str, indent: str = "       ") -> str:
    return textwrap.fill(
        text, width=WIDTH, initial_indent=indent, subsequent_indent=indent
    )


def render_scores(scores: dict, top: int = 0) -> str:
    """Deterministic table with no model involvement. Used by --no-llm."""
    names = db.customer_names()
    out = [
        _rule("="),
        f"CHURN RISK - deterministic scores (as of {scores['as_of']} IST)",
        _rule("="),
        "",
        "  " + "  ".join(
            f"{band}={count}" for band, count in sorted(
                scores["band_counts"].items(), key=lambda kv: BAND_ORDER.get(kv[0], 9)
            )
        ),
        "",
    ]

    rows = scores["rows"][:top] if top else scores["rows"]
    current = None
    for r in rows:
        if r["band"] != current:
            current = r["band"]
            out += ["", BAND_HEADINGS.get(current, current), _rule()]
        name = names.get(r["u"], f"user {r['u']}")
        out.append(f"  [{r['score']:>3}] u{r['u']:<3} {name}")
        detail = (
            f"login {_days(r['dl'])}, order {_days(r['do'])}, "
            f"baseline {r['opw']}/wk, state {r['st']}"
        )
        out.append(_wrap(detail, "        "))
        if r["unres"] or r["neg"]:
            extra = []
            if r["unres"]:
                extra.append(f"{r['unres']} unresolved ticket(s)")
            if r["neg"]:
                extra.append(f"{r['neg']} negative review(s)")
            out.append(_wrap("also: " + ", ".join(extra), "        "))

    out += ["", _rule(), _wrap(scores["scoring_note"], "  "), ""]
    return "\n".join(out)


def _days(value: int) -> str:
    return "never" if value < 0 else f"{value}d ago"


def render_report(report: dict, scores: dict) -> str:
    """Render the agent's structured report."""
    names = db.customer_names()
    out = [
        _rule("="),
        f"CUSTOMER CHURN REPORT (as of {report.get('as_of', scores['as_of'])} IST)",
        _rule("="),
        "",
        _wrap(report.get("headline", ""), "  "),
        "",
        "  " + "  ".join(
            f"{band}={count}" for band, count in sorted(
                scores["band_counts"].items(), key=lambda kv: BAND_ORDER.get(kv[0], 9)
            )
        ),
    ]

    findings = sorted(
        report.get("findings", []),
        key=lambda f: (BAND_ORDER.get(f.get("band", ""), 9), -f.get("score", 0)),
    )

    current = None
    for f in findings:
        if f.get("band") != current:
            current = f.get("band")
            out += ["", "", BAND_HEADINGS.get(current, current), _rule()]
        name = names.get(f["u"], f"user {f['u']}")
        out.append(f"  [{f.get('score', 0):>3}] u{f['u']:<3} {name}")
        if f.get("why"):
            out.append(_wrap(f["why"], "        "))
        if f.get("corroboration"):
            out.append(_wrap("context: " + f["corroboration"], "        "))
        if f.get("action"):
            out.append(_wrap("-> " + f["action"], "        "))

    if report.get("caveats"):
        out += ["", "", "CAVEATS", _rule(), _wrap(report["caveats"], "  ")]
    out.append("")
    return "\n".join(out)
