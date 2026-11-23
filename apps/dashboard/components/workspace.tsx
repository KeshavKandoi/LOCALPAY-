"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "./ui/button";
import { importPortable } from "@/lib/workspace-import";
import { assertResponse, curl, defaultDraft, execute, formats, methods, prepare, prepareExternal, type Draft, type Result } from "@/lib/workspace";

type Saved = { id: string; name: string; collection: string; draft: Draft };
type History = { id: string; at: string; status: number; ms: number; method: Draft["method"]; savedId: string | null };
type CollectionSettings = { variables: string; useSessionCredential: boolean };
type Data = { collections?: Record<string, CollectionSettings>; requests: Saved[]; history: History[]; environments: Record<string, string> };
const empty: Data = { requests: [], history: [], environments: { Local: "", Development: "", Staging: "" } };
const runbook: [string, Partial<Draft>][] = [
  ["List orders", {}],
  ["Create order", { method: "POST", format: "json", body: '{\n  "amount": 50000,\n  "currency": "INR",\n  "receipt": "localpay-demo"\n}' }],
  ["Simulate payment", { method: "POST", url: "{{base_url}}/localpay/v1/simulations/payments", format: "json", body: '{\n  "order_id": "{{order_id}}"\n}', checks: "status = 201" }],
  ["Capture payment", { method: "POST", url: "{{base_url}}/v1/payments/{{payment_id}}/capture", format: "json", body: '{\n  "amount": 50000,\n  "currency": "INR"\n}' }],
  ["Refund payment", { method: "POST", url: "{{base_url}}/v1/payments/{{payment_id}}/refund", format: "json", body: '{\n  "amount": 10000\n}' }],
  ["Gateway health", { url: "{{base_url}}/health", authenticated: false }],
];

function readData(key: string): Data {
  if (typeof window === "undefined") return empty;
  try { return JSON.parse(localStorage.getItem(key) ?? "null") ?? empty; }
  catch { return empty; }
}

function exportFile(name: string, data: Blob) {
  const url = URL.createObjectURL(data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function importRequests(source: unknown): Saved[] {
  if (!source || typeof source !== "object" || !("version" in source) || source.version !== 1 ||
      !("requests" in source) || !Array.isArray(source.requests) || source.requests.length > 100) {
    throw new Error("Choose a LocalPay workspace export with up to 100 requests.");
  }
  return source.requests.map((entry: unknown) => {
    if (!entry || typeof entry !== "object" || !("name" in entry) || !("collection" in entry) || !("draft" in entry) ||
        typeof entry.name !== "string" || typeof entry.collection !== "string" ||
        !entry.draft || typeof entry.draft !== "object") throw new Error("Invalid saved request.");
    const candidate = entry.draft as Partial<Draft>;
    if (!methods.some((method) => method === candidate.method) || !Object.hasOwn(formats, candidate.format ?? "") ||
        typeof candidate.authenticated !== "boolean" ||
        ![candidate.url, candidate.query, candidate.headers, candidate.body, candidate.checks].every((value) => typeof value === "string")) {
      throw new Error("Invalid request fields.");
    }
    const { method, url, query, headers, format, body, checks, authenticated } = candidate as Draft;
    return { id: crypto.randomUUID(), name: entry.name, collection: entry.collection, draft: { method, url, query, headers, format, body, checks, authenticated } };
  });
}

export function Workspace({ project }: { project: string }) {
  const storage = "localpay.workspace.v1." + project;
  const [data, setData] = useState(() => readData(storage));
  const [draft, setDraft] = useState(defaultDraft);
  const [active, setActive] = useState<string | null>(null);
  const [name, setName] = useState("List orders");
  const [collection, setCollection] = useState("Payment API");
  const [environment, setEnvironment] = useState("Local");
  const [customEnvironment, setCustomEnvironment] = useState("");
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [external, setExternal] = useState(false);
  const [keyId, setKeyId] = useState("");
  const [secret, setSecret] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Result>();
  const [responseView, setResponseView] = useState("pretty");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [historyMethod, setHistoryMethod] = useState("");
  const [historyStatus, setHistoryStatus] = useState("");
  const [historySearch, setHistorySearch] = useState("");
  const [folder, setFolder] = useState("");
  const [folderName, setFolderName] = useState("");
  const [collectionKeys, setCollectionKeys] = useState<Record<string, string>>({});
  const [editor, setEditor] = useState<"request" | "environment" | "saved" | "history">("request");
  const current = useRef<AbortController | null>(null);

  useEffect(() => () => current.current?.abort(), []);

  function change<K extends keyof Draft>(field: K, value: Draft[K]) {
    setDraft((previous) => ({ ...previous, [field]: value }));
  }

  function persist(next: Data) {
    try {
      localStorage.setItem(storage, JSON.stringify(next));
      setData(next);
    } catch {
      setError("Could not save workspace data in this browser.");
    }
  }

  function select(saved: Saved) {
    setExternal(false);
    setActive(saved.id);
    setName(saved.name);
    setCollection(saved.collection);
    setDraft(saved.draft);
    setFile(null);
    setEditor("request");
  }

  function save(duplicate = false) {
    if (external) { setError("External requests are session-only."); return; }
    if (!name.trim() || !collection.trim()) {
      setError("Enter a request name and collection.");
      return;
    }
    if (file || /^(?:authorization|cookie|proxy-authorization):/im.test(draft.headers)) {
      setError("Remove the attached file and credential headers before saving a request.");
      return;
    }
    const id = !duplicate && active ? active : crypto.randomUUID();
    const saved = { id, name: name.trim() + (duplicate ? " copy" : ""), collection: collection.trim(), draft };
    const requests = data.requests.some((entry) => entry.id === id)
      ? data.requests.map((entry) => entry.id === id ? saved : entry) : [...data.requests, saved];
    persist({ ...data, requests });
    select(saved);
  }

  async function send(request = draft, savedId = active, collectionPath = collection, attachment = file, direct = external) {
    if (current.current) return;
    setError("");
    setNotice("");
    setResult(undefined);
    const controller = new AbortController();
    current.current = controller;
    setBusy(true);
    try {
      const collectionName = collectionPath.split("/")[0];
      const defaults = data.collections?.[collectionName];
      const credential = defaults?.useSessionCredential ? collectionKeys[collectionName] ?? "" : "";
      const separator = credential.indexOf(":");
      const inheritedKey = separator < 0 ? "" : credential.slice(0, separator);
      const inheritedSecret = separator < 0 ? "" : credential.slice(separator + 1);
      const variables = [defaults?.variables, data.environments[environment]].filter(Boolean).join("\n");
      const prepared = direct ? prepareExternal(request) : prepare(request, project, variables, secrets[environment] ?? "", keyId || inheritedKey, keyId ? secret : inheritedSecret, attachment);
      const response = await execute(prepared, controller.signal);
      setResult(response);
      setData((previous) => {
        const entry = { id: crypto.randomUUID(), at: new Date().toISOString(), method: request.method, status: response.status, ms: response.ms, savedId: direct ? null : savedId };
        const next = { ...previous, history: [entry, ...previous.history].slice(0, 100) };
        return next;
      });
    } catch (cause) {
      setError(controller.signal.aborted ? "Request cancelled." : cause instanceof Error ? cause.message : "Request failed.");
    } finally {
      current.current = null;
      setBusy(false);
    }
  }

  const latestHistory = data.history[0]?.id;
  useEffect(() => {
    if (!latestHistory) return;
    try {
      const stored = readData(storage);
      if (stored.history[0]?.id !== latestHistory) localStorage.setItem(storage, JSON.stringify({ ...stored, history: data.history }));
    } catch {}
  }, [data.history, latestHistory, storage]);

  async function copy(value: () => string) {
    try {
      await navigator.clipboard.writeText(value());
      setNotice("Copied to clipboard.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Clipboard unavailable."); }
  }

  const rendered = result && responseView === "headers" ? JSON.stringify(result.headers, null, 2)
    : result && responseView === "pretty" && result.json !== undefined ? JSON.stringify(result.json, null, 2) : result?.raw;
  const tabLabels = { request: "Request", environment: "Environment", saved: "Collections", history: "History" };

  const folderRoot = folder.split("/")[0];
  const folders = [...new Set(data.requests.flatMap((entry) => entry.collection.split("/").map((_, index, path) => path.slice(0, index + 1).join("/"))))].sort();
  const settings = data.collections?.[folderRoot] ?? { variables: "", useSessionCredential: false };
  function setCollectionSettings(next: CollectionSettings) {
    persist({ ...data, collections: { ...data.collections, [folderRoot]: next } });
  }

  return <div className="workspace-editor" onKeyDown={(event) => {
    if (!(event.metaKey || event.ctrlKey) || event.repeat || editor !== "request") return;
    if (event.key === "Enter") { event.preventDefault(); void send(); }
    if (event.key.toLowerCase() === "s") { event.preventDefault(); save(); }
  }}>
    <section className="panel form-panel" aria-label="Request designer">
      <div className="workspace-actions">{(Object.keys(tabLabels) as Array<keyof typeof tabLabels>).map((tab) => <Button key={tab} variant={editor === tab ? "solid" : "outline"} aria-pressed={editor === tab} onClick={() => setEditor(tab)}>{tabLabels[tab]}</Button>)}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p className="form-success" role="status">{notice}</p>}
      {editor === "request" && <>
        <label className="checkbox"><input type="checkbox" checked={external} onChange={(event) => setExternal(event.target.checked)} /> External HTTPS request</label>
        {external && <p>Browser GET and HEAD requests require CORS support. Credentials, custom headers, and workspace variables stay local.</p>}
        <label>Payment request templates<select value="" onChange={(event) => {
          const template = runbook[Number(event.target.value)];
          if (!event.target.value || !template) return;
          setExternal(false);
          setDraft({ ...defaultDraft, ...template[1] });
          setName(template[0]);
          setActive(null);
          setFile(null);
        }}><option value="">Choose a template</option>{runbook.map(([label], index) => <option key={label} value={index}>{label}</option>)}</select></label>
        <div className="workspace-request-line">
          <label>Method<select value={draft.method} onChange={(event) => change("method", event.target.value as Draft["method"])}>{methods.map((method) => <option key={method}>{method}</option>)}</select></label>
          <label>Request URL<input value={draft.url} onChange={(event) => change("url", event.target.value)} /></label>
        </div>
        <div className="workspace-actions">
          <Button disabled={busy} onClick={() => send()}>{busy ? "Sending…" : "Send request"}</Button>
          <Button variant="outline" disabled={!busy} onClick={() => current.current?.abort()}>Cancel</Button>
          <Button variant="outline" disabled={external} onClick={() => copy(() => curl(draft))}>Copy as cURL</Button>
        </div>
        <div className="input-row">
          <label>Query parameters<textarea rows={2} placeholder="count=10" value={draft.query} onChange={(event) => change("query", event.target.value)} /></label>
          <label>Headers<textarea disabled={external} rows={2} placeholder="Accept: application/json" value={draft.headers} onChange={(event) => change("headers", event.target.value)} /></label>
        </div>
        <label>Authentication<select disabled={external} value={draft.authenticated ? "basic" : "none"} onChange={(event) => change("authenticated", event.target.value === "basic")}><option value="basic">LocalPay project credentials (Basic)</option><option value="none">None</option></select></label>
        {!external && draft.authenticated && <div className="input-row">
          <label>Key ID<input autoComplete="off" value={keyId} onChange={(event) => setKeyId(event.target.value)} /></label>
          <label>Key secret<input type="password" autoComplete="off" value={secret} onChange={(event) => setSecret(event.target.value)} /></label>
        </div>}
        {!["GET", "HEAD", "OPTIONS"].includes(draft.method) && <>
          <label>Body format<select value={draft.format} onChange={(event) => change("format", event.target.value as Draft["format"])}>{Object.keys(formats).map((format) => <option key={format}>{format}</option>)}</select></label>
          {draft.format !== "none" && !file && <label>Request body<textarea className="workspace-code" rows={6} spellCheck={false} value={draft.body} onChange={(event) => change("body", event.target.value)} /></label>}
          {draft.format === "json" && !file && <Button variant="outline" onClick={() => {
            try { change("body", JSON.stringify(JSON.parse(draft.body), null, 2)); setError(""); }
            catch { setError("Enter valid JSON before formatting."); }
          }}>Format JSON</Button>}
          <label>Binary attachment<input type="file" key={active ?? name} onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
        </>}
        <label>Response assertions<textarea className="workspace-code" rows={3} spellCheck={false} placeholder={"status = 200\njson.id exists\ntime < 1000"} value={draft.checks} onChange={(event) => change("checks", event.target.value)} /></label>
        <div className="input-row">
          <label>Request name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>Collection or folder path<input value={collection} onChange={(event) => setCollection(event.target.value)} /></label>
        </div>
        <div className="workspace-actions">
          <Button variant="outline" onClick={() => save()}>Save request</Button>
          {active && <><Button variant="outline" onClick={() => save(true)}>Duplicate</Button><Button variant="outline" onClick={() => {
            persist({ ...data, requests: data.requests.filter((entry) => entry.id !== active) });
            setActive(null);
          }}>Delete saved request</Button></>}
        </div>
      </>}
      {editor === "environment" && <>
        <label>Active environment<select value={environment} onChange={(event) => setEnvironment(event.target.value)}>{Object.keys(data.environments).map((label) => <option key={label}>{label}</option>)}</select></label>
        <label>Variables <span>Saved in this browser. Add one name=value pair per line.</span><textarea rows={5} value={data.environments[environment] ?? ""} onChange={(event) => persist({ ...data, environments: { ...data.environments, [environment]: event.target.value } })} placeholder="order_id=order_example" /></label>
        <label>Session secret variable <span>One name=value pair. Kept in memory while this workspace is open.</span><input type="password" autoComplete="off" value={secrets[environment] ?? ""} onChange={(event) => setSecrets({ ...secrets, [environment]: event.target.value })} /></label>
        <label>New environment name<input value={customEnvironment} onChange={(event) => setCustomEnvironment(event.target.value)} /></label>
        <Button variant="outline" disabled={!customEnvironment.trim() || Object.hasOwn(data.environments, customEnvironment.trim())} onClick={() => {
          const label = customEnvironment.trim();
          persist({ ...data, environments: { ...data.environments, [label]: "" } });
          setEnvironment(label);
          setCustomEnvironment("");
        }}>Add environment</Button>
      </>}
      {editor === "saved" && <>
        <label>Collection or folder<select value={folder} onChange={(event) => { setFolder(event.target.value); setFolderName(""); }}><option value="">All requests</option>{folders.map((path) => <option key={path}>{path}</option>)}</select></label>
        {folder && <>
          <label>Move or rename folder<input value={folderName} onChange={(event) => setFolderName(event.target.value)} placeholder={folder} /></label>
          <Button variant="outline" disabled={!folderName.trim() || folders.includes(folderName.trim()) || folderName.trim().startsWith(folder + "/")} onClick={() => {
            const next = folderName.trim();
            const inFolder = (path: string) => path === folder || path.startsWith(folder + "/");
            const requests = data.requests.map((entry) => inFolder(entry.collection) ? { ...entry, collection: next + entry.collection.slice(folder.length) } : entry);
            const { [folder]: moved, ...remaining } = data.collections ?? {};
            persist({ ...data, requests, collections: moved && !next.includes("/") ? { ...remaining, [next]: moved } : data.collections });
            if (inFolder(collection)) setCollection(next + collection.slice(folder.length));
            setCollectionKeys({});
            setFolder(next);
            setFolderName("");
          }}>Move matching requests</Button>
          <label>Collection variables<textarea rows={3} value={settings.variables} placeholder="name=value" onChange={(event) => setCollectionSettings({ ...settings, variables: event.target.value })} /></label>
          <label className="checkbox"><input type="checkbox" checked={settings.useSessionCredential} onChange={(event) => setCollectionSettings({ ...settings, useSessionCredential: event.target.checked })} /> Inherit collection Basic credentials</label>
          {settings.useSessionCredential && <label>Collection credential (key:secret)<input type="password" autoComplete="off" value={collectionKeys[folderRoot] ?? ""} onChange={(event) => setCollectionKeys({ ...collectionKeys, [folderRoot]: event.target.value })} /></label>}
        </>}
        <label>Search saved requests<input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <ul className="row-list">{data.requests.filter((entry) => (!folder || entry.collection === folder || entry.collection.startsWith(folder + "/")) && (entry.collection + "/" + entry.name).toLowerCase().includes(search.toLowerCase())).map((entry) => <li key={entry.id}><Button variant="ghost" onClick={() => select(entry)}>{entry.collection} / {entry.name}</Button><span>{entry.draft.method}</span></li>)}</ul>
        {!data.requests.length && <p>No saved requests.</p>}
        <Button variant="outline" disabled={!data.requests.length} onClick={() => exportFile("localpay-workspace.json", new Blob([JSON.stringify({ version: 1, requests: data.requests }, null, 2)], { type: "application/json" }))}>Export requests</Button>
        <label>Import requests<input type="file" accept=".json,.curl,.txt,application/json,text/plain" onChange={async (event) => {
          const target = event.currentTarget;
          const file = target.files?.[0];
          target.value = "";
          if (!file) return;
          try {
            if (file.size > 524288) throw new Error("Import must be smaller than 512 KiB.");
            const source = await file.text();
            const portable = importPortable(source);
            const requests = portable ? portable.map((entry) => ({ ...entry, id: crypto.randomUUID() })) : importRequests(JSON.parse(source));
            persist({ ...data, requests: [...data.requests, ...requests] });
          } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not import requests."); }
        }} /></label>
      </>}
      {editor === "history" && <>
        <label>Filter history by method<select value={historyMethod} onChange={(event) => setHistoryMethod(event.target.value)}><option value="">All methods</option>{methods.map((method) => <option key={method}>{method}</option>)}</select></label>
        <label>Filter history by status<select value={historyStatus} onChange={(event) => setHistoryStatus(event.target.value)}><option value="">All status codes</option>{[2, 3, 4, 5].map((status) => <option key={status} value={status}>{status}xx</option>)}</select></label>
        <label>Search history<input value={historySearch} onChange={(event) => setHistorySearch(event.target.value)} placeholder="Request name or status" /></label>
        <ul className="row-list">{data.history.filter((entry) => {
          const saved = data.requests.find((request) => request.id === entry.savedId);
          return (!historyMethod || entry.method === historyMethod) && (!historyStatus || Math.floor(entry.status / 100) === Number(historyStatus)) &&
            (entry.method + " " + entry.status + " " + (saved?.name ?? "")).toLowerCase().includes(historySearch.toLowerCase());
        }).map((entry) => {
          const saved = data.requests.find((request) => request.id === entry.savedId);
          return <li key={entry.id}><span>{entry.method} · HTTP {entry.status} · {entry.ms} ms</span><time dateTime={entry.at}>{new Date(entry.at).toLocaleString()}</time>{saved && <><Button variant="ghost" onClick={() => select(saved)}>Open saved request</Button><Button variant="outline" disabled={busy} onClick={() => {
            select(saved);
            void send(saved.draft, saved.id, saved.collection, null, false);
          }}>Replay saved request</Button></>}</li>;
        })}</ul>
        {!data.history.length && <p>No requests sent.</p>}
        <Button variant="outline" disabled={!data.history.length} onClick={() => persist({ ...data, history: [] })}>Clear history</Button>
      </>}
    </section>
    <section className="panel workspace-response" aria-label="Response viewer">
      <div className="panel-heading"><h2>Response</h2>{result && <p role="status">HTTP {result.status} · {result.ms} ms · {result.size} bytes</p>}</div>
      {result ? <>
        <div className="selection workspace-actions">
          {["pretty", "raw", "headers"].map((view) => <Button key={view} aria-pressed={responseView === view} variant={responseView === view ? "solid" : "outline"} onClick={() => setResponseView(view)}>{view[0].toUpperCase() + view.slice(1)}</Button>)}
          <Button variant="outline" onClick={() => copy(() => rendered ?? "")}>Copy response</Button>
          <Button variant="outline" onClick={() => exportFile("localpay-response", new Blob([result.bytes], { type: "application/octet-stream" }))}>Download</Button>
        </div>
        <pre className="payload">{rendered || "Empty response body"}</pre>
        <ul className="row-list">{assertResponse(result, draft.checks).map(({ line, passed }, index) => <li key={index}><code>{line}</code><strong className={passed ? "form-success" : "form-error"}>{passed ? "Passed" : "Failed"}</strong></li>)}</ul>
      </> : <p className="empty">{busy ? "Waiting for LocalPay…" : "Send a request to inspect the response."}</p>}
    </section>
  </div>;
}
