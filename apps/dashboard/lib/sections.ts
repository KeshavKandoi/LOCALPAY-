import { Activity, Braces, Beaker, CreditCard, FileBarChart, FlaskConical, LayoutGrid, Package, RotateCcw, Settings, Webhook } from "lucide-react";

export const sections = [
  { key: "overview", label: "Overview", icon: LayoutGrid },
  { key: "workspace", label: "API Workspace", icon: Braces },
  { key: "simulator", label: "Payment Simulator", icon: CreditCard },
  { key: "orders", label: "Orders", icon: Package },
  { key: "payments", label: "Payments", icon: CreditCard },
  { key: "refunds", label: "Refunds", icon: RotateCcw },
  { key: "webhooks", label: "Webhooks", icon: Webhook },
  { key: "chaos", label: "Chaos Lab", icon: FlaskConical },
  { key: "tests", label: "Test Runner", icon: Beaker },
  { key: "reports", label: "Reports", icon: FileBarChart },
  { key: "settings", label: "Settings", icon: Settings },
] as const;

export const BrandIcon = Activity;
export type SectionKey = typeof sections[number]["key"];
