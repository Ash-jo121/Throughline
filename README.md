# Throughline

Throughline is a customer-escalation intelligence agent for the WeMakeDevs x Cognee
hackathon. It stores support incidents in Cognee memory, then recalls related past incidents
through the knowledge graph so a new customer escalation can surface the fix that worked before.

Day 1 is intentionally narrow: prove the command-line memory spine with local seed data, Cognee
`remember()`, Cognee `recall()`, and a passing cross-component acceptance test.

## Why Cognee Matters Here

The hero path is graph-first:

`new StripeTimeout -> PaymentService <- INC-2024-11 -> PR #1290`

The incoming ticket says "payments failing at checkout"; the old incident says "orders stuck in
pending state" and "Stripe webhook timeouts." A plain lexical search can chase the wrong generic
"failing/error" incident, but Cognee's graph can pivot through the shared `PaymentService`
component and return the old fix: exponential backoff for Stripe webhook retries.

Cognee references:

- [Cognee GitHub](https://github.com/topoteretes/cognee)
- [Cognee docs](https://docs.cognee.ai/)
- [Hackathon page](https://www.wemakedevs.org/hackathons/cognee)
- [Hackathon rules](https://www.wemakedevs.org/hackathons/cognee/rules)

## Setup

Use Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set `LLM_API_KEY`. Cognee needs an LLM key for graph extraction and graph
completion recall.

## Day 1 Commands

Backfill the seed incidents:

```powershell
.\.venv\Scripts\python.exe scripts\backfill.py
```

Run the hero recall:

```powershell
.\.venv\Scripts\python.exe scripts\demo_recall.py
```

Run the acceptance gate:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recall.py
```

Format:

```powershell
.\.venv\Scripts\python.exe -m ruff format .
```

## AI Disclosure

This project uses OpenAI Codex as a coding assistant.

<!-- Per hackathon rule 8, this must be declared
in the final submission. -->
