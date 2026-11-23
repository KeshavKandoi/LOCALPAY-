"use client";

import { useProject } from "./shell";
import { Overview, Records } from "./records";
import { Chaos, Reports, SettingsPanel, Tests, Webhooks } from "./workflows";
import { sections, type SectionKey } from "@/lib/sections";

export function Section({ section, initialRun }: { section: SectionKey; initialRun?: string }) {
  const project = useProject();
  if (!project) return null;
  const root = "projects/" + project.id;
  const title = sections.find((item) => item.key === section)?.label;
  const views = {
    overview: <Overview root={root} />,
    orders: <Records root={root} resource="orders" />,
    payments: <Records root={root} resource="payments" />,
    refunds: <Records root={root} resource="refunds" />,
    webhooks: <Webhooks root={root} />,
    chaos: <Chaos root={root} />,
    tests: <Tests root={root} initialRun={initialRun} />,
    reports: <Reports root={root} />,
    settings: <SettingsPanel root={root} />,
  };
  return <div className="section-stack" key={project.id + section}><h1>{title}</h1>{views[section]}</div>;
}
