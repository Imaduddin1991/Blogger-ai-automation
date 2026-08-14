import type { Metadata } from "next";
import { Settings } from "lucide-react";

import { PlaceholderPage } from "@/components/layout/placeholder-page";

export const metadata: Metadata = {
  title: "Settings",
  description: "Ollama, blog connection, and defaults.",
};

export default function SettingsPage() {
  return (
    <PlaceholderPage
      title="Settings"
      description="Ollama connection, Blogger account, and default model."
      icon={Settings}
      emptyTitle="Configuration pending"
      emptyDescription="Ollama URL, default model, and your Blogger connection will be configured here."
    />
  );
}
