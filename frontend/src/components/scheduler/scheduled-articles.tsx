"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, Loader2, XCircle } from "lucide-react";

import {
  listScheduled,
  cancelSchedule,
  formatDate,
  type ScheduledArticle,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
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

function ScheduledRow({
  entry,
  onCancel,
  busy,
}: {
  entry: ScheduledArticle;
  onCancel: (articleId: number) => void;
  busy: boolean;
}) {
  return (
    <tr className="border-b border-border/60 last:border-0">
      <td className="py-3 pr-4 text-sm font-medium">
        {entry.article_title ?? `Article #${entry.article_id}`}
      </td>
      <td className="py-3 pr-4 text-sm whitespace-nowrap">
        {formatDate(entry.run_at)}
      </td>
      <td className="py-3 pr-4">
        <Badge variant="outline" className="gap-1">
          <CalendarClock className="h-3 w-3" aria-hidden="true" />
          Pending
        </Badge>
      </td>
      <td className="py-3 text-right">
        <Button
          variant="ghost"
          size="sm"
          className="gap-1 text-destructive"
          onClick={() => onCancel(entry.article_id)}
          disabled={busy}
        >
          <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
          Cancel
        </Button>
      </td>
    </tr>
  );
}

export function ScheduledArticles() {
  const [entries, setEntries] = useState<ScheduledArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await listScheduled();
      setEntries(data);
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

  const handleCancel = useCallback(
    async (articleId: number) => {
      if (!window.confirm("Cancel this scheduled publish?")) return;
      setBusy(true);
      try {
        await cancelSchedule(articleId);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Loading" />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return <ErrorState description={error} onRetry={() => void refresh()} />;
  }

  if (entries.length === 0) {
    return (
      <Card>
        <CardContent className="py-12">
          <EmptyState
            icon={CalendarClock}
            title="No scheduled articles"
            description="Schedule an approved article for future publishing and it will appear here."
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Scheduled Publishing</CardTitle>
        <CardDescription>
          {entries.length} article{entries.length !== 1 ? "s" : ""} scheduled for future publishing.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 pr-4 text-sm font-medium text-muted-foreground">Article</th>
                <th className="pb-2 pr-4 text-sm font-medium text-muted-foreground">Publish At</th>
                <th className="pb-2 pr-4 text-sm font-medium text-muted-foreground">Status</th>
                <th className="pb-2 text-right text-sm font-medium text-muted-foreground">Action</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <ScheduledRow
                  key={entry.job_id}
                  entry={entry}
                  onCancel={handleCancel}
                  busy={busy}
                />
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
