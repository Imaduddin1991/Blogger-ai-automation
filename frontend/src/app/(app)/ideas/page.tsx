import type { Metadata } from "next";
import { Lightbulb } from "lucide-react";

import { PlaceholderPage } from "@/components/layout/placeholder-page";

export const metadata: Metadata = {
  title: "Ideas",
  description: "Your blog ideas.",
};

export default function IdeasPage() {
  return (
    <PlaceholderPage
      title="Ideas"
      description="Enter a blog topic and turn it into a researched article."
      icon={Lightbulb}
      emptyTitle="No ideas yet"
      emptyDescription="Your first blog idea will appear here. New ideas start the research pipeline."
    />
  );
}
