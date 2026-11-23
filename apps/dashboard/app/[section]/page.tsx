import { notFound } from "next/navigation";
import { Section } from "@/components/section";
import { sections } from "@/lib/sections";

export default async function DashboardPage({ params, searchParams }: {
  params: Promise<{ section: string }>;
  searchParams: Promise<{ run?: string | string[] }>;
}) {
  const { section } = await params;
  const { run } = await searchParams;
  const match = sections.find((item) => item.key === section);
  if (!match) notFound();
  return <Section section={match.key} initialRun={typeof run === "string" ? run : undefined} />;
}
