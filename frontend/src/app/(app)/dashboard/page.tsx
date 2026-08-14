import type { Metadata } from "next";
import { LayoutDashboard } from "lucide-react";

import { PlaceholderPage } from "@/components/layout/placeholder-page";

export const metadata: Metadata = {
  title: "Dashboard",
  description: "Overview of your article pipeline.",
};

export default function DashboardPage() {
  return (
    <PlaceholderPage
      title="Dashboard"
      description="Overview of your article pipeline."
      icon={LayoutDashboard}
      emptyTitle="Nothing running yet"
      emptyDescription="Once you create an idea, the pipeline stages will appear here with live status."
    />
  );
}
