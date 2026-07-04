# Throughline

Throughline is a customer-escalation memory agent for the WeMakeDevs x Cognee AI
hackathon. It remembers past incidents, recalls the fix that worked before, synthesizes a
shareable incident brief, learns from operator feedback, and forgets customer-owned data on
request.

The hero path is graph-first:

```text
new StripeTimeout ticket -> PaymentService <- INC-2024-11 -> PR #1290
```

A lexical search can chase the wrong generic outage. Throughline uses Cognee's graph to pivot
through shared components, Sentry errors, customers, incidents, pull requests, and engineers.

## Architecture

- Seed incidents and incoming tickets are serialized into extraction-friendly text.
- `cognee.remember()` writes them into a typed Throughline ontology.
- `cognee.recall()` runs graph completion with a per-brief session id and feedback influence.
- The synthesizer turns graph recall into a structured `IncidentBrief`.
- SQLite stores brief payloads, recall `session_id`/`qa_id`, feedback, forget requests, and
  customer-owned Cognee `data_id`s.
- FastAPI exposes incident creation, brief retrieval, feedback/improve, and customer forget routes.
- React renders the shareable `/brief/:id` page with feedback, forget, and native share/copy-link
  controls.

## Cognee Lifecycle Story

Throughline visibly exercises all four Cognee lifecycle APIs:

- `remember`: backfills incidents and stores incoming ticket memory.
- `recall`: retrieves the prior incident/fix before remembering the new ticket.
- `improve`: converts thumbs up/down feedback into `FeedbackEntry` and runs session-scoped
  `cognee.improve()`.
- `forget`: deletes customer-owned ticket data by captured `data_id` while keeping shared
  incident/PR knowledge.

## Setup

Use Python 3.11+ and Node.js 18+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set these in `.env`:

```text
LLM_API_KEY="..."
THROUGHLINE_PUBLIC_BASE_URL="http://localhost:5173"
```

## Runbook

Backfill seed incidents:

```powershell
.\.venv\Scripts\python.exe scripts\backfill.py
```

Run the make-or-break graph probe:

```powershell
.\.venv\Scripts\python.exe scripts\probe_graph.py
```

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.app:app --reload
```

Create a brief:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/incidents `
  -ContentType "application/json" `
  -Body '{"id":"JIRA-4821","raw_customer":"acme_corp","component":"PaymentService","summary":"Payments failing intermittently at checkout.","date":"2025-07-05","sentry_error":{"error_class":"StripeTimeout","service":"billing-worker"}}'
```

Start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173/brief/<brief_id>`.

Useful API routes:

- `POST /incidents`: recall -> synthesize -> persist, then remember ticket in the background.
- `GET /briefs/{brief_id}`: load a shareable brief.
- `POST /briefs/{brief_id}/feedback`: store feedback, submit `FeedbackEntry`, run `improve()`.
- `POST /customers/{name}/forget`: resolve alias, forget customer-owned `data_id`s, mark done.

## Verification

```powershell
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider
cd frontend
npm run build
```

The live graph probe writes a visualization to `.cognee/throughline_graph.html`.

## References

- [Cognee GitHub](https://github.com/topoteretes/cognee)
- [Cognee docs](https://docs.cognee.ai/)
- [Hackathon page](https://www.wemakedevs.org/hackathons/cognee)
- [Hackathon rules](https://www.wemakedevs.org/hackathons/cognee/rules)

## AI Disclosure

This project used OpenAI Codex and Claude as AI coding assistants. This disclosure is included for
hackathon rule 8.
