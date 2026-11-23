"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ChevronDown, Inbox, LoaderCircle } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "@/lib/api";
import { Button } from "./ui/button";

export function Panel({ title, children, detail }: { title: string; children: ReactNode; detail?: string }) {
  return <section className="panel"><div className="panel-heading"><h2>{title}</h2>{detail && <p>{detail}</p>}</div>{children}</section>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty"><Inbox size={24} aria-hidden /><p>{children}</p></div>;
}

export function Remote<T>({ path, children, poll }: { path: string; children: (data: T) => ReactNode; poll?: number }) {
  const result = useQuery({ queryKey: [path], queryFn: () => api<T>(path), refetchInterval: poll });
  if (result.isPending) return <div className="empty" role="status"><LoaderCircle className="animate-spin" size={22} /> Loading records…</div>;
  if (result.error) return <div className="empty" role="alert"><AlertCircle size={22} />{result.error.message}<Button variant="outline" onClick={() => result.refetch()}>Retry</Button></div>;
  return children(result.data);
}

export function Status({ value }: { value: string }) {
  const color = ["paid", "captured", "delivered", "succeeded", "passed", "processed", "active", "ready"].includes(value)
    ? "good" : ["failed", "error", "unavailable", "revoked"].includes(value) ? "bad" : "neutral";
  return <span className={"state state-" + color}>{value.replaceAll("_", " ")}</span>;
}

export function JsonPanel({ value }: { value: unknown }) {
  return <pre className="payload">{JSON.stringify(value, null, 2)}</pre>;
}

export function SelectField({ label, name, children, required = false }: { label: string; name: string; children: ReactNode; required?: boolean }) {
  return <label>{label}<span className="select-wrap"><select name={name} required={required}>{children}</select><ChevronDown size={14} aria-hidden /></span></label>;
}

export function ActionForm({ label, execute, children }: { label: string; execute: (data: FormData) => Promise<string>; children: ReactNode }) {
  const [state, setState] = useState<{ pending: boolean; error: boolean; message: string }>({ pending: false, error: false, message: "" });
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setState({ pending: true, error: false, message: "" });
    try {
      const message = await execute(data);
      setState({ pending: false, error: false, message });
    } catch (failure) {
      setState({ pending: false, error: true, message: (failure as Error).message });
    }
  }
  return <form className="form-panel" onSubmit={submit}>
    {children}
    <Button type="submit" disabled={state.pending}>{state.pending ? "Working…" : label}</Button>
    {state.message && <p className={state.error ? "form-error" : "form-success"} role={state.error ? "alert" : "status"}>{state.message}</p>}
  </form>;
}

export function date(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function minorAmount(amount: string, currency: string): string {
  const options = new Intl.NumberFormat(undefined, { style: "currency", currency }).resolvedOptions();
  const exponent = options.maximumFractionDigits ?? 2;
  const abs = BigInt(amount);
  const scale = 10n ** BigInt(exponent);
  const whole = new Intl.NumberFormat().format(abs / scale);
  const fraction = exponent ? "." + (abs % scale).toString().padStart(exponent, "0") : "";
  return currency + " " + whole + fraction;
}
