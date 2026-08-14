import type { Metadata } from "next";
import { FileText } from "lucide-react";

import { PlaceholderPage } from "@/components/layout/placeholder-page";

export const metadata: Metadata = {
  title: "Articles",
  description: "Generated and in-progress articles.",
};

export default function ArticlesPage() {
  return (
    <PlaceholderPage
      title="Articles"
      description="Review, edit, and approve generated articles."
      icon={FileText}
      emptyTitle="No articles yet"
      emptyDescription="Articles you generate from ideas will be listed here for review and approval."
    />
  );
}
