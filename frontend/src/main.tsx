import { StrictMode, useEffect, useMemo, useState } from "react";
import type { MouseEvent } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

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
  source_links: SourceLink[];
  generated_at: string;
};

type SourceLink = {
  label: string;
  url: string;
  kind: "jira" | "pull_request" | "sentry" | "other";
};

type FeedbackResponse = {
  feedback_id: string;
  status: string;
  improve_scope: string;
};

type ImportResponse = {
  brief_id: string;
  brief_path: string;
  brief_url: string;
  brief: IncidentBrief;
};

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function App() {
  const initialBriefId = useMemo(() => briefIdFromPath(), []);
  const [view, setView] = useState<"dashboard" | "brief">(initialBriefId ? "brief" : "dashboard");
  const [brief, setBrief] = useState<IncidentBrief | null>(null);
  const [briefs, setBriefs] = useState<IncidentBrief[]>([]);
  const [status, setStatus] = useState("Loading incidents...");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [correctionText, setCorrectionText] = useState("");
  const [correctionStatus, setCorrectionStatus] = useState("");
  const [correctionSubmitting, setCorrectionSubmitting] = useState(false);
  const [actionStatus, setActionStatus] = useState("");
  const [jiraKey, setJiraKey] = useState("ESC-1");
  const [importing, setImporting] = useState(false);
  const [forgettingCustomer, setForgettingCustomer] = useState("");

  useEffect(() => {
    if (initialBriefId) {
      void loadBrief(initialBriefId);
      return;
    }
    void loadDashboard();
  }, [initialBriefId]);

  useEffect(() => {
    if (view !== "dashboard") return;
    const interval = window.setInterval(() => {
      void loadDashboard({ silent: true });
    }, 5000);
    return () => window.clearInterval(interval);
  }, [view]);

  useEffect(() => {
    const onPopState = () => {
      const pathBriefId = briefIdFromPath();
      if (pathBriefId) {
        void loadBrief(pathBriefId, "replace");
        return;
      }
      setView("dashboard");
      setBrief(null);
      setFeedbackStatus("");
      setCorrectionText("");
      setCorrectionStatus("");
    setActionStatus("");
    setForgettingCustomer("");
    void loadDashboard({ silent: true });
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  });

  async function loadDashboard(options: { silent?: boolean } = {}) {
    if (!options.silent) {
      setStatus("Loading incidents...");
    }

    const response = await fetch(`${apiBase}/briefs`);
    if (!response.ok) {
      setStatus("Could not load incidents. Check that the API is running.");
      return;
    }

    const data = (await response.json()) as IncidentBrief[];
    setBriefs(data);
    if (!options.silent) {
      setStatus(data.length ? "" : "No incident briefs yet.");
    }
  }

  async function loadBrief(id: string, navigation: "push" | "replace" = "push") {
    const trimmed = id.trim();
    if (!trimmed) {
      setStatus("Enter a brief id.");
      return;
    }

    setStatus("Loading brief...");
    setFeedbackStatus("");
    setCorrectionText("");
    setCorrectionStatus("");
    setActionStatus("");
    const response = await fetch(`${apiBase}/briefs/${encodeURIComponent(trimmed)}`);
    if (!response.ok) {
      setBrief(null);
      setStatus("Brief not found.");
      return;
    }

    const data = (await response.json()) as IncidentBrief;
    openBrief(data, navigation);
    setStatus("Brief loaded.");
  }

  async function importFromJira() {
    const key = jiraKey.trim();
    if (!key) {
      setStatus("Enter a Jira issue key.");
      return;
    }

    setImporting(true);
    setStatus(`Importing ${key} from Jira...`);
    setActionStatus("");

    try {
      const response = await fetch(
        `${apiBase}/integrations/jira/issues/${encodeURIComponent(key)}/brief`,
        { method: "POST" }
      );
      if (!response.ok) {
        setStatus(await errorMessage(response));
        return;
      }

      const data = (await response.json()) as ImportResponse;
      setBriefs((current) => [data.brief, ...current.filter((item) => item.brief_id !== data.brief_id)]);
      openBrief(data.brief);
      setStatus(`Imported ${data.brief.incident_ref} from Jira.`);
    } finally {
      setImporting(false);
    }
  }

  async function sendFeedback(verdict: "up" | "down") {
    if (!brief) return;
    setFeedbackStatus("Saving feedback...");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(`${apiBase}/briefs/${brief.brief_id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict }),
        signal: controller.signal
      });
      if (!response.ok) {
        setFeedbackStatus("Feedback failed.");
        return;
      }
      const data = (await response.json()) as FeedbackResponse;
      setFeedbackStatus(
        `Feedback saved. Improve ${data.status === "applied" ? "applied" : "queued"} (${data.improve_scope}).`
      );
    } catch {
      setFeedbackStatus("Feedback timed out. Try again.");
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function submitCorrection() {
    if (!brief) return;
    const note = correctionText.trim();
    if (!note) {
      setCorrectionStatus("Enter a correction first.");
      return;
    }

    setCorrectionSubmitting(true);
    setCorrectionStatus("Applying correction to memory...");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 180000);
    try {
      const response = await fetch(`${apiBase}/briefs/${brief.brief_id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict: "up", note }),
        signal: controller.signal
      });
      if (!response.ok) {
        setCorrectionStatus("Correction failed.");
        return;
      }
      const data = (await response.json()) as FeedbackResponse;
      setCorrectionText("");
      setCorrectionStatus(
        `Correction applied to memory (${data.improve_scope}). Future related incidents can use it when recall surfaces the correction.`
      );
    } catch {
      setCorrectionStatus("Correction timed out. Check the API logs and try again.");
    } finally {
      window.clearTimeout(timeout);
      setCorrectionSubmitting(false);
    }
  }

  async function forgetCustomerFromDashboard(customer: string) {
    if (forgettingCustomer) return;
    const confirmation = window.prompt(
      `This permanently removes all ${customer} customer-owned data from Throughline memory. Type ${customer} to confirm.`
    );
    if (confirmation !== customer) {
      setActionStatus("Forget canceled.");
      return;
    }

    setForgettingCustomer(customer);
    setActionStatus(`Forgetting ${customer}...`);
    const slowForgetTimer = window.setTimeout(() => {
      setActionStatus(`Still forgetting ${customer}. Cognee is deleting customer-owned memory records...`);
    }, 5000);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 180000);
    try {
      const response = await fetch(`${apiBase}/customers/${encodeURIComponent(customer)}/forget`, {
        method: "POST",
        signal: controller.signal
      });
      if (!response.ok) {
        setActionStatus(await errorMessage(response));
        return;
      }
      const data = (await response.json()) as { forgotten_count: number; local_brief_count?: number };
      setBriefs((current) =>
        current
          .filter((item) => item.customer !== customer)
          .map((item) => ({
            ...item,
            also_affected: item.also_affected.filter((affectedCustomer) => affectedCustomer !== customer)
          }))
      );
      setActionStatus(
        `Forgot ${data.forgotten_count} memory record${data.forgotten_count === 1 ? "" : "s"} and ${
          data.local_brief_count ?? 0
        } brief${data.local_brief_count === 1 ? "" : "s"} for ${customer}.`
      );
    } catch {
      setActionStatus("Forget timed out or the API could not be reached. Check the API logs and try again.");
    } finally {
      window.clearTimeout(slowForgetTimer);
      window.clearTimeout(timeout);
      setForgettingCustomer("");
    }
  }

  async function shareBrief() {
    if (!brief) return;
    const briefUrl = currentBriefUrl(brief);
    const shareData = {
      title: brief.title,
      text: `${brief.customer} | ${brief.component} | ${brief.recommended_fix}`,
      url: briefUrl
    };

    try {
      if (navigator.share) {
        await navigator.share(shareData);
        setActionStatus("Share sheet opened.");
        return;
      }

      await navigator.clipboard.writeText(briefUrl);
      setActionStatus("Brief link copied.");
    } catch {
      setActionStatus("Share canceled.");
    }
  }

  function openBrief(nextBrief: IncidentBrief, navigation: "push" | "replace" = "push") {
    setBrief(nextBrief);
    setView("brief");
    setActionStatus("");
    setFeedbackStatus("");
    setCorrectionText("");
    setCorrectionStatus("");
    const path = `/brief/${encodeURIComponent(nextBrief.brief_id)}`;
    if (navigation === "replace") {
      window.history.replaceState(null, "", path);
    } else {
      window.history.pushState(null, "", path);
    }
  }

  function openDashboard() {
    setView("dashboard");
    setBrief(null);
    setFeedbackStatus("");
    setCorrectionText("");
    setCorrectionStatus("");
    setActionStatus("");
    window.history.replaceState(null, "", "/");
    void loadDashboard();
  }

  const briefUrl = brief ? currentBriefUrl(brief) : "";

  return (
    <main className="shell">
      <section className="toolbar" aria-label="Primary navigation">
        <div>
          <p className="eyebrow">Throughline</p>
          <h1>{view === "dashboard" ? "Incidents Dashboard" : "Incident Brief"}</h1>
        </div>
        <div className="toolbarActions">
          {view === "brief" ? (
            <a className="backLink" href="/" onClick={handleBackToDashboard(openDashboard)}>
              &larr; Back to incidents
            </a>
          ) : null}
        </div>
      </section>

      {status ? <p className="status">{status}</p> : null}

      {view === "dashboard" ? (
        <Dashboard
          briefs={briefs}
          jiraKey={jiraKey}
          importing={importing}
          forgettingCustomer={forgettingCustomer}
          actionStatus={actionStatus}
          onJiraKeyChange={setJiraKey}
          onImport={() => void importFromJira()}
          onOpenBrief={openBrief}
          onForgetCustomer={(customer) => void forgetCustomerFromDashboard(customer)}
        />
      ) : null}

      {view === "brief" && brief ? (
        <BriefDetail
          brief={brief}
          briefUrl={briefUrl}
          feedbackStatus={feedbackStatus}
          correctionText={correctionText}
          correctionStatus={correctionStatus}
          correctionSubmitting={correctionSubmitting}
          actionStatus={actionStatus}
          onFeedback={(verdict) => void sendFeedback(verdict)}
          onCorrectionChange={setCorrectionText}
          onSubmitCorrection={() => void submitCorrection()}
          onShare={() => void shareBrief()}
        />
      ) : null}
    </main>
  );
}

function Dashboard({
  briefs,
  jiraKey,
  importing,
  forgettingCustomer,
  actionStatus,
  onJiraKeyChange,
  onImport,
  onOpenBrief,
  onForgetCustomer
}: {
  briefs: IncidentBrief[];
  jiraKey: string;
  importing: boolean;
  forgettingCustomer: string;
  actionStatus: string;
  onJiraKeyChange: (value: string) => void;
  onImport: () => void;
  onOpenBrief: (brief: IncidentBrief) => void;
  onForgetCustomer: (customer: string) => void;
}) {
  const stats = dashboardStats(briefs);
  const customers = distinctCustomers(briefs);

  return (
    <section className="dashboard" aria-label="Incidents dashboard">
      <form
        className="importBar"
        onSubmit={(event) => {
          event.preventDefault();
          onImport();
        }}
      >
        <label>
          <span>Jira issue key</span>
          <input
            value={jiraKey}
            onChange={(event) => onJiraKeyChange(event.target.value)}
            placeholder="ESC-1"
            aria-label="Jira issue key"
          />
        </label>
        <button type="submit" disabled={importing}>
          {importing ? "Importing..." : "Import from Jira"}
        </button>
      </form>

      <section className="statsGrid" aria-label="Memory stats">
        <StatCard label="Incidents tracked" value={String(stats.total)} />
        <StatCard label="Prior context surfaced" value={`${stats.matches} of ${stats.total}`} />
        <StatCard label="Customers affected" value={String(stats.customers)} />
        <StatCard label="High-confidence briefs" value={String(stats.highConfidence)} />
      </section>

      <section className="incidentList" aria-label="Incident briefs">
        <header className="listHeader">
          <h2>Incidents</h2>
          <span>{briefs.length} total</span>
        </header>
        {briefs.length ? (
          <div className="incidentTable" role="table" aria-label="Incident brief list">
            <div className="incidentRow heading" role="row">
              <span>Incident</span>
              <span>Customer</span>
              <span>Component</span>
              <span>Prior context</span>
              <span>Confidence</span>
              <span>Generated</span>
            </div>
            {briefs.map((brief) => (
              <button
                className="incidentRow"
                type="button"
                role="row"
                key={brief.brief_id}
                onClick={() => onOpenBrief(brief)}
              >
                <span>
                  <strong>{brief.incident_ref}</strong>
                  <small>{brief.title}</small>
                </span>
                <span>{brief.customer}</span>
                <span>{brief.component}</span>
                <span>
                  {brief.matched_incident_id ? (
                    <span className="fixBadge">{brief.matched_incident_id}</span>
                  ) : (
                    <span className="muted">None</span>
                  )}
                </span>
                <span>
                  <span className={`badge ${brief.confidence}`}>{brief.confidence}</span>
                </span>
                <span>{formatDate(brief.generated_at)}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="emptyState">
            <h2>No incident briefs yet</h2>
            <p>Import a Jira issue key to generate the first brief.</p>
          </div>
        )}
      </section>

      <section className="customersSection" aria-label="Customer privacy controls">
        <header className="listHeader">
          <h2>Customers</h2>
          <span>{customers.length} accounts</span>
        </header>
        <div className="customerGrid">
          {customers.map((customer) => (
            <div className="customerRow" key={customer}>
              <span>{customer}</span>
              <button
                className="secondary danger"
                type="button"
                disabled={Boolean(forgettingCustomer)}
                onClick={() => onForgetCustomer(customer)}
              >
                {forgettingCustomer === customer ? "Forgetting..." : "Forget customer"}
              </button>
            </div>
          ))}
        </div>
        {actionStatus ? <p className="status inlineStatus">{actionStatus}</p> : null}
      </section>
    </section>
  );
}

function BriefDetail({
  brief,
  briefUrl,
  feedbackStatus,
  correctionText,
  correctionStatus,
  correctionSubmitting,
  actionStatus,
  onFeedback,
  onCorrectionChange,
  onSubmitCorrection,
  onShare
}: {
  brief: IncidentBrief;
  briefUrl: string;
  feedbackStatus: string;
  correctionText: string;
  correctionStatus: string;
  correctionSubmitting: boolean;
  actionStatus: string;
  onFeedback: (verdict: "up" | "down") => void;
  onCorrectionChange: (value: string) => void;
  onSubmitCorrection: () => void;
  onShare: () => void;
}) {
  return (
    <article className="brief">
      <header className="briefHeader">
        <div>
          <p className="eyebrow">{brief.incident_ref}</p>
          <h2>{brief.title}</h2>
        </div>
        <span className={`badge ${brief.confidence}`}>{brief.confidence}</span>
      </header>

      <dl className="facts">
        <div>
          <dt>Customer</dt>
          <dd>{brief.customer}</dd>
        </div>
        <div>
          <dt>Component</dt>
          <dd>{brief.component}</dd>
        </div>
        <div>
          <dt>Owner</dt>
          <dd>{brief.suggested_owner ?? "Unassigned"}</dd>
        </div>
        <div>
          <dt>Prior match</dt>
          <dd>{brief.matched_incident_id ?? "No prior match"}</dd>
        </div>
      </dl>

      <section className="bodyGrid">
        <BriefBlock title="Probable Cause" value={brief.probable_cause} />
        <RelationBlock brief={brief} />
        <RecommendedFixBlock value={brief.recommended_fix} />
        <SourcesBlock brief={brief} />
        <div className="panel">
          <h3>Also Affected</h3>
          <ChipList values={brief.also_affected} empty="None found" />
        </div>
        <div className="panel">
          <h3>Related Records</h3>
          <ChipList
            values={brief.matched_incident_id ? brief.related : []}
            empty="No related records"
          />
        </div>
      </section>

      <footer className="feedback">
        <button type="button" onClick={() => onFeedback("up")} aria-label="Mark helpful">
          Helpful
        </button>
        <button type="button" onClick={() => onFeedback("down")} aria-label="Mark unhelpful">
          Not helpful
        </button>
        <span>{feedbackStatus}</span>
      </footer>

      <form
        className="correctionForm"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmitCorrection();
        }}
      >
        <label>
          <span>Suggest a better fix (optional)</span>
          <textarea
            value={correctionText}
            onChange={(event) => onCorrectionChange(event.target.value)}
            placeholder="Example: Backoff alone did not fully resolve this. The durable fix was PR #1350, making webhook handlers idempotent."
            rows={4}
          />
        </label>
        <div className="correctionActions">
          <button type="submit" disabled={correctionSubmitting || !correctionText.trim()}>
            {correctionSubmitting ? "Applying..." : "Submit fix"}
          </button>
          <span>{correctionStatus}</span>
        </div>
      </form>

      <section className="shareBar" aria-label="Share and privacy actions">
        <input value={briefUrl} readOnly aria-label="Shareable brief link" />
        <button type="button" onClick={onShare}>
          Share link
        </button>
        <span>{actionStatus}</span>
      </section>
    </article>
  );
}

function RelationBlock({ brief }: { brief: IncidentBrief }) {
  const sentry = brief.source_links.find((link) => link.kind === "sentry")?.label.replace("Sentry ", "");
  const signals = [brief.component, sentry].filter(Boolean) as string[];
  return (
    <div className="panel">
      <h3>Why Related</h3>
      <p>{brief.why_related}</p>
      <ChipList values={signals} empty="No shared graph signals" />
    </div>
  );
}

function SourcesBlock({ brief }: { brief: IncidentBrief }) {
  const links = brief.source_links.filter(
    (link) => link.kind !== "pull_request" || Boolean(brief.matched_incident_id)
  );
  return (
    <div className="panel">
      <h3>Sources</h3>
      {links.length ? (
        <div className="sourceLinks">
          {links.map((link) => (
            <a key={`${link.kind}-${link.url}`} href={link.url} target="_blank" rel="noreferrer">
              {link.label}
            </a>
          ))}
        </div>
      ) : (
        <p className="muted">No source links available</p>
      )}
    </div>
  );
}

function RecommendedFixBlock({ value }: { value: string }) {
  const steps = numberedSteps(value);
  return (
    <div className="panel">
      <h3>Recommended Fix</h3>
      {steps.length > 1 ? (
        <ol className="fixList">
          {steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      ) : (
        <p>{value}</p>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="statCard">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function BriefBlock({ title, value }: { title: string; value: string }) {
  return (
    <div className="panel">
      <h3>{title}</h3>
      <p>{value}</p>
    </div>
  );
}

function ChipList({ values, empty }: { values: string[]; empty: string }) {
  if (!values.length) {
    return <p className="muted">{empty}</p>;
  }

  return (
    <div className="chips">
      {values.map((value) => (
        <span key={value}>{value}</span>
      ))}
    </div>
  );
}

function dashboardStats(briefs: IncidentBrief[]) {
  const customers = distinctCustomers(briefs);
  return {
    total: briefs.length,
    matches: briefs.filter((brief) => Boolean(brief.matched_incident_id)).length,
    customers: customers.length,
    highConfidence: briefs.filter((brief) => brief.confidence === "high").length
  };
}

function distinctCustomers(briefs: IncidentBrief[]) {
  return Array.from(
    new Set(briefs.flatMap((brief) => [brief.customer, ...brief.also_affected]).filter(Boolean))
  ).sort((a, b) => a.localeCompare(b));
}

function briefIdFromPath() {
  const pathMatch = window.location.pathname.match(/^\/brief\/([^/]+)$/);
  return pathMatch?.[1] ?? new URLSearchParams(window.location.search).get("brief_id") ?? "";
}

function handleBackToDashboard(openDashboard: () => void) {
  return (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    openDashboard();
  };
}

function currentBriefUrl(brief: IncidentBrief) {
  return `${window.location.origin}/brief/${encodeURIComponent(brief.brief_id)}`;
}

async function errorMessage(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload.detail) return payload.detail;
  } catch {
    // Fall through to a status-based message.
  }
  return `Import failed with HTTP ${response.status}.`;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(date);
}

function numberedSteps(value: string) {
  const normalized = value.replace(/\s+/g, " ").trim();
  const matches = Array.from(normalized.matchAll(/(?:^|\s)(\d+)\.\s+/g));
  if (matches.length < 2) return [];

  return matches
    .map((match, index) => {
      const start = (match.index ?? 0) + match[0].length;
      const next = matches[index + 1];
      const end = next?.index ?? normalized.length;
      return normalized.slice(start, end).trim();
    })
    .filter(Boolean);
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
