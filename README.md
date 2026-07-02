# Throughline

Throughline is a customer-escalation intelligence agent for the WeMakeDevs x Cognee
hackathon. It stores support incidents in Cognee memory, then recalls related past incidents
through the knowledge graph so a new customer escalation can surface the fix that worked before.

Day 1 is intentionally narrow: prove the command-line memory spine with local seed data, Cognee
`remember()`, Cognee `recall()`, and a passing cross-component acceptance test.

Day 2 adds the shareable incident brief layer: customer alias resolution, structured brief
synthesis, SQLite-backed brief URLs, a FastAPI surface, and a minimal dashboard.

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

Probe the make-or-break graph merge for `PaymentService`:

```powershell
.\.venv\Scripts\python.exe scripts\probe_graph.py
```

Run the acceptance gate:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recall.py
```

Run the Day 2 synthesizer gate:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_synthesize.py tests\test_service.py
```

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.app:app --reload
```

Start the dashboard:

```powershell
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173/?brief_id=<brief_id>`.

Format:

```powershell
.\.venv\Scripts\python.exe -m ruff format .
```

## AI Disclosure

This project uses OpenAI Codex and Claude as coding assistants. Per hackathon rule 8, this must be
declared in the final submission. The synthesizer defaults to OpenAI model `gpt-4.1-mini` via the
OpenAI SDK when `LLM_API_KEY` is available.
