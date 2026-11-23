"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { defaultDraft, execute, prepare, type Result } from "@/lib/workspace";
import { Button } from "./ui/button";

const scenarios = [
  ["success", "Authorize payment for capture"],
  ["failed", "Fail the simulated payment"],
  ["insufficient_funds", "Decline for insufficient funds"],
  ["authorization_failed", "Reject authorization"],
  ["capture_failed", "Authorize the payment and reject capture"],
  ["timeout", "Return a simulated HTTP 504"],
  ["network_interruption", "Return a simulated HTTP 503"],
];
const actions = ["Create order", "Simulate payment", "Capture payment", "Refund payment", "List refunds", "Resolve refund"] as const;

type RecordView = {
  id: string;
  entity: "order" | "payment" | "refund";
  status: string;
  amount: number;
  currency?: string;
  amount_paid?: number;
  amount_due?: number;
  amount_refunded?: number;
  attempts?: number;
  error_description?: string;
  created_at: number;
};

function isRecord(value: unknown): value is RecordView {
  return !!value && typeof value === "object" && "id" in value && typeof value.id === "string" &&
    "entity" in value && ["order", "payment", "refund"].some((entity) => entity === value.entity) &&
    "status" in value && typeof value.status === "string" && "amount" in value && typeof value.amount === "number" &&
    "created_at" in value && typeof value.created_at === "number";
}

export function Simulator({ project }: { project: string }) {
  const [action, setAction] = useState<typeof actions[number]>("Create order");
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [orderId, setOrderId] = useState("");
  const [paymentId, setPaymentId] = useState("");
  const [refundId, setRefundId] = useState("");
  const [amount, setAmount] = useState("50000");
  const [currency, setCurrency] = useState("INR");
  const [scenario, setScenario] = useState("success");
  const [refundOutcome, setRefundOutcome] = useState("processed");
  const [records, setRecords] = useState<RecordView[]>([]);
  const [result, setResult] = useState<Result>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (active.current) return;
    setError("");
    setResult(undefined);
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    try {
      const numeric = Number(amount);
      if (["Create order", "Capture payment", "Refund payment"].includes(action) && (!Number.isSafeInteger(numeric) || numeric < 0)) {
        throw new Error("Enter an amount in whole minor currency units.");
      }
      const paymentPath = "/v1/payments/" + encodeURIComponent(paymentId);
      const refundPath = "/localpay/v1/simulations/refunds/" + encodeURIComponent(refundId);
      let url: string;
      let body: object | undefined;
      let headers = "";
      if (action === "Create order") {
        const notes = value("notes") ? JSON.parse(value("notes")) : {};
        url = "/v1/orders";
        body = { amount: numeric, currency, notes, receipt: value("receipt") || null };
      } else if (action === "Simulate payment") {
        url = "/localpay/v1/simulations/payments";
        body = { order_id: orderId, method: value("method"), scenario: "payment." + scenario };
        if (value("idempotency")) headers = "X-LocalPay-Idempotency-Key: " + value("idempotency");
      } else if (action === "Capture payment") {
        url = paymentPath + "/capture";
        body = { amount: numeric, currency };
      } else if (action === "Refund payment") {
        url = refundOutcome === "processed" ? paymentPath + "/refund" : "/localpay/v1/simulations/payments/" + encodeURIComponent(paymentId) + "/refunds";
        body = { amount: amount === "" ? null : numeric, ...(refundOutcome === "processed" ? {} : { outcome: refundOutcome }) };
        if (value("idempotency")) headers = "X-Refund-Idempotency: " + value("idempotency");
      } else if (action === "List refunds") {
        url = paymentPath + "/refunds";
      } else {
        url = refundPath + "/resolve";
        body = { outcome: value("resolution") };
      }
      const response = await execute(prepare({ ...defaultDraft, url, method: body ? "POST" : "GET", format: body ? "json" : "none", body: body ? JSON.stringify(body) : "", headers },
        project, "", "", key, secret, null), controller.signal);
      setResult(response);
      const record = response.json;
      if (isRecord(record)) {
        setRecords((previous) => [...previous, record]);
        if (record.entity === "order") {
          setOrderId(record.id);
          setAction("Simulate payment");
        } else if (record.entity === "payment") {
          setPaymentId(record.id);
          if (record.status === "authorized") {
            setAmount(String(record.amount));
            if (record.currency) setCurrency(record.currency);
            setAction("Capture payment");
          }
          if (record.status === "captured") {
            setAmount("");
            setAction("Refund payment");
          }
        } else setRefundId(record.id);
      }
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not execute payment action.");
    } finally {
      active.current = null;
      setBusy(false);
    }
  }

  return <div className="workspace-editor">
    <form className="panel form-panel" onSubmit={submit}>
      <div className="input-row">
        <label>Key ID<input required autoComplete="off" value={key} onChange={(event) => setKey(event.target.value)} /></label>
        <label>Key secret<input required autoComplete="off" type="password" value={secret} onChange={(event) => setSecret(event.target.value)} /></label>
      </div>
      <label>Payment action<select value={action} onChange={(event) => setAction(event.target.value as typeof action)}>{actions.map((name) => <option key={name}>{name}</option>)}</select></label>
      {["Create order", "Capture payment", "Refund payment"].includes(action) && <label>{action === "Refund payment" ? "Amount (blank for full refund)" : "Amount in minor currency units"}<input required={action !== "Refund payment"} type="number" min={action === "Create order" ? 0 : 1} step="1" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>}
      {["Create order", "Capture payment"].includes(action) && <label>Currency<input required pattern="[A-Z]{3}" maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} /></label>}
      {action === "Create order" && <>
        <label>Receipt<input name="receipt" maxLength={40} /></label>
        <label>Notes (JSON object)<textarea name="notes" rows={3} placeholder="{}" /></label>
      </>}
      {action === "Simulate payment" && <>
        <label>Order ID<input required value={orderId} onChange={(event) => setOrderId(event.target.value)} /></label>
        <label>Payment method<select name="method">{["card", "upi", "netbanking", "wallet", "emi", "paylater"].map((method) => <option key={method}>{method}</option>)}</select></label>
        <label>Scenario<select value={scenario} onChange={(event) => setScenario(event.target.value)}>{scenarios.map(([key, description]) => <option value={key} key={key}>{description}</option>)}</select></label>
      </>}
      {["Capture payment", "Refund payment", "List refunds"].includes(action) && <label>Payment ID<input required value={paymentId} onChange={(event) => setPaymentId(event.target.value)} /></label>}
      {["Simulate payment", "Refund payment"].includes(action) && <label>Idempotency key<input name="idempotency" minLength={10} maxLength={128} /></label>}
      {action === "Refund payment" && <label>Refund outcome<select value={refundOutcome} onChange={(event) => setRefundOutcome(event.target.value)}>{["processed", "pending", "failed"].map((outcome) => <option key={outcome}>{outcome}</option>)}</select></label>}
      {action === "Resolve refund" && <>
        <label>Refund ID<input required value={refundId} onChange={(event) => setRefundId(event.target.value)} /></label>
        <label>Resolution<select name="resolution"><option>processed</option><option>failed</option></select></label>
      </>}
      <Button type="submit" disabled={busy}>{busy ? "Sending…" : action}</Button>
      {error && <p role="alert" className="form-error">{error}</p>}
    </form>
    <div className="section-stack">
      <section className="panel" aria-label="Payment lifecycle">
        <div className="panel-heading"><h2>Session lifecycle</h2></div>
        {records.length ? <ol className="row-list">{records.map((record, index) => <li key={index}>
          <div><strong>{record.entity} · {record.status}</strong><br /><code>{record.id}</code></div>
          <div>{record.currency} {record.amount} · <time>{new Date(record.created_at * 1000).toLocaleString()}</time></div>
          {record.amount_refunded !== undefined && <div>Refunded amount {record.amount_refunded}</div>}
          {record.amount_due !== undefined && <div>Paid {record.amount_paid} · Due {record.amount_due} · Attempts {record.attempts}</div>}
          {record.error_description && <p className="form-error">{record.error_description}</p>}
        </li>)}</ol> : <p className="empty">Run a payment action to see its returned state.</p>}
      </section>
      <section className="panel" aria-label="Payment action response">
        <div className="panel-heading"><h2>Latest response</h2>{result && <p role="status">HTTP {result.status} · {result.ms} ms</p>}</div>
        {result && <pre className="payload">{result.json === undefined ? result.raw : JSON.stringify(result.json, null, 2)}</pre>}
      </section>
    </div>
  </div>;
}
