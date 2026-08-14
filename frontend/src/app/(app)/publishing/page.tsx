import type { Metadata } from "next";
import { Send } from "lucide-react";

import { PlaceholderPage } from "@/components/layout/placeholder-page";

export const metadata: Metadata = {
  title: "Publishing",
  description: "Publish status and history.",
};

export default function PublishingPage() {
  return (
    <PlaceholderPage
      title="Publishing"
      description="Send approved articles to Blogger and track status."
      icon={Send}
      emptyTitle="Nothing published yet"
      emptyDescription="Articles you publish to Blogger will be tracked here, including failures and retries."
    />
  );
}
