"""Stable multi-agent churn analysis.

The original version routed the orchestrator through DeepAgents' ``task`` tool.
That made the project unnecessarily sensitive to provider-specific tool-calling
behaviour. This version keeps the same three analyst roles, but Python performs
the deterministic metric queries and each analyst receives only the compact
facts it needs. A final LLM call synthesizes the report with a strict Pydantic
contract. There is no nested task/tool loop, so Groq's tool-choice quirks cannot
break the run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from churn_agent import db, prompts, tools
from churn_agent.config import as_of_iso, build_model, db_path
from churn_agent.schemas import (
    ChurnReport,
    ReviewFindings,
    SupportFindings,
    UsageFindings,
)


@dataclass
class ChurnAgent:
    model: object
    database: str
    verbose: bool = False

    def _call_structured(self, schema, system: str, payload: dict):
        """One model call with a Pydantic contract and no external tools."""
        structured = self.model.with_structured_output(
            schema,
            method="function_calling",
        )
        return structured.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
            ]
        )

    def run(self, top: int = 8) -> dict:
        top = max(1, min(int(top), 8))

        # Python does the database work. The LLM never has to discover or
        # calculate the numbers itself.
        usage = tools.usage_cohort_metrics.invoke({})
        support = tools.support_cohort_metrics.invoke({})
        review = tools.review_cohort_metrics.invoke({})
        scores = tools.churn_scores.invoke({"top_n": top})

        if self.verbose:
            print("  usage-analyst -> usage_cohort_metrics", flush=True)
            print("  support-analyst -> support_cohort_metrics", flush=True)
            print("  review-analyst -> review_cohort_metrics", flush=True)
            print("  orchestrator -> churn_scores", flush=True)

        usage_findings = self._call_structured(
            UsageFindings,
            prompts.USAGE_LLM_SYSTEM,
            {"as_of": as_of_iso(), "evidence": usage},
        )
        support_findings = self._call_structured(
            SupportFindings,
            prompts.SUPPORT_LLM_SYSTEM,
            {"as_of": as_of_iso(), "evidence": support},
        )
        review_findings = self._call_structured(
            ReviewFindings,
            prompts.REVIEW_LLM_SYSTEM,
            {"as_of": as_of_iso(), "evidence": review},
        )

        final_payload = {
            "as_of": as_of_iso(),
            "top": top,
            "scores": scores,
            "usage_analysis": usage_findings.model_dump(),
            "support_analysis": support_findings.model_dump(),
            "review_analysis": review_findings.model_dump(),
        }

        final = self._call_structured(
            ChurnReport,
            prompts.FINAL_LLM_SYSTEM,
            final_payload,
        )

        return {"structured_response": final, "messages": []}


def build_agent(
    database: str | None = None,
    model_name: str | None = None,
    verbose: bool = False,
) -> ChurnAgent:
    database_path = db_path(database)
    db.configure(database_path)
    model = build_model(model_name)
    return ChurnAgent(model=model, database=database_path, verbose=verbose)


def run(agent: ChurnAgent, top: int = 8) -> dict:
    """Run the stable three-analyst workflow."""
    return agent.run(top=top)
