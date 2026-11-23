"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, post } from "@/lib/api";
import { ActionForm, date, Empty, JsonPanel, Panel, Remote, SelectField, Status } from "./panels";
import { ProjectCreate } from "./shell";
import { Button } from "./ui/button";

type Endpoint = { id: string; url: string; enabled_events: string[]; enabled: boolean };
type Event = { id: string; event_type: string; created_at: string };
type Delivery = { id: string; event_id: string; endpoint_id: string; status: string; attempt_count: number; next_retry_at: string };
type Scenario = { id: string; name: string; configuration: Record<string, unknown> };
type Run = { id: string; status: string; result: Record<string, unknown> | null; suite_name?: string; created_at: string };
type Suite = { id: string; name: string };
const eventTypes = ["payment.authorized", "payment.captured", "payment.failed", "refund.created", "refund.processed", "refund.failed"];

function EndpointOptions({ endpoints }: { endpoints: Endpoint[] }) {
  return <><option value="">Select a receiver</option>{endpoints.filter((item) => item.enabled).map((item) => <option key={item.id} value={item.id}>{item.url}</option>)}</>;
}

export function Webhooks({ root }: { root: string }) {
  const cache = useQueryClient();
  const [selected, setSelected] = useState("");
  const [delivery, setDelivery] = useState("");
  const [replayId, setReplayId] = useState("");
  return <>
    <div className="two-columns">
      <Panel title="Event history"><Remote<Event[]> path={root + "/webhook-events"} poll={5000}>{(events) => events.length
        ? <ul className="row-list">{events.map((event) => <li key={event.id}><button className="link-button" onClick={() => { setSelected(event.id); setReplayId(""); }}>{event.event_type}</button><span>{date(event.created_at)}</span></li>)}</ul>
        : <Empty>No webhook events recorded.</Empty>}</Remote></Panel>
      <Panel title="Receivers"><Remote<Endpoint[]> path={root + "/webhook-endpoints"}>{(endpoints) => endpoints.length
        ? <ul className="row-list">{endpoints.map((endpoint) => <li key={endpoint.id}><span className="wrap">{endpoint.url}</span><Status value={endpoint.enabled ? "active" : "disabled"} /></li>)}</ul>
        : <Empty>Add a receiver in Settings to start delivering events.</Empty>}</Remote></Panel>
    </div>
    {selected && <Panel title="Event payload"><Remote<unknown> path={root + "/webhook-events/" + selected + "/payload"}>{(payload) => <JsonPanel value={payload} />}</Remote>
      <Remote<Endpoint[]> path={root + "/webhook-endpoints"}>{(endpoints) => <ActionForm label="Replay webhook" execute={async (body) => {
        const run = await post<{ execution_id: string }>(root + "/dashboard/events/" + selected + "/replay", { endpoint_id: body.get("endpoint") });
        setReplayId(run.execution_id);
        await cache.invalidateQueries({ queryKey: [root + "/webhook-deliveries"] });
        return "Replay queued.";
      }}><SelectField label="Replay receiver" name="endpoint" required><EndpointOptions endpoints={endpoints} /></SelectField></ActionForm>}</Remote>
      {replayId && <Remote<Run> path={root + "/webhook-runs/" + replayId} poll={2000}>{(run) => <div className="selection">Replay status <Status value={run.status} /></div>}</Remote>}
    </Panel>}
    <Panel title="Delivery history"><Remote<Delivery[]> path={root + "/webhook-deliveries"} poll={3000}>{(rows) => rows.length ? <ul className="row-list">
      {rows.map((item) => <li key={item.id}><button className="link-button" onClick={() => setDelivery(item.id)}>{item.id.slice(0, 12)}</button><span>{item.attempt_count} attempts</span><Status value={item.status} /></li>)}
    </ul> : <Empty>No deliveries recorded.</Empty>}</Remote>
      {delivery && <Remote<unknown[]> path={root + "/webhook-deliveries/" + delivery + "/attempts"} poll={3000}>{(attempts) => attempts.length ? <JsonPanel value={attempts} /> : <Empty>No attempts yet.</Empty>}</Remote>}
    </Panel>
  </>;
}

export function Chaos({ root }: { root: string }) {
  const cache = useQueryClient();
  const [activeRun, setActiveRun] = useState<{ kind: "payment" | "webhook"; id: string } | null>(null);
  return <>
    <div className="two-columns">
      <Panel title="Payment scenarios"><Remote<string[]> path={root + "/payment-chaos/scenarios"}>{(cases) => <ActionForm label="Run payment scenario" execute={async (body) => {
        const run = await post<Run>(root + "/payment-chaos/runs", { type: body.get("type"), requests: Number(body.get("requests")) });
        setActiveRun({ kind: "payment", id: run.id });
        await cache.invalidateQueries({ queryKey: [root + "/dashboard/overview"] });
        return "Scenario started.";
      }}>
        <SelectField label="Payment scenario" name="type" required>{cases.map((item) => <option key={item}>{item}</option>)}</SelectField>
        <label>Fault request budget<input type="number" min={1} max={10} name="requests" defaultValue={1} required /></label>
      </ActionForm>}</Remote></Panel>
      <Panel title="Create webhook scenario"><ActionForm label="Save scenario" execute={async (body) => {
        await post(root + "/webhook-scenarios", {
          name: body.get("name"), config: { duplicate_count: Number(body.get("duplicates")), delay_ms: Number(body.get("delay")), failure_mode: body.get("fault"), reorder_events: body.get("reorder") === "on" },
        });
        await cache.invalidateQueries({ queryKey: [root + "/webhook-scenarios"] });
        return "Scenario saved.";
      }}>
        <label>Scenario name<input name="name" required maxLength={120} /></label>
        <div className="input-row"><label>Copies<input name="duplicates" type="number" min={1} max={32} defaultValue={2} required /></label>
        <label>Delay (ms)<input name="delay" type="number" min={0} max={60000} defaultValue={0} required /></label></div>
        <SelectField label="Delivery fault" name="fault">{["none", "http_500", "http_429", "timeout", "reset", "unavailable", "invalid_signature", "worker_interruption"].map((item) => <option key={item}>{item}</option>)}</SelectField>
        <label className="checkbox"><input name="reorder" type="checkbox" /> Reverse selected events</label>
      </ActionForm></Panel>
    </div>
    <Panel title="Run webhook scenario">
      <Remote<Scenario[]> path={root + "/webhook-scenarios"}>{(scenarios) => <Remote<Endpoint[]> path={root + "/webhook-endpoints"}>{(endpoints) => <Remote<Event[]> path={root + "/webhook-events"}>{(events) =>
        <ActionForm label="Run webhook scenario" execute={async (body) => {
          const run = await post<Run>(root + "/webhook-scenarios/" + body.get("scenario") + "/runs", { endpoint_id: body.get("endpoint"), event_ids: body.getAll("events") });
          setActiveRun({ kind: "webhook", id: run.id });
          return "Webhook scenario queued.";
        }}>
          <div className="input-row"><SelectField label="Webhook scenario" name="scenario" required><option value="">Select scenario</option>{scenarios.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</SelectField>
          <SelectField label="Receiver" name="endpoint" required><EndpointOptions endpoints={endpoints} /></SelectField></div>
          <label>Events<select name="events" multiple required>{events.map((item) => <option value={item.id} key={item.id}>{item.event_type} · {date(item.created_at)}</option>)}</select></label>
        </ActionForm>}</Remote>}</Remote>}</Remote>
    </Panel>
    {activeRun && <Panel title="Scenario execution"><Remote<Run> path={root + (activeRun.kind === "payment" ? "/payment-chaos/runs/" : "/webhook-runs/") + activeRun.id} poll={2000}>{(run) => <>
      <div className="selection"><Status value={run.status} /></div><JsonPanel value={run.result} />
      {activeRun.kind === "payment" && run.status === "running" && <ActionForm label="Cancel fault" execute={async () => {
        await post(root + "/payment-chaos/runs/" + run.id + "/cancel");
        return "Fault canceled.";
      }}><span /></ActionForm>}
      {activeRun.kind === "webhook" && <Remote<unknown[]> path={root + "/webhook-runs/" + run.id + "/deliveries"} poll={2000}>{(deliveries) => <JsonPanel value={deliveries} />}</Remote>}
    </>}</Remote></Panel>}
  </>;
}

export function Tests({ root, initialRun }: { root: string; initialRun?: string }) {
  const cache = useQueryClient();
  const [selected, setSelected] = useState(initialRun ?? "");
  return <>
    <div className="two-columns">
      <Panel title="Create test suite"><ActionForm label="Save test suite" execute={async (body) => {
        await post(root + "/test-suites", { yaml: body.get("definition") });
        await cache.invalidateQueries({ queryKey: [root + "/test-suites"] });
        return "Test suite saved.";
      }}><label>YAML definition<textarea name="definition" rows={9} maxLength={65536} placeholder="name: smoke" required /></label></ActionForm></Panel>
      <Panel title="Test suites"><Remote<Suite[]> path={root + "/test-suites"}>{(suites) => suites.length ? <ActionForm label="Run test suite" execute={async (body) => {
        const run = await post<Run>(root + "/test-suites/" + body.get("suite") + "/runs");
        setSelected(run.id);
        return "Run queued.";
      }}><SelectField label="Suite to run" name="suite" required>{suites.map((suite) => <option value={suite.id} key={suite.id}>{suite.name}</option>)}</SelectField></ActionForm> : <Empty>Save a suite to run it.</Empty>}</Remote></Panel>
    </div>
    <RunList root={root} select={setSelected} />
    {selected && <Panel title="Run results"><Remote<Run> path={root + "/test-runs/" + selected} poll={2000}>{(run) => <>
      <div className="selection"><Status value={run.status} /><span>{run.suite_name}</span></div>
      {run.result ? <JsonPanel value={run.result} /> : <Empty>Waiting for recorded assertions.</Empty>}
    </>}</Remote></Panel>}
  </>;
}

function RunList({ root, select }: { root: string; select: (id: string) => void }) {
  return <Panel title="Run history"><Remote<Run[]> path={root + "/test-runs"} poll={3000}>{(runs) => runs.length
    ? <ul className="row-list">{runs.map((run) => <li key={run.id}><button className="link-button" onClick={() => select(run.id)}>{run.suite_name}</button><span>{date(run.created_at)}</span><Status value={run.status} /></li>)}</ul>
    : <Empty>No test runs recorded.</Empty>}</Remote></Panel>;
}

type Report = { suite_name: string; status: string; summary: { total: number; passed: number; failed: number; error: number; inconclusive: number }; cases: unknown[] };

export function Reports({ root }: { root: string }) {
  const [selected, setSelected] = useState("");
  const report = root + "/test-runs/" + selected + "/report";
  return <><RunList root={root} select={setSelected} />
    {selected && <Panel title="Reliability report"><Remote<Report> path={report + "/json"} poll={3000}>{(data) => <>
      <div className="selection"><strong>{data.suite_name}</strong><Status value={data.status} /></div>
      <div className="selection"><span>{data.summary.passed} passed</span><span>{data.summary.failed} failed</span><span>{data.summary.inconclusive} inconclusive</span><span>{data.summary.error} errors</span></div>
      <div className="selection"><Button asChild variant="outline"><a href={"/api/backend/" + report + "/json"} download>Export JSON</a></Button><Button asChild variant="outline"><a href={"/api/backend/" + report + "/html"} download>Export HTML</a></Button></div>
      {data.cases.length ? <JsonPanel value={data.cases} /> : <Empty>No report case data yet.</Empty>}
    </>}</Remote></Panel>}
  </>;
}

type Credential = { id: string; key_id: string; label: string; enabled: boolean; secret?: string };

export function SettingsPanel({ root }: { root: string }) {
  const cache = useQueryClient();
  const [issued, setIssued] = useState<Credential | null>(null);
  const [failure, setFailure] = useState("");
  const [activeCredential, setActiveCredential] = useState("");
  const credentialsPath = root + "/credentials";
  async function updateCredential(id: string, rotate: boolean) {
    setFailure("");
    setActiveCredential(id);
    try {
      if (rotate) setIssued(await post<Credential>(credentialsPath + "/" + id + "/rotate"));
      else await api(credentialsPath + "/" + id, { method: "DELETE" });
      await cache.invalidateQueries({ queryKey: [credentialsPath] });
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setActiveCredential("");
    }
  }

  return <>
    <div className="two-columns">
      <Panel title="Environment health"><Remote<{ status: string; dependencies: Record<string, string> }> path="ready" poll={5000}>{(readiness) => <div className="selection"><Status value={readiness.status} />{Object.entries(readiness.dependencies).map(([key, value]) => <span key={key}>{key} · {value}</span>)}</div>}</Remote></Panel>
      <ProjectCreate />
    </div>
    <Panel title="Local API credentials"><ActionForm label="Issue test credential" execute={async (body) => {
      setIssued(await post<Credential>(credentialsPath, { label: body.get("label") }));
      await cache.invalidateQueries({ queryKey: [credentialsPath] });
      return "Credential issued.";
    }}><label>Credential label<input name="label" required maxLength={120} /></label></ActionForm>
      {issued && <div className="selection issued"><div><strong>Save this credential now</strong><JsonPanel value={{ key_id: issued.key_id, secret: issued.secret }} /></div><Button variant="outline" onClick={() => setIssued(null)}>Dismiss</Button></div>}
      {failure && <p className="form-error" role="alert">{failure}</p>}
      <Remote<Credential[]> path={credentialsPath}>{(items) => items.length ? <ul className="row-list">
        {items.map((item) => <li key={item.id}><div><strong>{item.label}</strong><br /><code>{item.key_id}</code></div><Status value={item.enabled ? "active" : "revoked"} />
          {item.enabled && <div className="selection"><Button variant="outline" disabled={!!activeCredential} onClick={() => updateCredential(item.id, true)}>Rotate</Button><Button variant="ghost" disabled={!!activeCredential} onClick={() => updateCredential(item.id, false)}>Revoke</Button></div>}</li>)}
      </ul> : <Empty>No test credentials issued.</Empty>}</Remote>
    </Panel>
    <Panel title="Register webhook receiver"><ActionForm label="Register receiver" execute={async (body) => {
      await post(root + "/webhook-endpoints", { url: body.get("url"), secret: body.get("secret"), enabled_events: body.getAll("events") });
      await cache.invalidateQueries({ queryKey: [root + "/webhook-endpoints"] });
      return "Receiver registered.";
    }}>
      <div className="input-row"><label>Receiver URL<input name="url" type="url" required /></label><label>Webhook secret<input name="secret" type="password" minLength={16} maxLength={128} required /></label></div>
      <label>Event subscriptions<select name="events" multiple required>{eventTypes.map((item) => <option key={item}>{item}</option>)}</select></label>
    </ActionForm></Panel>
  </>;
}
