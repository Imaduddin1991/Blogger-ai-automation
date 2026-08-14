import type { Metadata } from "next";

import { DashboardView } from "@/components/dashboard/dashboard-view";

export const metadata: Metadata = {
  title: "Dashboard",
  description: "Overview of your article pipeline.",
};

export default function DashboardPage() {
  return <DashboardView />;
}
