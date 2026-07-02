# Throughline — Requirements & Handoff (Day 3 and beyond)

> This doc is self-contained — it explains what Throughline is, what's already built, and exactly what remains. Team **Wolfpack**, WeMakeDevs x Cognee hackathon, **deadline July 5**.

---

## 1. What Throughline is

A customer-escalation intelligence agent. It ingests support signals (Jira tickets, Sentry errors, GitHub PRs, Slack chats) into a **Cognee knowledge graph**. When a new incident arrives, it traverses the graph to surface _related past incidents and the fix that resolved them_ — connections a plain vector search would miss, because it links by shared **entities** (customer, component, error class), not by text similarity.

The hackathon scores **depth of Cognee use** heavily. The graph traversal must be the reason the product works, and we must visibly exercise all four memory-lifecycle APIs: `remember`, `recall`, `improve`, `forget`. Day 3 is where `improve` and `forget` get wired — so Day 3 is where a big chunk of the score is won.

## 2. Current state (Days 1–2 are DONE)

- **Graph spine:** Cognee running locally (embedded SQLite + LanceDB + Kuzu, no external DB). Typed ontology in `throughline/ontology.py`. Seed of 3 past incidents in `throughline/seed/incidents.py`, deliberately engineered so the demo query has a guaranteed cross-component hit.
- **Memory wrappers** (`throughline/memory.py`): `remember_incident()`, `remember_ticket()`, `recall_related()`, `reset_memory()`.
- **Synthesizer** (`throughline/synthesize.py`): turns an incoming ticket + recall output into a structured `IncidentBrief` via an LLM, with a deterministic regex fallback. Has an honesty guardrail (won't invent PRs/engineers).
- **Persistence** (`throughline/store.py`): SQLite. `briefs`, `feedback`, `forget_requests` tables. Briefs are addressable by `brief_id`.
- **API** (`api/app.py`, FastAPI): `POST /incidents`, `GET /briefs/{id}`, `POST /briefs/{id}/feedback`, `POST /customers/{name}/forget`. **The feedback and forget endpoints currently only STORE the request — they do NOT call Cognee yet. Wiring them is Day 3.**
- **Orchestration** (`throughline/service.py`): recall → synthesize → persist, then remember the ticket in the background (recall-before-remember, so the ticket never matches itself).
- **Frontend** (`frontend/`): minimal React dashboard rendering a brief.

### In flight (Ashish is handling — don't duplicate)

- Getting the OpenAI API key.

### The one empirical check that must pass before building further

The whole demo depends on Cognee merging the two "PaymentService" mentions into **one shared graph node**. After backfill with a real key, run the `COMPONENT_PROBE_QUERY` (in `seed/incidents.py`) and confirm only `INC-2024-11` comes back for PaymentService — not the SearchService/AuthService incidents. If the wrong incidents come back, the graph join isn't forming and must be fixed (strengthen the extraction prompt / canonicalize component names) before anything else.

## 3. Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # cognee>=1.0, fastapi, uvicorn, openai, pytest, pytest-asyncio, python-dotenv
cp .env.example .env                      # then set LLM_API_KEY=sk-...  (OpenAI; used for both LLM + embeddings)
# optional: LLM_MODEL=gpt-5.4  and  THROUGHLINE_SYNTH_MODEL=gpt-5.4-mini

python scripts/backfill.py                # loads seed into the graph
python scripts/demo_recall.py             # prints the hero recall answer (should cite PR #1290 / backoff)
pytest                                    # asyncio_mode=auto is set

uvicorn api.app:app --reload              # API on :8000
cd frontend && npm install && npm run dev # dashboard on :5173
```

Keep `.env` gitignored; commit only `.env.example`.

## 4. Cognee lifecycle API reference (verified against source — but re-confirm against the installed version, the API moves fast)

```python
import cognee
from cognee import SearchType
from cognee.memory import FeedbackEntry

# WRITE
await cognee.remember(text, dataset_name="throughline_day1",
                      graph_model=ThroughlineGraph, custom_prompt=EXTRACTION_PROMPT,
                      node_set=["throughline", ...], self_improvement=True)

# READ (multi-hop graph answer)
await cognee.recall(query_text=q, query_type=SearchType.GRAPH_COMPLETION,
                    datasets=["throughline_day1"], session_id="sess_1",   # session_id needed for feedback loop
                    feedback_influence=0.5, top_k=8)

# ENRICH + APPLY FEEDBACK  (Day 3)
await cognee.improve(dataset="throughline_day1", session_ids=["sess_1"])

# DELETE  (Day 3)
await cognee.forget(dataset="throughline_day1", data_id=some_uuid)   # surgical
await cognee.forget(dataset="throughline_day1")                      # whole dataset
await cognee.forget(everything=True)                                 # nuke
```

---

## 5. Day 3 requirements (the priority work)

### R1 — Wire feedback → `improve()` (the "learning" beat)

Cognee's feedback loop is **session-based**. The mechanism:

1. Run `recall_related()` **with a `session_id`** so the Q&A is cached in that session, and capture the resulting **`qa_id`** from the recall response.
2. When the engineer clicks thumbs-up/down in the dashboard, submit a `FeedbackEntry` to that session:
   ```python
   await cognee.remember(
       FeedbackEntry(qa_id=<qa_id>, feedback_text=note, feedback_score=+1),  # -1 for down
       session_id="sess_1",
   )
   ```
3. Call `improve(dataset="throughline_day1", session_ids=["sess_1"])`. This applies feedback weights to the graph nodes/edges that produced the answer — up-rated answers boost their source nodes, down-rated ones decrease them.
4. Future `recall(..., feedback_influence=...)` ranks the boosted fix higher.

**Requirement:** `POST /briefs/{id}/feedback` must (still store the signal, and) drive this loop. You'll need to persist the `session_id` and `qa_id` alongside each brief so feedback can reference them — add columns to the `briefs` table.

- **Minimum viable (if the full loop is fiddly):** on feedback, at least call `improve(dataset="throughline_day1")` for a bare enrichment pass so `improve()` is visibly exercised. This still counts, but the session-based version above is what scores "depth."
- **Verify** the exact `qa_id` retrieval from the recall response and the `feedback_score` range against the installed package before relying on it.

### R2 — Wire customer delete → `forget()` (the GDPR beat)

The compelling story: "customer requests account deletion → we surgically remove their incident history from the graph."

- **Surgical (preferred):** capture the `data_id` that `remember()` returns (`RememberResult`) for each ingested record, and store a `customer_name → [data_id]` map. On a forget request, call `forget(dataset="throughline_day1", data_id=<id>)` for each of that customer's items.
- **Fallback (if data_id capture is fiddly):** demo `forget(dataset=...)` on a per-customer dataset, or dataset-level deletion. Less surgical but still exercises the API.

**Requirement:** `POST /customers/{name}/forget` must (resolve the alias — already does — and) actually call Cognee `forget()`, then mark the stored request `status="done"`.

### R3 — Shareable brief (the delivery beat)

The premise is sending briefs to stakeholders and eng channels.

- `GET /briefs/{id}` already serves the brief. Add a **frontend route** (e.g. `/brief/:id`) that renders it cleanly from the id, so the URL itself is shareable.
- Add a **Slack incoming-webhook** post: a "Share to Slack" button that posts the brief's title + link to a channel (a single webhook URL, trivial to set up). Slack unfurls the link into a preview — that's the money demo moment. **Prioritize the share link over PDF.**

### R4 — Demo script + video

Write and rehearse the **four-beat demo** — this IS the rule-2 score:

1. **remember()** — backfill; the graph is populated with past incidents.
2. **recall()** — new Acme ticket → surfaces `INC-2024-11` / `PR #1290` via the cross-component graph hop. Say the line: _"different words, same component — vector search would miss this."_
3. **improve()** — thumbs-up the recommendation → feedback bridged into the graph → re-run recall and show the fix ranked higher.
4. **forget()** — Acme requests deletion → their incident history is surgically removed; re-run recall and show it's gone.
   Record a tight (<3 min) screen capture of this flow.

### R5 — README + AI disclosure

- README: what it is, the architecture, how to run, the four-API story.
- **Hackathon rule 8: declare every AI assistant used (Codex, and any others) in the submission.** Non-disclosure = disqualification. Put it in the README.

## 6. Day 3+ / stretch (only if time)

- **PDF export** of a brief (deferred; share link matters more).
- **Live GitHub integration** — `api.github.com` is easy (token auth, no OAuth); pull real PRs. The other sources stay as replayed fixtures.
- **Jira video transcription** — real tickets carry a screen-recording; transcribe (Whisper) → text before ingest. Deferred by design.
- **Multi-incident dashboard** — a list view of recent briefs.
- **Richer entity resolution** — beyond the current alias hashmap.

## 7. Constraints & gotchas

- **Deadline July 5.** A working, slightly rough end-to-end demo beats a polished half. Land R1–R4 before polishing.
- **Cognee is async-first** — everything is `await`ed; tests use `asyncio_mode="auto"`.
- **Don't skip the empirical component-join check** (§2) — it's the foundation everything else rests on.
- **Cost is trivial** — OpenAI at this volume is under $5 for the whole event; don't cheap out on the extraction model (a weak extractor silently breaks the graph join).
- **Re-verify Cognee signatures** against the installed version before trusting any call — the package's API has shifted across 2026 releases.
- The seed's distractor incident (SearchService) exists on purpose: it shares generic words like "failing"/"error" but sits in a different component, proving the graph picks the right incident. Don't "clean it up."
