import type { Metadata } from "next";
import { Search } from "lucide-react";

import { PlaceholderPage } from "@/components/layout/placeholder-page";

export const metadata: Metadata = {
  title: "Research",
  description: "Research summaries and sources.",
};

export default function ResearchPage() {
  return (
    <PlaceholderPage
      title="Research"
      description="Source-grounded summaries for your topics."
      icon={Search}
      emptyTitle="No research yet"
      emptyDescription="Research summaries with cited sources will appear here once ideas are processed."
    />
  );
}
