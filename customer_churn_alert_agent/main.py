"""CLI for the customer churn alert agent.

Examples:

    uv run python main.py
    uv run python main.py --verbose
    uv run python main.py --top 8
    uv run python main.py --no-llm
    uv run python main.py --as-of "2026-07-20"
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="churn-agent",
        description="Detect customers at risk of churning.",
    )

    parser.add_argument(
        "--db",
        default=None,
        help="SQLite path (default: qcommerce.db)",
    )

    parser.add_argument(
        "--model",
        default=None,
        help="Groq model",
    )

    parser.add_argument("--top", type=int, default=8,)
    parser.add_argument(
        "--as-of",
        default=None,
        help="Freeze analysis clock",
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Run deterministic churn engine only",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show agent tool calls",
    )

    args = parser.parse_args()
    args.top = max(1, min(args.top, 8))

    from churn_agent import db, report
    from churn_agent.config import db_path, freeze_as_of
    from churn_agent.metrics import churn

    freeze_as_of(args.as_of)

    db.configure(
        db_path(args.db)
    )

    # ------------------------------------------------------------------ #
    # Deterministic mode
    # ------------------------------------------------------------------ #

    if args.no_llm:
        print(
            report.render_scores(
                churn.scores(),
                top=args.top,
            )
        )
        return 0

    # ------------------------------------------------------------------ #
    # LLM mode
    # ------------------------------------------------------------------ #

    from churn_agent.agent import build_agent, run

    print(
        "Running churn analysis (3 subagents)...",
        file=sys.stderr,
    )

    try:
        agent = build_agent(
            args.db,
            args.model,
            verbose=args.verbose,
        )

        state = run(
            agent,
            top=args.top,
        )

    except Exception as exc:
        error_text = str(exc)

        print(
            "\nAgent execution failed:",
            file=sys.stderr,
        )

        print(
            f"{type(exc).__name__}: {error_text}",
            file=sys.stderr,
        )

        # Groq 413 / TPM protection
        if (
            "413" in error_text
            or "tokens per minute" in error_text.lower()
            or "request too large" in error_text.lower()
        ):
            print(
                "\nThe Groq request exceeded your current TPM limit.",
                file=sys.stderr,
            )

            print(
                "Try one of these:",
                file=sys.stderr,
            )

            print(
                "  1. Reduce the tool-result size.",
                file=sys.stderr,
            )

            print(
                "  2. Use a model/tier with a higher TPM limit.",
                file=sys.stderr,
            )

            print(
                "  3. Run the deterministic engine:",
                file=sys.stderr,
            )

            print(
                "     uv run python main.py --no-llm",
                file=sys.stderr,
            )

        return 1

    # The stable agent prints a compact trace itself when --verbose is set.

    # ------------------------------------------------------------------ #
    # Structured response
    # ------------------------------------------------------------------ #

    structured = state.get(
        "structured_response"
    )

    if structured is None:
        print(
            "Agent did not return a structured report.",
            file=sys.stderr,
        )

        messages = state.get(
            "messages",
            [],
        )

        if messages:
            print(
                "\nRaw final response:\n",
                file=sys.stderr,
            )

            print(
                messages[-1].content
            )

        print(
            "\nFalling back to deterministic scores:\n",
            file=sys.stderr,
        )

        print(
            report.render_scores(
                churn.scores(),
                top=args.top,
            )
        )

        return 0

    # Pydantic model or dict
    if isinstance(
        structured,
        dict,
    ):
        payload = structured
    else:
        payload = structured.model_dump()

    print(
        report.render_report(
            payload,
            churn.scores(),
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )