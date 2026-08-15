import type { Metadata } from "next";

import { ArticlesView } from "@/components/articles/articles-view";
import { PageHeader } from "@/components/layout/page-header";

export const metadata: Metadata = {
  title: "Articles",
  description: "Generated and in-progress articles.",
};

export default function ArticlesPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Articles"
        description="Review, edit, and check generated articles before approval."
      />
      <ArticlesView />
    </div>
  );
}
