# Customer Churn Alert Agent

A teaching project that builds a **multi-agent LLM system** to find customers who
are quietly abandoning a quick-commerce app (think Blinkit / Zepto) — and does it
in a way you can actually trust.

A Python orchestrator runs three specialist analyst calls over compact evidence,
then a final Groq call synthesizes the report. Risk scores remain **100% deterministic**.

```
                    Python orchestrator
                           |
          +----------------+----------------+
          |                |                |
   usage-analyst     support-analyst   review-analyst
   login + orders       tickets          reviews
          |                |                |
          +----------------+----------------+
                           |
                    churn_scores()
                <-- plain Python, ONLY
                    source of scores
                           |
                    final Groq synthesis
                           |
                    ranked churn report
```

---

## What this project demonstrates

If you are here to learn, these are the ideas worth taking away:

1. **Multi-agent workflow.** Three focused analyst LLM calls handle usage,
   support, and reviews, followed by a final synthesis call. The Python layer
   executes the database tools first, avoiding fragile nested provider tool loops.
2. **Let code do the math, let the LLM do the judgement.** Every risk *number*
   is computed in ordinary Python ([scoring.py](churn_agent/scoring.py)); the LLM
   only explains and recommends. This makes runs reproducible and auditable —
   the same data always yields the same scores.
3. **Structured hand-offs.** Subagents return validated JSON (Pydantic models in
   [schemas.py](churn_agent/schemas.py)), not free text, so the orchestrator gets
   clean data instead of prose it has to parse.
4. **Honesty about the data.** Two of the three signals *cannot actually predict
   churn in this dataset*, and the agent is built to say so rather than invent a
   story. Knowing the limits of your data is half of data science. See
   [Why tickets and reviews don't predict churn](#why-tickets-and-reviews-dont-predict-churn).

---

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** (the package manager this repo uses)
- For the full agent run: a **Groq API key**. *You can skip this entirely and still run
  the deterministic analysis with `--no-llm`.*

---

## Quickstart

### 1. Install dependencies

```bash
uv sync
```

### 2. Use the included demo database

A working `qcommerce.db` is included so the project can run immediately. If you
want to regenerate the synthetic dataset, use:

```bash
uv run python quick_commerce_sim.py init --db ./qcommerce.db --days 120
```

### 3. Run the analysis with no API key

Start here — this runs every database query and the full scoring path using
**only Python**, no model and no credentials required. It's the fastest way to
see the system work:

```bash
uv run python main.py --no-llm
```

You should see a ranked table: ~8 HIGH risk, a couple of CONVERSION_RISK, one
NEVER_ACTIVATED, and the rest LOW. (See [Reading the output](#reading-the-output).)

### 4. Configure a model (for the full agent)

Copy the example env file and choose **one** backend:

```bash
cp .env.example .env
```

- **Groq**: put your API key in `.env`:
  ```
  GROQ_API_KEY=your-key-here
  ```
  Optional model override:
  ```
  CHURN_MODEL=openai/gpt-oss-20b
  ```

### 5. Run the full agent

```bash
uv run python main.py --verbose
```

`--verbose` prints the compact analyst/data-flow trace. Python executes the deterministic metric tools first, and the LLM calls have no external tools attached, so the workflow does not depend on nested provider tool-calling.

---

## Command reference

```bash
uv run python main.py                        # full agent run
uv run python main.py --no-llm               # scores only, no model/credentials
uv run python main.py --as-of "2026-07-20"   # freeze "today" for a repeatable run
uv run python main.py --top 20               # include more customers in the report
uv run python main.py --verbose              # show the agent's tool calls
uv run python main.py --model openai/gpt-oss-20b # override the model
```

| Flag | Default | Meaning |
|---|---|---|
| `--db` | `qcommerce.db` | Path to the SQLite database |
| `--model` | `openai/gpt-oss-20b` | Groq model (also settable via `CHURN_MODEL`) |
| `--top` | `12` | Max customers to include in the report |
| `--as-of` | now (IST) | Freeze the analysis clock for reproducible runs |
| `--no-llm` | off | Deterministic scores only; no model needed |
| `--verbose` | off | Print the agent's tool calls to stderr |

> **Tip:** pass `--as-of "2026-07-20 12:00:00"` whenever you want two runs to be
> comparable. Otherwise "days since last order" shifts a little every day as the
> clock moves.

---

## Reading the output

Every customer lands in exactly one **band**. The band, not the raw score, tells
you what to *do*:

| Band | Meaning | What to do |
|---|---|---|
| `HIGH` | No logins **and** no orders for weeks | Win them back |
| `CONVERSION_RISK` | Still opening the app, but not ordering | Fix conversion, not retention |
| `NEVER_ACTIVATED` | Signed up but never placed a first order | Onboarding |
| `MEDIUM` | Slipping — worth watching | Monitor |
| `LOW` | Healthy | Nothing |

The key design choice: **login recency and order recency are tracked separately.**
A customer who opened the app yesterday but hasn't ordered in six weeks has a
*conversion* problem, not a churn problem — collapsing both into one "days
inactive" number would hide that. That's why `CONVERSION_RISK` exists as its own
band.

Sample (`--no-llm`, as of 2026-07-20):

```
  HIGH=8  CONVERSION_RISK=2  MEDIUM=1  NEVER_ACTIVATED=1  LOW=28

HIGH RISK - likely churned, win-back
------------------------------------------------------------------------------
  [100] u41  Sanjay Bose (Kolkata)
        login 61d ago, order 61d ago, baseline 0.56/wk, state dormant
  ...
CONVERSION RISK - still visiting, not buying
------------------------------------------------------------------------------
  [ 61] u6   Tara Reddy (Pune)
        login 8d ago, order 31d ago, baseline 0.72/wk, state browsing_not_buying
```

The number in brackets is the 0–100 risk score.

---

## How one run works, step by step

1. **You run `main.py`.** It freezes the clock (so every metric agrees on
   "today"), points the code at the database, and builds the agent.
2. **The orchestrator sends each analyst one cohort-wide task** via the `task`
   tool. Each analyst calls its metric tool *once* to get a compact table for all
   40 customers — not once per customer.
3. **Each analyst returns validated JSON** (its Pydantic schema), so the
   orchestrator receives structured data, not prose.
4. **The orchestrator calls `churn_scores()`** — the deterministic scorer — and
   copies those numbers verbatim into the report.
5. **The report is rendered** to your terminal, grouped by band.

The `--no-llm` path skips steps 2–4 and calls the scorer directly. Same numbers,
no model.

---

## Guided tour of the code

Read the files in this order — it goes from "plain Python you can run today" up to
"the LLM wiring":

| # | File | What to learn from it |
|---|---|---|
| 1 | [quick_commerce_sim.py](quick_commerce_sim.py) | How the fake data (and the hidden churn) is generated. Standard library only. |
| 2 | [churn_agent/scoring.py](churn_agent/scoring.py) | The heart of it: how a customer is classified and scored, in pure Python. |
| 3 | [churn_agent/metrics/](churn_agent/metrics/) | The SQL and aggregation behind each signal. One file per domain; `churn.py` fuses them. |
| 4 | [churn_agent/tools.py](churn_agent/tools.py) | How Python functions become tools the LLM can call (`@tool`). |
| 5 | [churn_agent/schemas.py](churn_agent/schemas.py) | The Pydantic "contracts" each subagent must fill in. |
| 6 | [churn_agent/prompts.py](churn_agent/prompts.py) | What each agent is told to do. Read the comments — they explain *why*. |
| 7 | [churn_agent/agent.py](churn_agent/agent.py) | The wiring: three subagents plugged into `create_deep_agent`. |
| 8 | [main.py](main.py) & [churn_agent/report.py](churn_agent/report.py) | The CLI and how the report is printed. |

Supporting files: [config.py](churn_agent/config.py) (clock, credentials, model
factory) and [db.py](churn_agent/db.py) (read-only database access).

---

## The two big lessons

### Code computes the scores, not the LLM

All scoring lives in [scoring.py](churn_agent/scoring.py). The analyst schemas
have **no score field at all**, so an analyst literally has nowhere to write a
number even if it wanted to; the orchestrator copies scores from the
`churn_scores` tool. Ask an LLM to weigh "41 days inactive" against "2 open
tickets" and it will hand you a confident number that changes run to run. Here,
the numbers are reproducible and you can point to the exact line of code that
produced them.

**Want to change how risk is measured?** Edit `scoring.py` and re-run `--no-llm`.
Don't try to steer it through a prompt.

### Why tickets and reviews don't predict churn

This is the most important thing to understand about *this* dataset.

In [quick_commerce_sim.py](quick_commerce_sim.py), `gen_ticket` and `gen_review`
draw their category, priority, status, and rating from **fixed probabilities that
have nothing to do with whether a customer is about to leave.** There is no
"unhappy customer complains more, then churns" pattern baked in — because it was
never generated. Worse, tickets are created per-order, so a dormant customer has
*fewer* tickets simply because they stopped ordering. And half the customers have
no tickets at all.

So the honest conclusion is: **support and review data cannot predict churn
here.** Rather than have the agent invent a trend, the two analysts are scoped to
*corroboration* — they add colour ("this dormant customer also has an unresolved
refund ticket") that changes how you'd approach the customer, without pretending
to have predicted anything. Their total contribution to the score is capped at 15
of 100 points and can never push a healthy customer into a risk band.

**A great exercise:** make these signals *actually* predictive. In the simulator,
tie ticket rates and low ratings to the churn cutoff — raise complaints and drop
ratings in the weeks before a customer goes quiet — then lift the score cap in
`scoring.py` and watch the two analysts start to matter.

---

## Things to try

- **Change the risk thresholds.** In [scoring.py](churn_agent/scoring.py), what
  happens to the band counts if `DORMANT_LOGIN_DAYS` goes from 14 to 7? Re-run
  `--no-llm` to see.
- **Add a signal.** Failed logins are already in the database
  (`auth_audit_log`). Add a metric for them and fold it into the score.
- **Regenerate the data.** Set `RANDOM_SEED = None` at the top of the simulator
  and re-`init` to get a fresh cohort with a different churn distribution.
- **Compare models.** Run with `--model gemini-2.5-flash` vs
  `--model gemini-2.5-pro` and compare the *narratives* (the numbers won't
  change — that's the point).

---

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| `Database not found` | You skipped step 2. Run `quick_commerce_sim.py init`. |
| `No Gemini credentials found` | No key/project configured. Use `--no-llm`, or fill in `.env`. |
| `404 ... model ... was not found` (Vertex) | That model isn't enabled in your project/region. Try `--model gemini-2.5-flash` or `gemini-2.5-pro`. |
| `API key not valid` | The key in `.env` is wrong/expired. Get a new one from AI Studio. |
| `UnicodeEncodeError` on Windows | Set `PYTHONIOENCODING=utf-8` in your shell before running. |

> **Note on `quick_commerce_sim.py live`:** it accidentally reactivates dormant
> customers, which erodes the churn signal. Prefer a fresh `init` before
> analysing. (Details in [CLAUDE.md](CLAUDE.md).)

---

## Project layout

```
customer_churn_alert_agent/
├── main.py                     CLI entry point
├── quick_commerce_sim.py       synthetic data generator (stdlib only)
├── qcommerce.db                the database (generated; not in git)
└── churn_agent/
    ├── config.py               frozen clock, credentials, model factory
    ├── db.py                   read-only SQLite access
    ├── scoring.py              deterministic classification & scoring
    ├── metrics/                SQL + aggregation, one module per signal
    │   ├── usage.py            logins & orders  (the real churn signal)
    │   ├── support.py          support tickets  (corroboration only)
    │   ├── reviews.py          product reviews  (corroboration only)
    │   └── churn.py            fuses all three into scores
    ├── tools.py                @tool wrappers the agents call
    ├── schemas.py              Pydantic hand-off contracts
    ├── prompts.py              system prompts & task templates
    ├── agent.py                the deepagents wiring
    └── report.py               terminal rendering
```

Working on the code with an AI assistant? [CLAUDE.md](CLAUDE.md) captures the
non-obvious gotchas (deepagents quirks, the IST/UTC timezone trap, churn
semantics).
