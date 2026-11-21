import { LANGUAGES } from "@mandi/i18n";
import { ApiError, type AdminDocument } from "@mandi/shared";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useApp } from "../lib/app-context";

/** Staff-only page (English): sign in with the server's ADMIN_TOKEN, manage the documents the agent answers from. */

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
    /* storage blocked: the token just isn't remembered */
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
  const [docs, setDocs] = useState<AdminDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (t: string) => {
      setBusy(true);
      setError(null);
      try {
        setDocs(await api.adminDocuments(t));
        setToken(t);
        saveToken(t);
      } catch (e) {
        setDocs(null);
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

  if (!token || !docs) {
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
        <h2 className="text-2xl font-bold tracking-tight">Documents</h2>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => {
            saveToken(null);
            setToken("");
            setDocs(null);
            setInput("");
          }}
        >
          Sign out
        </button>
      </div>
      <p className="text-sm text-muted">
        The assistant answers storage, handling and other questions from these documents. A new upload is used from the next question on.{" "}
        <Link to="/" className="font-semibold text-leaf underline">
          Try a question
        </Link>
      </p>
      <UploadForm token={token} onUploaded={(d) => setDocs((cur) => [...(cur ?? []), d].sort((a, b) => a.filename.localeCompare(b.filename)))} />
      <DocumentList token={token} docs={docs} onDeleted={(id) => setDocs((cur) => (cur ?? []).filter((d) => d.id !== id))} />
    </div>
  );
}

function UploadForm({ token, onUploaded }: { token: string; onUploaded: (d: AdminDocument) => void }) {
  const { api, meta } = useApp();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [crop, setCrop] = useState("all");
  const [language, setLanguage] = useState("en");
  const [source, setSource] = useState("");
  const [published, setPublished] = useState("");
  const [state, setState] = useState("all");
  const [url, setUrl] = useState("");
  const [helpline, setHelpline] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [inputKey, setInputKey] = useState(0);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setMessage(null);
    try {
      const doc = await api.uploadDocument(token, { file, filename: file.name, title, crop, language, source, published, state, url, helpline });
      onUploaded(doc);
      setMessage({ ok: true, text: `Added “${doc.title}” (${doc.chunks} passages). The assistant can answer from it now.` });
      setFile(null);
      setTitle("");
      setSource("");
      setPublished("");
      setUrl("");
      setHelpline("");
      setInputKey((k) => k + 1);
    } catch (err) {
      setMessage({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card space-y-3">
      <h3 className="eyebrow">Upload a document</h3>
      <div>
        <label className="label" htmlFor="doc-file">
          File (PDF, Markdown or text, up to 10 MB)
        </label>
        <input
          key={inputKey}
          id="doc-file"
          className="input py-2"
          type="file"
          accept=".pdf,.md,.txt,application/pdf,text/plain,text/markdown"
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            setFile(f);
            if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " "));
          }}
        />
      </div>
      <div>
        <label className="label" htmlFor="doc-title">
          Title
        </label>
        <input id="doc-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label" htmlFor="doc-crop">
            Crop
          </label>
          <select id="doc-crop" className="input" value={crop} onChange={(e) => setCrop(e.target.value)}>
            <option value="all">All crops / general</option>
            {meta?.crops.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="doc-lang">
            Language of the file
          </label>
          <select id="doc-lang" className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label" htmlFor="doc-source">
            Source
          </label>
          <input id="doc-source" className="input" placeholder="e.g. KVK Nashik" value={source} onChange={(e) => setSource(e.target.value)} maxLength={200} />
        </div>
        <div>
          <label className="label" htmlFor="doc-date">
            Published
          </label>
          <input id="doc-date" className="input" type="date" value={published} onChange={(e) => setPublished(e.target.value)} />
        </div>
      </div>
      <div>
        <label className="label" htmlFor="doc-state">
          Applies to
        </label>
        <select id="doc-state" className="input" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="all">All of India (central scheme or general advice)</option>
          {meta?.states?.map((st) => (
            <option key={st} value={st}>
              {st} only
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-muted">Farmers in other states never get answers from a state-only document.</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label" htmlFor="doc-url">
            Official link (optional)
          </label>
          <input id="doc-url" className="input" type="url" placeholder="https://pmkisan.gov.in" value={url} onChange={(e) => setUrl(e.target.value)} maxLength={200} />
        </div>
        <div>
          <label className="label" htmlFor="doc-helpline">
            Helpline (optional)
          </label>
          <input id="doc-helpline" className="input" inputMode="tel" placeholder="155261" value={helpline} onChange={(e) => setHelpline(e.target.value)} maxLength={60} />
        </div>
      </div>
      {message && <p className={`text-sm ${message.ok ? "text-leaf" : "text-chilli-ink"}`}>{message.text}</p>}
      <button type="submit" className="btn-primary w-full" disabled={busy || !file}>
        {busy ? "Uploading and indexing…" : "Upload"}
      </button>
    </form>
  );
}

function DocumentList({ token, docs, onDeleted }: { token: string; docs: AdminDocument[]; onDeleted: (id: string) => void }) {
  const { api } = useApp();
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const remove = async (d: AdminDocument) => {
    if (!window.confirm(`Delete “${d.title}”? The assistant will stop using it.`)) return;
    setDeleting(d.id);
    setError(null);
    try {
      await api.deleteDocument(token, d.id);
      onDeleted(d.id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setDeleting(null);
    }
  };

  return (
    <section className="card space-y-3">
      <h3 className="eyebrow">{docs.length} documents</h3>
      {error && <p className="text-sm text-chilli-ink">{error}</p>}
      <ul className="divide-y divide-line">
        {docs.map((d) => (
          <li key={d.id} className="flex items-start justify-between gap-3 py-3">
            <div className="min-w-0">
              <p className="font-semibold break-words">{d.title}</p>
              <p className="text-sm text-muted break-words">
                {d.crop === "all" ? "All crops" : d.crop} · {d.language} · {d.format.toUpperCase()} · {d.chunks} passages
                {d.source ? ` · ${d.source}` : ""}
                {d.state && d.state !== "all" ? ` · ${d.state} only` : ""}
                {d.helpline ? ` · ☎ ${d.helpline}` : ""}
              </p>
              {!d.deletable && <span className="chip mt-1 bg-sunken text-muted">Built-in</span>}
            </div>
            {d.deletable && (
              <button type="button" className="btn-ghost shrink-0" disabled={deleting === d.id} onClick={() => void remove(d)}>
                {deleting === d.id ? "Deleting…" : "Delete"}
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
