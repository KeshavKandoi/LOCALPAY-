"use client";

import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Circle, LogOut, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useState, type FormEvent, type ReactNode } from "react";
import { api, post } from "@/lib/api";
import { BrandIcon, sections } from "@/lib/sections";
import { Button } from "./ui/button";

export type Project = { id: string; name: string; slug: string; status: string };
const ProjectContext = createContext<Project | null>(null);

export function useProject() {
  return useContext(ProjectContext);
}

export function DashboardShell({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 6000 } } }));
  return <QueryClientProvider client={client}><Shell>{children}</Shell></QueryClientProvider>;
}

function Brand() {
  return <div className="brand"><span className="brand-icon"><BrandIcon size={20} aria-hidden /></span><span>LocalPay</span></div>;
}

function Shell({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState("");
  const [dark, setDark] = useState(false);
  const pathname = usePathname();
  const cache = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const response = await fetch("/api/session");
      if (!response.ok) throw new Error("Unable to load session.");
      return response.json() as Promise<{ authenticated: boolean }>;
    },
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<Project[]>("projects"),
    enabled: !!session.data?.authenticated,
  });
  const project = projects.data?.find((item) => item.id === selected) ?? projects.data?.[0] ?? null;
  const active = sections.find((item) => pathname === "/" + item.key)?.label ?? "Overview";

  if (session.isPending) return <div className="splash" role="status">Loading LocalPay…</div>;
  if (session.error) return <div className="splash" role="alert">{session.error.message} <Button onClick={() => session.refetch()}>Retry</Button></div>;
  if (!session.data?.authenticated) return <Login />;
  return <div className="workspace" data-theme={dark ? "dark" : "light"}>
    <aside className="sidebar">
      <Brand />
      <label className="project-select"><span>Project</span><select aria-label="Project" value={project?.id ?? ""} onChange={(event) => setSelected(event.target.value)}>
        {projects.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        {!project && <option value="">No project</option>}
      </select><ChevronDown size={15} aria-hidden /></label>
      <nav aria-label="Dashboard">
        {sections.map(({ key, label, icon: Icon }) => <Link key={key} className="nav-item" aria-current={pathname === "/" + key ? "page" : undefined} href={"/" + key}>
          <Icon size={17} aria-hidden /><span>{label}</span>
        </Link>)}
      </nav>
      <div className="sidebar-bottom"><Circle size={8} fill="currentColor" aria-hidden /> Simulation workspace</div>
    </aside>
    <div className="workspace-body">
      <header className="topbar"><span>{active}</span><div>
        <Button variant="ghost" aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} onClick={() => setDark(!dark)}>
          {dark ? <Sun size={18} /> : <Moon size={18} />}
        </Button>
        <Button variant="ghost" aria-label="Sign out" onClick={async () => {
          await fetch("/api/session", { method: "DELETE" });
          cache.setQueryData(["session"], { authenticated: false });
          cache.removeQueries({ predicate: (query) => query.queryKey[0] !== "session" });
          setSelected("");
        }}><LogOut size={17} /></Button>
      </div></header>
      <main className="content" id="main-content">
        {projects.isPending ? <div className="panel empty" role="status">Loading projects…</div>
          : projects.error ? <div className="panel empty" role="alert">{projects.error.message}<Button variant="outline" onClick={() => projects.refetch()}>Retry</Button></div>
          : project ? <ProjectContext.Provider value={project}>{children}</ProjectContext.Provider>
          : <ProjectCreate />}
      </main>
    </div>
  </div>;
}

export function ProjectCreate() {
  const cache = useQueryClient();
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    setWorking(true);
    setError("");
    try {
      await post<Project>("projects", { name: fields.get("name"), slug: fields.get("slug") });
      await cache.invalidateQueries({ queryKey: ["projects"] });
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setWorking(false);
    }
  }
  return <form className="panel form-panel" onSubmit={submit}>
    <h2>Create project</h2>
    <label>Project name<input name="name" required maxLength={120} /></label>
    <label>Project slug<input name="slug" required maxLength={63} pattern="[a-z0-9]+(-[a-z0-9]+)*" /></label>
    {error && <p role="alert" className="form-error">{error}</p>}
    <Button type="submit" disabled={working}>{working ? "Creating…" : "Create project"}</Button>
  </form>;
}

function Login() {
  const cache = useQueryClient();
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = new FormData(event.currentTarget).get("token");
    setWorking(true);
    setError("");
    try {
      const response = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
      if (!response.ok) throw new Error("Invalid administration token.");
      cache.setQueryData(["session"], { authenticated: true });
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setWorking(false);
    }
  }
  return <main className="login"><div className="login-card panel"><Brand /><h1>Sign in to LocalPay</h1><p>Use the administration token configured on your LocalPay instance.</p>
    <form className="form-panel login-form" onSubmit={submit}>
      <label>Administration token<input name="token" type="password" autoComplete="current-password" required maxLength={128} /></label>
      {error && <p role="alert" className="form-error">{error}</p>}
      <Button type="submit" disabled={working}>{working ? "Signing in…" : "Sign in"}</Button>
    </form>
  </div></main>;
}
