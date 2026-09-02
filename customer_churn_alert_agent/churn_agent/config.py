"""Process-wide configuration for the churn analysis agent."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_DB = "qcommerce.db"
LEGACY_MODELS = {
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
}
_as_of: datetime | None = None


def freeze_as_of(override: str | None = None) -> datetime:
    global _as_of
    if _as_of is None:
        if override:
            value = datetime.fromisoformat(override)
            if value.tzinfo is not None:
                value = value.astimezone(IST).replace(tzinfo=None)
            _as_of = value
        else:
            _as_of = datetime.now(IST).replace(tzinfo=None)
    return _as_of


def as_of_iso() -> str:
    return freeze_as_of().isoformat(sep=" ", timespec="seconds")


def load_env() -> None:
    from dotenv import load_dotenv
    load_dotenv()


def build_model(model_name: str | None = None):
    """Create the Groq chat model used by all four LLM calls.

    GPT-OSS 20B is currently available to the project and supports tool use and
    structured output. Low reasoning keeps small requests from spending the
    entire output budget on hidden reasoning tokens.
    """
    from langchain_groq import ChatGroq

    load_env()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("No GROQ_API_KEY found. Put GROQ_API_KEY=your_key in .env.")

    requested = model_name or os.getenv("CHURN_MODEL") or DEFAULT_MODEL
    if requested in LEGACY_MODELS:
        requested = DEFAULT_MODEL

    return ChatGroq(
        model=requested,
        temperature=0,
        api_key=api_key,
        reasoning_effort="low",
        # ChatGroq 1.1.x accepts provider-specific fields through model_kwargs.
        # GPT-OSS otherwise returns reasoning text and can consume the whole
        # small completion budget before producing the requested report.
        model_kwargs={"include_reasoning": False},
        max_tokens=600,
    )


def db_path(explicit: str | None = None) -> str:
    return explicit or os.getenv("CHURN_DB") or DEFAULT_DB
