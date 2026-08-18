"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  FileText,
  LayoutDashboard,
  Lightbulb,
  Search,
  XCircle,
} from "lucide-react";
import Link from "next/link";

import { getDashboard, type Dashboard } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";

type StatCardProps = {
  label: string;
  value: number;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
};

function StatCard({ label, value, href, icon: Icon }: StatCardProps) {
  return (
    <Link href={href} className="group">
      <Card className="transition-colors group-hover:border-primary/40">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
          <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <span className="text-3xl font-semibold tracking-tight">{value}</span>
          <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
        </CardContent>
      </Card>
    </Link>
  );
}

export function DashboardView() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const d = await getDashboard();
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch; setState runs in a promise callback
    void refresh();
  }, [refresh]);

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-busy="true" aria-label="Loading">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="h-24 animate-pulse p-5" />
          </Card>
        ))}
      </div>
    );
  }

  if (error) {
    return <ErrorState description={error} onRetry={() => void refresh()} />;
  }

  const empty = data && data.idea_count === 0;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard label="Ideas" value={data?.idea_count ?? 0} href="/ideas" icon={Lightbulb} />
        <StatCard label="Research runs" value={data?.research_count ?? 0} href="/research" icon={Search} />
        <StatCard label="Articles" value={data?.article_count ?? 0} href="/articles" icon={FileText} />
        <StatCard label="Published" value={data?.publish_success_count ?? 0} href="/publishing" icon={CheckCircle2} />
        <StatCard label="Publish failed" value={data?.publish_fail_count ?? 0} href="/publishing" icon={XCircle} />
        <StatCard label="Scheduled" value={data?.scheduled_count ?? 0} href="/scheduler" icon={CalendarClock} />
      </div>

      {empty ? (
        <EmptyState
          icon={LayoutDashboard}
          title="Nothing running yet"
          description="Add your first blog idea to start the pipeline: idea → research → summary → article."
          action={
            <Button asChild>
              <Link href="/ideas">Create an idea</Link>
            </Button>
          }
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Next step</CardTitle>
            <CardDescription>
              Continue from where the pipeline left off.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button asChild>
              <Link href="/ideas">Add an idea</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/research">Review research</Link>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
