import type { Metadata } from "next";
import { CalendarClock } from "lucide-react";

import { PlaceholderPage } from "@/components/layout/placeholder-page";

export const metadata: Metadata = {
  title: "Scheduler",
  description: "Scheduled publishing jobs.",
};

export default function SchedulerPage() {
  return (
    <PlaceholderPage
      title="Scheduler"
      description="Articles queued to publish at a chosen time."
      icon={CalendarClock}
      emptyTitle="No scheduled jobs"
      emptyDescription="Articles you schedule for publishing will be listed here with their run time."
    />
  );
}
