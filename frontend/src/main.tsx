import { StrictMode, useEffect, useMemo, useState } from "react";
import { Root, createRoot } from "react-dom/client";
import "./styles.css";

declare global {
  interface Window {
    __throughlineRoot?: Root;
  }
}

type IncidentBrief = {
  brief_id: string;
  incident_ref: string;
  customer: string;
  component: string;
  title: string;
  probable_cause: string;
  matched_incident_id: string | null;
  why_related: string;
  recommended_fix: string;
  suggested_owner: string | null;
  also_affected: string[];
  confidence: "high" | "medium" | "low";
  related: string[];
  generated_at: string;
};

type IncidentForm = {
  id: string;
  raw_customer: string;
  component: string;
  summary: string;
  errorClass: string;
  service: string;
};

type IntegrationState = {
  jira?: { configured: boolean; auth: string };
  slack?: { configured: boolean; auth: string };
};

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const blankTicket: IncidentForm = {
  id: "",
  raw_customer: "",
  component: "",
  summary: "",
  errorClass: "",
  service: ""
};

function App() {
  const initialBriefId = useMemo(() => {
    const pathMatch = window.location.pathname.match(/^\/brief\/([^/]+)$/);
    return pathMatch?.[1] ?? new URLSearchParams(window.location.search).get("brief_id") ?? "";
  }, []);
  const [briefId, setBriefId] = useState(initialBriefId);
  const [brief, setBrief] = useState<IncidentBrief | null>(null);
  const [form, setForm] = useState<IncidentForm>(blankTicket);
  const [jiraKey, setJiraKey] = useState("");
  const [integrations, setIntegrations] = useState<IntegrationState>({});
  const [activity, setActivity] = useState("Ready for a live escalation.");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [forgetStatus, setForgetStatus] = useState("");
  const [shareStatus, setShareStatus] = useState("");
  const [memoryStatus, setMemoryStatus] = useState("Empty until you import or seed");
  const [isImportingJira, setIsImportingJira] = useState(false);
  const [isResettingMemory, setIsResettingMemory] = useState(false);
  const [isSeedingMemory, setIsSeedingMemory] = useState(false);

  useEffect(() => {
    void loadIntegrations();
    if (initialBriefId) {
      void loadBrief(initialBriefId);
    }
  }, [initialBriefId]);

  async function loadIntegrations() {
    try {
      const response = await fetch(`${apiBase}/integrations`);
      if (response.ok) {
        setIntegrations((await response.json()) as IntegrationState);
      }
    } catch {
      setIntegrations({});
    }
  }

  async function loadBrief(id = briefId) {
    const trimmed = id.trim();
    if (!trimmed) {
      setActivity("Enter a brief id.");
      return;
    }

    setActivity("Loading saved brief...");
    setFeedbackStatus("");
    let response: Response;
    try {
      response = await fetch(`${apiBase}/briefs/${encodeURIComponent(trimmed)}`);
    } catch {
      setBrief(null);
      setActivity("Could not reach the API on port 8000.");
      return;
    }
    if (!response.ok) {
      setBrief(null);
      setActivity("Brief not found.");
      return;
    }

    const data = (await response.json()) as IncidentBrief;
    setBrief(data);
    setBriefId(data.brief_id);
    window.history.replaceState(null, "", `/brief/${encodeURIComponent(data.brief_id)}`);
    setActivity("Brief loaded from SQLite.");
  }

  async function createIncident() {
    setActivity("Recalling Cognee graph memory...");
    setFeedbackStatus("");
    setForgetStatus("");
    setShareStatus("");
    let response: Response;
    try {
      response = await fetch(`${apiBase}/incidents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: form.id,
          raw_customer: form.raw_customer,
          component: form.component,
          summary: form.summary,
          sentry_error: form.errorClass
            ? {
                error_class: form.errorClass,
                service: form.service || form.component
              }
            : null
        })
      });
    } catch {
      setActivity("Could not reach the API on port 8000.");
      return;
    }

    if (!response.ok) {
      setActivity(await failureText(response, "Incident creation failed."));
      return;
    }

    const data = (await response.json()) as { brief_id: string; brief: IncidentBrief };
    setBrief(data.brief);
    setBriefId(data.brief_id);
    window.history.replaceState(null, "", `/brief/${encodeURIComponent(data.brief_id)}`);
    setActivity("recall() completed and a new brief was generated.");
  }

  async function importJiraIssue() {
    const key = jiraKey.trim();
    if (!key) {
      setActivity("Enter a Jira issue key.");
      return;
    }

    setActivity(`Importing ${key} from Jira Cloud...`);
    setIsImportingJira(true);
    const slowImportTimer = window.setTimeout(() => {
      setActivity(
        `Still importing ${key}. First run after reset can take about a minute while Cognee initializes memory.`
      );
    }, 8000);
    try {
      const response = await fetch(`${apiBase}/integrations/jira/issues/${encodeURIComponent(key)}/brief`, {
        method: "POST"
      });
      if (!response.ok) {
        setActivity(await failureText(response, "Jira import failed."));
        return;
      }

      const data = (await response.json()) as {
        issue_key: string;
        ticket: {
          id: string;
          raw_customer: string;
          component: string;
          summary: string;
          sentry_error?: { error_class?: string; service?: string };
        };
        brief_id: string;
        brief: IncidentBrief;
      };
      setForm({
        id: data.ticket.id,
        raw_customer: data.ticket.raw_customer,
        component: data.ticket.component,
        summary: data.ticket.summary,
        errorClass: data.ticket.sentry_error?.error_class ?? "",
        service: data.ticket.sentry_error?.service ?? data.ticket.component
      });
      setBrief(data.brief);
      setBriefId(data.brief_id);
      setMemoryStatus(`Remembered ${data.issue_key} for future recall`);
      window.history.replaceState(null, "", `/brief/${encodeURIComponent(data.brief_id)}`);
      setActivity(`${data.issue_key} imported from Jira and converted into a brief.`);
    } catch {
      setActivity("Could not reach the API on port 8000.");
    } finally {
      window.clearTimeout(slowImportTimer);
      setIsImportingJira(false);
    }
  }

  async function sendFeedback(verdict: "up" | "down") {
    if (!brief) return;
    setFeedbackStatus("Running improve()...");
    const response = await fetch(`${apiBase}/briefs/${brief.brief_id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict })
    });
    if (!response.ok) {
      setFeedbackStatus("Feedback failed.");
      return;
    }
    const result = (await response.json()) as { improve_scope: string };
    setFeedbackStatus(`Feedback stored and improve() ran at ${result.improve_scope} scope.`);
  }

  async function forgetCustomer() {
    if (!brief) return;
    setForgetStatus("Running forget()...");
    const response = await fetch(`${apiBase}/customers/${encodeURIComponent(brief.customer)}/forget`, {
      method: "POST"
    });
    if (!response.ok) {
      setForgetStatus("Forget failed.");
      return;
    }
    const data = (await response.json()) as { forgotten_count: number };
    setForgetStatus(`forget() completed for ${data.forgotten_count} customer-owned record(s).`);
  }

  async function shareSlack() {
    if (!brief) return;
    setShareStatus("Posting to Slack...");
    const response = await fetch(`${apiBase}/briefs/${brief.brief_id}/share/slack`, {
      method: "POST"
    });
    setShareStatus(response.ok ? "Shared to Slack." : await failureText(response, "Slack share failed."));
  }

  async function copyLink() {
    if (!brief) return;
    const url = `${window.location.origin}/brief/${brief.brief_id}`;
    await navigator.clipboard.writeText(url);
    setShareStatus("Brief link copied.");
  }

  async function resetDemo() {
    if (isResettingMemory || isSeedingMemory) return;
    setIsResettingMemory(true);
    setMemoryStatus("Resetting...");
    setActivity("Resetting Cognee memory...");
    const slowResetTimer = window.setTimeout(() => {
      setActivity("Still resetting memory. Cognee is clearing graph/vector stores.");
    }, 5000);
    try {
      const response = await fetch(`${apiBase}/demo/reset`, { method: "POST" });
      if (response.ok) {
        setMemoryStatus("Memory reset");
        setBrief(null);
        setBriefId("");
        setForm(blankTicket);
        setActivity("Memory reset. Import a Jira issue to start fresh.");
        window.history.replaceState(null, "", "/");
      } else {
        setMemoryStatus("Reset failed");
        setActivity(await failureText(response, "Reset failed."));
      }
    } catch {
      setMemoryStatus("Reset failed");
      setActivity("Could not reach the API on port 8000.");
    } finally {
      window.clearTimeout(slowResetTimer);
      setIsResettingMemory(false);
    }
  }

  async function backfillDemo() {
    if (isResettingMemory || isSeedingMemory) return;
    setIsSeedingMemory(true);
    setMemoryStatus("Running remember()...");
    setActivity("Seeding sample memory with Cognee remember()...");
    const slowSeedTimer = window.setTimeout(() => {
      setActivity("Still seeding memory. First Cognee graph extraction can take about a minute.");
    }, 8000);
    try {
      const response = await fetch(`${apiBase}/demo/backfill`, { method: "POST" });
      if (response.ok) {
        setMemoryStatus("remember() backfilled sample incidents");
        setActivity("Sample memory seeded.");
      } else {
        setMemoryStatus("Backfill failed");
        setActivity(await failureText(response, "Backfill failed."));
      }
    } catch {
      setMemoryStatus("Backfill failed");
      setActivity("Could not reach the API on port 8000.");
    } finally {
      window.clearTimeout(slowSeedTimer);
      setIsSeedingMemory(false);
    }
  }

  const graphNodes = graphEvidence(form, brief);

  return (
    <main className="appShell">
      <aside className="sidebar" aria-label="Throughline navigation">
        <div className="brandMark">T</div>
        <nav>
          <a href="#intake">In</a>
          <a href="#memory">Kg</a>
          <a href="#brief">Br</a>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Throughline command center</p>
            <h1>Escalation memory, from signal to fix</h1>
          </div>
          <div className="integrationStrip">
            <IntegrationBadge label="Jira" ready={Boolean(integrations.jira?.configured)} />
            <IntegrationBadge label="Slack" ready={Boolean(integrations.slack?.configured)} />
          </div>
        </header>

        <section className="statusBar" aria-live="polite">
          <strong>Run state</strong>
          <span>{activity}</span>
        </section>

        <section className="lifecycle">
          <LifecycleStep label="remember()" status={memoryStatus} active />
          <LifecycleStep label="recall()" status={brief ? "Matched prior fix" : "Awaiting incident"} active={Boolean(brief)} />
          <LifecycleStep label="improve()" status={feedbackStatus || "Awaiting feedback"} active={feedbackStatus.includes("ran")} />
          <LifecycleStep label="forget()" status={forgetStatus || "Awaiting delete request"} active={forgetStatus.includes("completed")} />
        </section>

        <section className="grid">
          <section className="surface intake" id="intake">
            <div className="sectionHeader">
              <div>
                <p className="eyebrow">Live signal</p>
                <h2>Incident intake</h2>
              </div>
              <button type="button" className="ghostButton" onClick={() => setForm(blankTicket)}>
                Clear form
              </button>
            </div>

            <div className="demoControls">
              <button
                type="button"
                className="ghostButton"
                onClick={resetDemo}
                disabled={isResettingMemory || isSeedingMemory}
              >
                {isResettingMemory ? "Resetting..." : "Reset memory"}
              </button>
              <button
                type="button"
                className="ghostButton"
                onClick={backfillDemo}
                disabled={isResettingMemory || isSeedingMemory}
              >
                {isSeedingMemory ? "Seeding..." : "Seed sample memory"}
              </button>
            </div>

            <div className="jiraImport">
              <label>
                <span>Jira issue key</span>
                <input value={jiraKey} onChange={(event) => setJiraKey(event.target.value)} />
              </label>
              <button type="button" onClick={importJiraIssue} disabled={isImportingJira}>
                {isImportingJira ? "Importing..." : "Import Jira"}
              </button>
            </div>

            <div className="formGrid">
              <TextField label="Ticket" value={form.id} onChange={(id) => setForm({ ...form, id })} />
              <TextField label="Customer" value={form.raw_customer} onChange={(raw_customer) => setForm({ ...form, raw_customer })} />
              <TextField label="Component" value={form.component} onChange={(component) => setForm({ ...form, component })} />
              <TextField label="Sentry error" value={form.errorClass} onChange={(errorClass) => setForm({ ...form, errorClass })} />
            </div>
            <label className="textAreaField">
              <span>Escalation summary</span>
              <textarea value={form.summary} onChange={(event) => setForm({ ...form, summary: event.target.value })} />
            </label>
            <button type="button" className="primaryButton" onClick={createIncident}>
              Generate brief
            </button>
          </section>

          <section className="surface" id="memory">
            <div className="sectionHeader">
              <div>
                <p className="eyebrow">Source evidence</p>
                <h2>Signals used by memory</h2>
              </div>
            </div>
            <div className="sourceGrid">
              <SourceCard title="Jira" value={form.id} detail={form.summary} state="live" />
              <SourceCard title="Sentry" value={form.errorClass || "Not attached"} detail={form.service} state="parsed" />
              <SourceCard title="GitHub" value={brief?.recommended_fix.match(/PR\s*#?\s*\d+/i)?.[0] ?? "Awaiting recall"} detail="Fix evidence from prior incident" state="memory" />
              <SourceCard title="Slack" value={integrations.slack?.configured ? "Webhook ready" : "Webhook missing"} detail={shareStatus || "Share generated brief"} state="pending" />
            </div>
          </section>

          <section className="surface graphPanel">
            <div className="sectionHeader">
              <div>
                <p className="eyebrow">Cognee graph route</p>
                <h2>Why this matched</h2>
              </div>
            </div>
            <div className="graphPath">
              {graphNodes.map((node, index) => (
                <div className="graphNode" key={`${node.label}-${index}`}>
                  <span>{node.type}</span>
                  <strong>{node.label}</strong>
                </div>
              ))}
            </div>
            <p className="graphNote">
              Graph extraction uses explicit entity index fields so repeated Jira signals can become shared graph
              pivots instead of one-off text matches.
            </p>
          </section>

          <section className="surface briefSurface" id="brief">
            <div className="sectionHeader">
              <div>
                <p className="eyebrow">Shareable output</p>
                <h2>Incident brief</h2>
              </div>
              <form
                className="lookup"
                onSubmit={(event) => {
                  event.preventDefault();
                  void loadBrief();
                }}
              >
                <input value={briefId} onChange={(event) => setBriefId(event.target.value)} placeholder="brief id" />
                <button type="submit" className="ghostButton">
                  Load
                </button>
              </form>
            </div>

            {brief ? (
              <BriefView
                brief={brief}
                feedbackStatus={feedbackStatus}
                forgetStatus={forgetStatus}
                shareStatus={shareStatus}
                onFeedback={sendFeedback}
                onForget={forgetCustomer}
                onCopy={copyLink}
                onSlack={shareSlack}
              />
            ) : (
              <div className="emptyState">
                <strong>No brief loaded</strong>
                <p>Import a Jira issue or enter your own escalation to see the full incident packet.</p>
              </div>
            )}
          </section>
        </section>
      </section>
    </main>
  );
}

function BriefView({
  brief,
  feedbackStatus,
  forgetStatus,
  shareStatus,
  onFeedback,
  onForget,
  onCopy,
  onSlack
}: {
  brief: IncidentBrief;
  feedbackStatus: string;
  forgetStatus: string;
  shareStatus: string;
  onFeedback: (verdict: "up" | "down") => Promise<void>;
  onForget: () => Promise<void>;
  onCopy: () => Promise<void>;
  onSlack: () => Promise<void>;
}) {
  return (
    <article className="brief">
      <header className="briefHeader">
        <div>
          <p className="eyebrow">{brief.incident_ref}</p>
          <h3>{brief.title}</h3>
        </div>
        <span className={`confidence ${brief.confidence}`}>{brief.confidence}</span>
      </header>

      <dl className="facts">
        <Fact label="Customer" value={brief.customer} />
        <Fact label="Component" value={brief.component} />
        <Fact label="Owner" value={brief.suggested_owner ?? "Unassigned"} />
        <Fact label="Matched" value={brief.matched_incident_id ?? "No prior match"} />
      </dl>

      <div className="briefBlocks">
        <BriefBlock title="Probable cause" value={brief.probable_cause} />
        <BriefBlock title="Why related" value={brief.why_related} />
        <BriefBlock title="Recommended fix" value={brief.recommended_fix} />
        <div className="miniPanel">
          <h4>Related memory</h4>
          <ChipList values={[...brief.related, ...brief.also_affected]} empty="No related memory found" />
        </div>
      </div>

      <footer className="actions">
        <button type="button" onClick={() => void onFeedback("up")}>
          Helpful
        </button>
        <button type="button" className="ghostButton" onClick={() => void onFeedback("down")}>
          Not useful
        </button>
        <button type="button" className="ghostButton" onClick={() => void onCopy()}>
          Copy link
        </button>
        <button type="button" className="ghostButton" onClick={() => void onSlack()}>
          Share Slack
        </button>
        <button type="button" className="dangerButton" onClick={() => void onForget()}>
          Forget customer
        </button>
      </footer>
      <div className="actionStatus">
        <span>{feedbackStatus}</span>
        <span>{shareStatus}</span>
        <span>{forgetStatus}</span>
      </div>
    </article>
  );
}

function IntegrationBadge({ label, ready }: { label: string; ready: boolean }) {
  return (
    <div className="systemState">
      <span className={ready ? "stateDot ready" : "stateDot"} />
      <div>
        <strong>{label}</strong>
        <small>{ready ? "Connected" : "Env missing"}</small>
      </div>
    </div>
  );
}

function LifecycleStep({ label, status, active }: { label: string; status: string; active: boolean }) {
  return (
    <div className={active ? "lifeStep active" : "lifeStep"}>
      <strong>{label}</strong>
      <span>{status}</span>
    </div>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label>
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function SourceCard({ title, value, detail, state }: { title: string; value: string; detail: string; state: "live" | "parsed" | "memory" | "pending" }) {
  return (
    <article className="sourceCard">
      <span className={`sourceState ${state}`}>{state}</span>
      <h3>{title}</h3>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function BriefBlock({ title, value }: { title: string; value: string }) {
  return (
    <div className="miniPanel">
      <h4>{title}</h4>
      <p>{value}</p>
    </div>
  );
}

function ChipList({ values, empty }: { values: string[]; empty: string }) {
  const unique = [...new Set(values)].filter(Boolean);
  if (!unique.length) {
    return <p className="muted">{empty}</p>;
  }

  return (
    <div className="chips">
      {unique.map((value) => (
        <span key={value}>{value}</span>
      ))}
    </div>
  );
}

function graphEvidence(form: IncidentForm, brief: IncidentBrief | null) {
  return [
    { type: "Ticket", label: form.id },
    { type: "Error", label: form.errorClass || "Optional error signal" },
    { type: "Component", label: brief?.component ?? (form.component || "Unknown component") },
    { type: "Incident", label: brief?.matched_incident_id ?? "Awaiting recall" },
    { type: "Fix", label: brief?.recommended_fix.match(/PR\s*#?\s*\d+/i)?.[0] ?? "Awaiting prior fix" }
  ];
}

async function failureText(response: Response, fallback: string) {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? fallback;
  } catch {
    return fallback;
  }
}

const rootElement = document.getElementById("root")!;
window.__throughlineRoot = window.__throughlineRoot ?? createRoot(rootElement);
window.__throughlineRoot.render(
  <StrictMode>
    <App />
  </StrictMode>
);
