import { ApiError, type AdminContent, type AdminDocument } from "@mandi/shared";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useApp } from "../lib/app-context";

/*
 * Staff-only page (English): sign in with the server's ADMIN_TOKEN, see what the advisory
 * features still need (reviews, data), and upload / approve storage documents.
 */

const TOKEN_KEY = "mandi.adminToken";

function readToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: the token is just not remembered */
  }
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 404) return "Admin is turned off on this server. Set ADMIN_TOKEN in the backend .env and restart it.";
    if (e.status === 401) return "Wrong admin token.";
    return e.message;
  }
  return "Could not reach the server.";
}

export function AdminPage() {
  const { api } = useApp();
  const [token, setToken] = useState(readToken);
  const [input, setInput] = useState("");
  const [content, setContent] = useState<AdminContent | null>(null);
  const [docs, setDocs] = useState<AdminDocument[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (t: string) => {
      setBusy(true);
      setError(null);
      try {
        const [c, d] = await Promise.all([api.adminContent(t), api.adminDocuments(t)]);
        setContent(c);
        setDocs(d);
        setToken(t);
        saveToken(t);
      } catch (e) {
        setContent(null);
        setToken("");
        saveToken(null);
        setError(errorText(e));
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  useEffect(() => {
    if (token) void load(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on first render / server change
  }, [api]);

  if (!token || !content) {
    return (
      <div className="mx-auto max-w-sm space-y-4 pt-4">
        <h2 className="text-2xl font-bold tracking-tight">Admin sign-in</h2>
        <form
          className="card space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void load(input.trim());
          }}
        >
          <div>
            <label className="label" htmlFor="admin-token">
              Admin token
            </label>
            <input id="admin-token" className="input" type="password" autoComplete="current-password" value={input} onChange={(e) => setInput(e.target.value)} />
            <p className="mt-1 text-sm text-muted">The ADMIN_TOKEN value from the backend .env file.</p>
          </div>
          {error && <p className="text-sm text-chilli-ink">{error}</p>}
          <button type="submit" className="btn-primary w-full" disabled={busy || !input.trim()}>
            {busy ? "Checking…" : "Sign in"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-2xl font-bold tracking-tight">Advisory content</h2>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => {
            saveToken(null);
            setToken("");
            setContent(null);
            setInput("");
          }}
        >
          Sign out
        </button>
      </div>
      <ContentStatus content={content} />
      <UploadForm token={token} onUploaded={() => void load(token)} />
      <DocumentList token={token} docs={docs} onChanged={() => void load(token)} />
    </div>
  );
}

function Count({ label, value, warn }: { label: string; value: string | number; warn?: boolean }) {
  return (
    <div className="rounded-lg bg-sunken p-3">
      <p className="eyebrow">{label}</p>
      <p className={`num mt-1 text-xl font-semibold ${warn ? "text-turmeric-ink" : ""}`}>{value}</p>
    </div>
  );
}

function ContentStatus({ content }: { content: AdminContent }) {
  const pending = content.pesticide_rows.pending ?? 0;
  const approved = content.pesticide_rows.approved ?? 0;
  const bulletin = content.agromet[0];
  return (
    <section className="card space-y-3" aria-label="Content status">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Count label="Pesticide rows to review" value={pending} warn={pending > 0} />
        <Count label="Pesticide rows approved" value={approved} warn={approved === 0} />
        <Count label="Documents approved" value={content.documents.approved ?? 0} warn={!content.documents.approved} />
        <Count label="KCC answers" value={content.kcc_answers} warn={content.kcc_answers === 0} />
      </div>
      <p className="text-sm">
        <span className="font-semibold">IMD bulletin: </span>
        {bulletin ? `${bulletin.district}, issued ${bulletin.issued_on}, valid till ${bulletin.valid_until}` : "none stored yet (run manage.py fetch-agromet)"}
      </p>
      <div className="text-sm">
        <p className="font-semibold">
          Schemes: {content.schemes.total} entries, {content.schemes.needs_attention.length} need attention
        </p>
        {content.schemes.needs_attention.length > 0 && (
          <ul className="mt-1 list-disc pl-5 text-muted">
            {content.schemes.needs_attention.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </div>
      <p className="text-xs text-muted">
        Pesticide rows are reviewed in review.csv (manage.py import-pesticides / approve-pesticides); schemes in backend/data/schemes/*.json.
      </p>
    </section>
  );
}

function UploadForm({ token, onUploaded }: { token: string; onUploaded: () => void }) {
  const { api, meta } = useApp();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [crop, setCrop] = useState("onion");
  const [language, setLanguage] = useState("mr");
  const [publisher, setPublisher] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [inputKey, setInputKey] = useState(0);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setMessage(null);
    try {
      const doc = await api.uploadDocument(token, { file, filename: file.name, title, crop, language, publisher, url });
      setMessage({ ok: true, text: `Added “${doc.title}” (${doc.passages} passages) as pending. Approve it below once it has been checked.` });
      setFile(null);
      setTitle("");
      setUrl("");
      setInputKey((k) => k + 1);
      onUploaded();
    } catch (err) {
      setMessage({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card space-y-3" aria-label="Add a storage document">
      <h3 className="text-lg font-semibold">Add a storage / post-harvest document</h3>
      <p className="text-sm text-muted">Official material only (ICAR-DOGR, CPRI, KVK, agricultural universities). PDF with text, Markdown or plain text.</p>
      <input key={inputKey} type="file" accept=".pdf,.md,.txt" className="input py-2" aria-label="Document file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <div>
        <label className="label" htmlFor="doc-title">
          Title
        </label>
        <input id="doc-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} required />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label" htmlFor="doc-crop">
            Crop
          </label>
          <select id="doc-crop" className="input" value={crop} onChange={(e) => setCrop(e.target.value)}>
            <option value="all">All crops</option>
            {meta?.crops.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="doc-lang">
            Language
          </label>
          <select id="doc-lang" className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="mr">Marathi</option>
            <option value="hi">Hindi</option>
            <option value="en">English</option>
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label" htmlFor="doc-publisher">
            Publisher
          </label>
          <input id="doc-publisher" className="input" placeholder="ICAR-DOGR" value={publisher} onChange={(e) => setPublisher(e.target.value)} maxLength={200} required />
        </div>
        <div>
          <label className="label" htmlFor="doc-url">
            Source link (optional)
          </label>
          <input id="doc-url" className="input" type="url" placeholder="https://" value={url} onChange={(e) => setUrl(e.target.value)} maxLength={500} />
        </div>
      </div>
      {message && <p className={`text-sm ${message.ok ? "text-leaf-ink" : "text-chilli-ink"}`}>{message.text}</p>}
      <button type="submit" className="btn-primary w-full" disabled={busy || !file || !title.trim() || !publisher.trim()}>
        {busy ? "Reading the document…" : "Add as pending"}
      </button>
    </form>
  );
}

function DocumentList({ token, docs, onChanged }: { token: string; docs: AdminDocument[]; onChanged: () => void }) {
  const { api } = useApp();
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState<string | null>(null);

  const decide = async (doc: AdminDocument, decision: "approve" | "reject") => {
    setError(null);
    try {
      await api.reviewDocument(token, doc.id, decision, reviewer.trim());
      onChanged();
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <section className="card space-y-3" aria-label="Documents">
      <h3 className="text-lg font-semibold">{docs.length} documents</h3>
      <div>
        <label className="label" htmlFor="reviewer">
          Your name (recorded with each approval)
        </label>
        <input id="reviewer" className="input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} maxLength={120} />
      </div>
      {error && <p className="text-sm text-chilli-ink">{error}</p>}
      {docs.length === 0 && <p className="text-sm text-muted">No documents yet. Storage questions are answered only from approved documents.</p>}
      <ul className="divide-y divide-line">
        {docs.map((d) => (
          <li key={d.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
            <div className="min-w-0">
              <p className="break-words font-semibold">{d.title}</p>
              <p className="break-words text-sm text-muted">
                {d.publisher} · {d.crop === "all" ? "all crops" : d.crop} · {d.language} · {d.passages} passages
                {d.reviewed_by ? ` · reviewed by ${d.reviewed_by}` : ""}
              </p>
              <span
                className={`chip mt-1 ${d.status === "approved" ? "bg-leaf-soft text-leaf-ink" : d.status === "rejected" ? "bg-chilli-soft text-chilli-ink" : "bg-turmeric-soft text-turmeric-ink"}`}
              >
                {d.status}
              </span>
            </div>
            <div className="flex shrink-0 gap-2">
              {d.status !== "approved" && (
                <button type="button" className="btn-primary" disabled={!reviewer.trim()} onClick={() => void decide(d, "approve")}>
                  Approve
                </button>
              )}
              {d.status !== "rejected" && (
                <button type="button" className="btn-ghost" disabled={!reviewer.trim()} onClick={() => void decide(d, "reject")}>
                  Reject
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
