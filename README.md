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

## What The Demo Shows

Throughline is not a mock ticket viewer. The winning demo path is:

1. Backfill real Cognee memory with historical incidents.
2. Import or create a new escalation from Jira-shaped ticket data.
3. Recall the closest prior incident through Cognee's graph, not keyword search.
4. Generate an operator-ready brief with source evidence, graph path, and recommended fix.
5. Improve future recall from thumbs-up/down feedback.
6. Forget customer-owned ticket memory while preserving shared incident knowledge.
7. Share the brief to Slack for escalation handoff.

The app can run with demo data only, but the integration surface is production-shaped: Jira Cloud
REST import, Slack incoming webhook share, persisted feedback, and customer data deletion records.

## Architecture

- Seed incidents and incoming tickets are serialized into extraction-friendly text.
- `cognee.remember()` writes them into a typed Throughline ontology.
- `cognee.recall()` runs graph completion with a per-brief session id and feedback influence.
- The synthesizer turns graph recall into a structured `IncidentBrief`.
- SQLite stores brief payloads, recall `session_id`/`qa_id`, feedback, forget requests, and
  customer-owned Cognee `data_id`s.
- FastAPI exposes incident creation, Jira import, brief retrieval, Slack share, feedback/improve,
  demo memory controls, and customer forget routes.
- React renders a command-center UI with the full memory lifecycle, integration health, source
  evidence, graph path, brief actions, and demo controls.

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

Optional real integrations:

```text
JIRA_SITE_URL="https://your-domain.atlassian.net"
JIRA_EMAIL="you@example.com"
JIRA_API_TOKEN="..."
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

Jira uses Atlassian Cloud Basic auth with email + API token against REST API v3 issue reads.
Slack uses an incoming webhook URL. Keep both out of source control.

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
.\.venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000
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
- `GET /integrations`: report Jira and Slack readiness.
- `GET /integrations/jira/issues/{issue_key}`: fetch a real Jira Cloud issue.
- `POST /integrations/jira/issues/{issue_key}/brief`: import Jira -> recall -> synthesize.
- `GET /briefs/{brief_id}`: load a shareable brief.
- `POST /briefs/{brief_id}/share/slack`: send the current brief to Slack.
- `POST /briefs/{brief_id}/feedback`: store feedback, submit `FeedbackEntry`, run `improve()`.
- `POST /customers/{name}/forget`: resolve alias, forget customer-owned `data_id`s, mark done.
- `POST /demo/reset`: clear Cognee memory for a clean demo.
- `POST /demo/backfill`: reset and load the historical incident set.

## Judge Demo Script

1. Start backend and frontend, then open the command-center page.
2. Click `Backfill demo memory`; point out that this calls Cognee `remember()`.
3. Create the Acme `PaymentService` / `StripeTimeout` escalation or import a configured Jira key.
4. Show the recalled path `PaymentService -> INC-2024-11 -> PR #1290 -> Priya`.
5. Explain the generated brief: matched incident, recommended fix, source evidence, and next steps.
6. Click a feedback button and show the `improve()` status.
7. Use Slack share if `SLACK_WEBHOOK_URL` is configured; otherwise show the button's real config error.
8. Run customer forget for `Acme Corp` and show the completed `forget()` count.

For hackathon judging, the Jira/Slack controls are intentionally real but optional: the app remains
demoable without leaking credentials, and the integration health badges make that transparent.

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
