import type { Metadata } from "next";

import { ScheduledArticles } from "@/components/scheduler/scheduled-articles";

export const metadata: Metadata = {
  title: "Scheduler",
  description: "Scheduled publishing jobs.",
};

export default function SchedulerPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Scheduler</h1>
        <p className="text-sm text-muted-foreground">
          Articles queued for future publishing.
        </p>
      </div>
      <ScheduledArticles />
    </div>
  );
}
