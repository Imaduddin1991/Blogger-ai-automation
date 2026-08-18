import type { Metadata } from "next";

import { PageHeader } from "@/components/layout/page-header";
import { PublishHistory } from "@/components/publishing/publish-history";

export const metadata: Metadata = {
  title: "Publishing",
  description: "Publish status and history.",
};

export default function PublishingPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Publishing"
        description="Track publish attempts, successes, and failures for your articles."
      />
      <PublishHistory />
    </div>
  );
}
