"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  ExternalLink,
  History,
  Loader2,
  XCircle,
} from "lucide-react";

import {
  listPublishLog,
  formatDate,
  type PublishLogEntry,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";

function ResultBadge({ result }: { result: string }) {
  if (result === "success") {
    return (
      <Badge variant="default" className="gap-1 bg-emerald-600">
        <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
        Success
      </Badge>
    );
  }
  if (result === "error") {
    return (
      <Badge variant="destructive" className="gap-1">
        <XCircle className="h-3 w-3" aria-hidden="true" />
        Failed
      </Badge>
    );
  }
  return <Badge variant="outline">{result}</Badge>;
}

function ActionLabel({ action }: { action: string }) {
  switch (action) {
    case "publish":
      return <span>Publish</span>;
    case "publish_draft":
      return <span>Save as draft</span>;
    case "retry":
      return <span>Retry publish</span>;
    case "update":
      return <span>Update</span>;
    default:
      return <span className="capitalize">{action.replace(/_/g, " ")}</span>;
  }
}

function LogRow({ entry }: { entry: PublishLogEntry }) {
  return (
    <tr className="border-b border-border/60 last:border-0">
      <td className="py-3 pr-4 text-sm font-medium">
        {entry.article_title ?? `Article #${entry.article_id}`}
      </td>
      <td className="py-3 pr-4 text-sm">
        <ActionLabel action={entry.action} />
      </td>
      <td className="py-3 pr-4">
        <ResultBadge result={entry.result} />
      </td>
      <td className="py-3 pr-4 text-sm text-muted-foreground">
        {entry.details?.error ? (
          <span className="text-destructive" title={String(entry.details.error)}>
            {String(entry.details.error).slice(0, 80)}
          </span>
        ) : null}
      </td>
      <td className="py-3 pr-4 text-sm">
        {entry.blogger_post_url ? (
          <a
            href={entry.blogger_post_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-blue-600 hover:underline dark:text-blue-400"
          >
            View
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        ) : null}
      </td>
      <td className="py-3 text-sm text-muted-foreground whitespace-nowrap">
        {formatDate(entry.created_at)}
      </td>
    </tr>
  );
}

export function PublishHistory() {
  const [entries, setEntries] = useState<PublishLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listPublishLog();
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
            icon={History}
            title="No publish history yet"
            description="Publish an article to Blogger and it will appear here."
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Publish History</CardTitle>
        <CardDescription>
          {entries.length} publish {entries.length === 1 ? "attempt" : "attempts"} recorded.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 pr-4 text-sm font-medium text-muted-foreground">Article</th>
                <th className="pb-2 pr-4 text-sm font-medium text-muted-foreground">Action</th>
                <th className="pb-2 pr-4 text-sm font-medium text-muted-foreground">Result</th>
                <th className="pb-2 pr-4 text-sm font-medium text-muted-foreground">Error</th>
                <th className="pb-2 pr-4 text-sm font-medium text-muted-foreground">Link</th>
                <th className="pb-2 text-sm font-medium text-muted-foreground">Date</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <LogRow key={entry.id} entry={entry} />
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
