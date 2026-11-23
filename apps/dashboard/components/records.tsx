"use client";

import { Activity, CircleAlert, DollarSign, Radio } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "./ui/button";
import { date, Empty, JsonPanel, minorAmount, Panel, Remote, Status } from "./panels";

type OverviewData = {
  payments: number; failed: number; captured: number; deliveries: number; delivered: number;
  volume: { currency: string; amount: string }[];
  activity: { date: string; count: number }[];
  recent_failures: { id: string; reason: string | null }[];
  recent_runs: { id: string; name: string; status: string }[];
};

function rate(numerator: number, denominator: number) {
  return denominator ? new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(numerator / denominator) : "—";
}

export function Overview({ root }: { root: string }) {
  return <Remote<OverviewData> path={root + "/dashboard/overview"}>{(data) => <>
    <div className="overview-banner"><div><h2>Simulation activity</h2><p>Payment and webhook activity for this project.</p></div><Button asChild><Link href="/tests">Open test runner</Link></Button></div>
    <div className="metrics">
      <div className="metric panel"><span><Activity size={17} /> Total payments</span><strong>{data.payments}</strong><small>{rate(data.captured, data.payments)} captured</small></div>
      <div className="metric panel"><span><DollarSign size={17} /> Captured volume</span><strong>{data.volume.length ? minorAmount(data.volume[0].amount, data.volume[0].currency) : "—"}</strong><small>{data.volume.slice(1).map((item) => minorAmount(item.amount, item.currency)).join(" · ") || "Simulated transactions"}</small></div>
      <div className="metric panel"><span><CircleAlert size={17} /> Failed payments</span><strong>{data.failed}</strong><small>{rate(data.failed, data.payments)} of payment attempts</small></div>
      <div className="metric panel"><span><Radio size={17} /> Webhook delivery</span><strong>{rate(data.delivered, data.deliveries)}</strong><small>{data.delivered} of {data.deliveries} delivered</small></div>
    </div>
    <Panel title="Payment activity" detail="Payment attempts by day over the last 14 days">
      {data.activity.some((item) => item.count > 0) ? <div className="chart" aria-label="Payment attempts by day">
        <ResponsiveContainer width="100%" height={240} initialDimension={{ width: 700, height: 240 }}>
          <AreaChart data={data.activity} margin={{ left: 0, right: 15, bottom: 0, top: 15 }}>
            <defs><linearGradient id="activity-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#347753" stopOpacity={0.28} /><stop offset="100%" stopColor="#347753" stopOpacity={0.02} /></linearGradient></defs>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="date" tickFormatter={(value) => value.slice(5)} tickLine={false} axisLine={false} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={36} />
            <Tooltip />
            <Area type="monotone" dataKey="count" name="Payments" stroke="#347753" strokeWidth={2} fill="url(#activity-fill)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div> : <Empty>Simulate a payment to see activity here.</Empty>}
    </Panel>
    <div className="two-columns">
      <Panel title="Recent failures">{data.recent_failures.length ? <ul className="row-list">{data.recent_failures.map((item) => <li key={item.id}><code>{item.id}</code><span>{item.reason ?? "No failure reason recorded"}</span></li>)}</ul> : <Empty>No failed payments recorded.</Empty>}</Panel>
      <Panel title="Latest test runs">{data.recent_runs.length ? <ul className="row-list">{data.recent_runs.map((item) => <li key={item.id}><Link href={"/tests?run=" + item.id}>{item.name}</Link><Status value={item.status} /></li>)}</ul> : <Empty>No reliability runs recorded.</Empty>}</Panel>
    </div>
  </>}</Remote>;
}

type Resource = "orders" | "payments" | "refunds";
type RecordRow = { id: string; amount: string; currency: string; status: string; reference: string | null; created_at: string };
const statuses: Record<Resource, string[]> = { orders: ["created", "attempted", "paid"], payments: ["created", "authorized", "captured", "failed", "refunded"], refunds: ["pending", "processed", "failed"] };

export function Records({ root, resource }: { root: string; resource: Resource }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState("");
  const path = root + "/dashboard/records/" + resource;
  const params = new URLSearchParams({ search, status, offset: String(offset) });
  return <>
    <Panel title={resource[0].toUpperCase() + resource.slice(1)}>
      <div className="filter-bar">
        <input aria-label="Search records" placeholder="Search by ID or reference" value={search} maxLength={120} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} />
        <select aria-label="Filter by status" value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0); }}>
          <option value="">All statuses</option>{statuses[resource].map((value) => <option key={value}>{value}</option>)}
        </select>
      </div>
      <Remote<RecordRow[]> path={path + "?" + params}>{(rows) => rows.length ? <div className="table-scroll"><table><thead><tr><th>ID</th><th>Amount</th><th>Status</th><th>Reference</th><th>Created</th></tr></thead><tbody>
        {rows.map((row) => <tr key={row.id}><td><button className="link-button" onClick={() => setSelected(row.id)}>{row.id}</button></td>
          <td>{minorAmount(row.amount, row.currency)}</td><td><Status value={row.status} /></td><td>{row.reference ?? "—"}</td><td>{date(row.created_at)}</td></tr>)}
      </tbody></table><div className="pagination"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(offset - 25)}>Previous</Button><span>Page {1 + offset / 25}</span><Button variant="outline" disabled={rows.length < 25} onClick={() => setOffset(offset + 25)}>Next</Button></div></div>
      : <><Empty>No matching {resource}.</Empty>{offset > 0 && <Button variant="outline" onClick={() => setOffset(offset - 25)}>Previous page</Button>}</>}</Remote>
    </Panel>
    {selected && <Panel title={selected} detail="Record details and related activity"><Remote<Record<string, unknown>> path={path + "/" + selected}>{(record) => <JsonPanel value={record} />}</Remote></Panel>}
  </>;
}
