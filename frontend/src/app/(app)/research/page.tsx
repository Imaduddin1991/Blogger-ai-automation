import type { Metadata } from "next";

import { ResearchView } from "@/components/research/research-view";

export const metadata: Metadata = {
  title: "Research",
  description: "Research summaries and sources.",
};

export default function ResearchPage() {
  return <ResearchView />;
}
