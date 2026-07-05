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
- FastAPI exposes Jira import/webhook, brief retrieval, Slack share, feedback/improve, demo memory
  controls, and customer forget routes.
- React renders `/` as an incidents dashboard with Jira import, memory stats, customer privacy
  controls, and a clickable incident list. `/brief/:id` remains the shareable detail page with
  source evidence, feedback, and native share/copy-link controls.

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
JIRA_WEBHOOK_SECRET=""
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

Run the Day 3 lifecycle demo with visible before/after recall pairs:

```powershell
.\.venv\Scripts\python.exe scripts\demo_lifecycle.py
```

Reset to a clean dashboard state for recording:

```powershell
.\.venv\Scripts\python.exe scripts\reset_demo.py
```

This clears local brief state and Cognee memory, backfills the seed incidents, then generates one
matched brief and one low/no-match brief so the dashboard stats look believable.

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
```

Start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` for the incidents dashboard, or
`http://localhost:5173/brief/<brief_id>` for a shareable brief detail.

Reliable Jira fallback: import an existing issue by key and generate a brief:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/integrations/jira/issues/ESC-1/brief
```

Useful API routes:

- `GET /integrations`: report Jira and Slack readiness.
- `GET /integrations/jira/issues/{issue_key}`: fetch a real Jira Cloud issue.
- `POST /integrations/jira/issues/{issue_key}/brief`: import Jira -> recall -> synthesize.
- `POST /integrations/jira/webhook`: accept Jira issue-created webhooks quickly, then generate the
  brief in the background.
- `GET /briefs`: list all generated briefs, newest first, for the dashboard.
- `GET /briefs/latest`: load the newest generated brief after an async webhook run.
- `GET /briefs/{brief_id}`: load a shareable brief.
- `POST /briefs/{brief_id}/share/slack`: send the current brief to Slack.
- `POST /briefs/{brief_id}/feedback`: store feedback, submit `FeedbackEntry`, run `improve()`.
- `POST /customers/{name}/forget`: resolve alias, forget customer-owned `data_id`s, mark done.
- `POST /demo/reset`: clear Cognee memory for a clean demo.
- `POST /demo/backfill`: reset and load the historical incident set.

## Jira Workflow

In production, the sales/support team creates the ticket in Jira. Jira sends an issue-created
webhook to Throughline, and Throughline fetches the full issue by key before generating the brief.
For a local live test:

```powershell
ngrok http 8000
```

Create a Jira webhook or Jira Automation "Send web request" action:

- URL: `https://<your-tunnel>/integrations/jira/webhook`
- Optional secret: `https://<your-tunnel>/integrations/jira/webhook?secret=<JIRA_WEBHOOK_SECRET>`
- Event: issue created only

For the strongest demo match, create the Jira issue with:

- Summary: `Payments failing intermittently at checkout.`
- Labels: `customer:Acme-Corp`, `component:PaymentService`, `sentry:StripeTimeout`

If the tunnel or Jira delivery lags during the demo, trigger the reliable fallback:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/integrations/jira/issues/ESC-1/brief" -Method Post
```

## Judge Demo Script

1. Open the dashboard.
2. Run `scripts/reset_demo.py` before recording so the list and stats are clean.
3. Import a configured Jira key or create a Jira issue that fires the webhook.
4. Show the recalled path `PaymentService -> INC-2024-11 -> PR #1290 -> Priya`.
5. Explain the generated brief: matched incident, recommended fix, source links, and graph signals.
6. Click a feedback button and mention the session-scoped `improve()` call.
7. Use Slack share if `SLACK_WEBHOOK_URL` is configured; otherwise show the honest config error.
8. Use the dashboard Customers section to forget `Acme Corp` with confirmation.

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
