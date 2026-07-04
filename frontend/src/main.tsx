import { StrictMode, useEffect, useMemo, useState } from "react";
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
  generated_at: string;
};

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function App() {
  const initialId = useMemo(() => {
    const pathMatch = window.location.pathname.match(/^\/brief\/([^/]+)$/);
    return pathMatch?.[1] ?? new URLSearchParams(window.location.search).get("brief_id") ?? "";
  }, []);
  const [briefId, setBriefId] = useState(initialId);
  const [brief, setBrief] = useState<IncidentBrief | null>(null);
  const [status, setStatus] = useState("Paste a brief id to load it.");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [actionStatus, setActionStatus] = useState("");

  useEffect(() => {
    if (initialId) {
      loadBrief(initialId);
    }
  }, [initialId]);

  async function loadBrief(id = briefId) {
    const trimmed = id.trim();
    if (!trimmed) {
      setStatus("Enter a brief id.");
      return;
    }

    setStatus("Loading brief...");
    setFeedbackStatus("");
    const response = await fetch(`${apiBase}/briefs/${encodeURIComponent(trimmed)}`);
    if (!response.ok) {
      setBrief(null);
      setStatus("Brief not found.");
      return;
    }

    const data = (await response.json()) as IncidentBrief;
    setBrief(data);
    setBriefId(data.brief_id);
    window.history.replaceState(null, "", `/brief/${encodeURIComponent(data.brief_id)}`);
    setStatus("Brief loaded.");
  }

  async function sendFeedback(verdict: "up" | "down") {
    if (!brief) return;
    setFeedbackStatus("Saving feedback...");
    const response = await fetch(`${apiBase}/briefs/${brief.brief_id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict })
    });
    setFeedbackStatus(response.ok ? "Feedback saved." : "Feedback failed.");
  }

  async function forgetCustomer() {
    if (!brief) return;
    setActionStatus("Submitting delete request...");
    const response = await fetch(`${apiBase}/customers/${encodeURIComponent(brief.customer)}/forget`, {
      method: "POST"
    });
    if (!response.ok) {
      setActionStatus("Delete request failed.");
      return;
    }
    const data = (await response.json()) as { forgotten_count: number };
    setActionStatus(`Deleted ${data.forgotten_count} customer-owned record${data.forgotten_count === 1 ? "" : "s"}.`);
  }

  async function shareBrief() {
    if (!brief) return;
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

  const briefUrl = brief ? `${window.location.origin}/brief/${encodeURIComponent(brief.brief_id)}` : "";

  return (
    <main className="shell">
      <section className="toolbar" aria-label="Brief lookup">
        <div>
          <p className="eyebrow">Throughline</p>
          <h1>Incident Brief</h1>
        </div>
        <form
          className="lookup"
          onSubmit={async (event) => {
            event.preventDefault();
            await loadBrief();
          }}
        >
          <input
            value={briefId}
            onChange={(event) => setBriefId(event.target.value)}
            placeholder="brief id"
            aria-label="Brief id"
          />
          <button type="submit">Load</button>
        </form>
      </section>

      <p className="status">{status}</p>

      {brief ? (
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
              <dt>Matched</dt>
              <dd>{brief.matched_incident_id ?? "No prior match"}</dd>
            </div>
          </dl>

          <section className="bodyGrid">
            <BriefBlock title="Probable Cause" value={brief.probable_cause} />
            <BriefBlock title="Why Related" value={brief.why_related} />
            <BriefBlock title="Recommended Fix" value={brief.recommended_fix} />
            <div className="panel">
              <h3>Also Affected</h3>
              <ChipList values={brief.also_affected} empty="None found" />
            </div>
            <div className="panel">
              <h3>Related Incidents</h3>
              <ChipList values={brief.related} empty="No related incident ids" />
            </div>
          </section>

          <footer className="feedback">
            <button type="button" onClick={async () => await sendFeedback("up")} aria-label="Mark helpful">
              Helpful
            </button>
            <button type="button" onClick={async () => await sendFeedback("down")} aria-label="Mark unhelpful">
              Not helpful
            </button>
            <span>{feedbackStatus}</span>
          </footer>

          <section className="shareBar" aria-label="Share and privacy actions">
            <input value={briefUrl} readOnly aria-label="Shareable brief link" />
            <button type="button" onClick={async () => await shareBrief()}>
              Share link
            </button>
            <button className="secondary" type="button" onClick={async () => await forgetCustomer()}>
              Forget customer
            </button>
            <span>{actionStatus}</span>
          </section>
        </article>
      ) : null}
    </main>
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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
