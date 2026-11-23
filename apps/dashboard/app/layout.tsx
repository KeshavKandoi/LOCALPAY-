import type { Metadata } from "next";
import type { ReactNode } from "react";
import { DashboardShell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "LocalPay — Integration dashboard",
  description: "Inspect simulated payments and run integration reliability tests.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body><DashboardShell>{children}</DashboardShell></body></html>;
}
