"""Structured contracts between analysts and the orchestrator."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UsageRow(BaseModel):
    u: int
    dl: int
    do: int
    st: str
    note: str = Field(description="Short factual observation; no score.")


class UsageFindings(BaseModel):
    as_of: str
    n_customers: int
    rows: list[UsageRow] = Field(description="Important non-active customers only.")
    dormant_ids: list[int]
    browsing_not_buying_ids: list[int]
    caveats: str = Field(description="Brief data-quality caveat.")


class SupportRow(BaseModel):
    u: int
    tk: int
    unres: int
    cat: str
    note: str = Field(description="Short concrete support detail.")


class SupportFindings(BaseModel):
    as_of: str
    n_with_tickets: int
    rows: list[SupportRow]
    friction_ids: list[int]
    caveats: str = Field(description="Must state support does not predict churn.")


class ReviewRow(BaseModel):
    u: int
    n: int
    avg: float
    neg: int
    quote: str = Field(description="Short actual complaint, or empty string.")


class ReviewFindings(BaseModel):
    as_of: str
    n_with_reviews: int
    rows: list[ReviewRow]
    detractor_ids: list[int]
    caveats: str = Field(description="Must state review trends do not predict churn.")


class CustomerFinding(BaseModel):
    u: int
    band: str
    score: int
    why: str = Field(description="<=220 chars; cite behaviour numbers.")
    corroboration: str = Field(description="Support/review context or empty string.")
    action: str = Field(description="<=120 chars; practical intervention.")


class ChurnReport(BaseModel):
    as_of: str
    headline: str = Field(description="One concise sentence on cohort state.")
    findings: list[CustomerFinding]
    caveats: str = Field(description="Brief limitations of the analysis.")
