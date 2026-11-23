"use client";

import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Circle, LogOut, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, post } from "@/lib/api";
import { BrandIcon, sections } from "@/lib/sections";
import { AccountSettings, AccountLogin } from "./account";
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

export function Brand() {
  return <div className="brand"><span className="brand-icon"><BrandIcon size={20} aria-hidden /></span><span>LocalPay</span></div>;
}

function Shell({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState("");
  const [dark, setDark] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const pathname = usePathname();
  const router = useRouter();
  const cache = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const response = await fetch("/api/session");
      if (!response.ok) throw new Error("Unable to load session.");
      return response.json() as Promise<{ authenticated: boolean; username?: string }>;
    },
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<Project[]>("projects"),
    enabled: !!session.data?.authenticated,
  });
  const project = projects.data?.find((item) => item.id === selected) ?? projects.data?.[0] ?? null;
  const active = sections.find((item) => pathname === "/" + item.key)?.label ?? "Overview";

  useEffect(() => {
    if (!session.data) return;
    if (!session.data.authenticated && pathname !== "/signup" && pathname !== "/login") router.replace("/login");
    if (session.data.authenticated && (pathname === "/signup" || pathname === "/login")) router.replace("/");
  }, [pathname, router, session.data]);

  if (session.isPending) return <div className="splash" role="status">Loading LocalPay…</div>;
  if (session.error) return <div className="splash" role="alert">{session.error.message} <Button onClick={() => session.refetch()}>Retry</Button></div>;
  if (!session.data?.authenticated) return <AccountLogin signup={pathname === "/signup"} dark={dark} toggleTheme={() => setDark(!dark)} signedIn={(username) => {
    cache.setQueryData(["session"], { authenticated: true, username });
    router.replace("/");
  }} />;
  async function signOut() {
    const response = await fetch("/api/session", { method: "DELETE" });
    if (!response.ok) throw new Error("Could not sign out. Try again.");
    cache.setQueryData(["session"], { authenticated: false });
    cache.removeQueries({ predicate: (query) => query.queryKey[0] !== "session" });
    setSelected("");
    router.replace("/login");
  }

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
        <Button asChild variant="ghost"><Link href="/settings/account">Account Settings</Link></Button>
        <Button variant="ghost" aria-label="Sign out" onClick={() => void signOut().catch((error: Error) => setSignOutError(error.message))}><LogOut size={17} /></Button>
      </div></header>
      <main className="content" id="main-content">
        {signOutError && <p role="alert">{signOutError}</p>}
        {pathname === "/settings/account" ? <AccountSettings username={session.data.username ?? ""} signOut={signOut} /> : projects.isPending ? <div className="panel empty" role="status">Loading projects…</div>
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
