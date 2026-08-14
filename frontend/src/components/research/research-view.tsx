"use client";

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Loader2, Search } from "lucide-react";

import { formatCoverage, formatDate, getResearch, listResearch, statusLabel, type Research } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";

function SourceList({ research }: { research: Research }) {
  if (research.sources.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No sources were returned. Coverage: {formatCoverage(research.coverage)}.
      </p>
    );
  }
  return (
    <ul className="space-y-3">
      {research.sources.map((source) => (
        <li key={source.url}>
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="group flex items-start gap-2 text-sm font-medium text-primary hover:underline"
          >
            {source.title}
            <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground group-hover:text-primary" aria-hidden="true" />
          </a>
          <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{source.snippet}</p>
          <p className="text-xs text-muted-foreground/70">
            {source.provider}
            {source.license ? ` · ${source.license}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

function ResearchDetail({ research }: { research: Research }) {
  const researching = research.status === "researching";
  return (
    <Card>
      <CardHeader className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-lg">{research.topic ?? `Research #${research.id}`}</CardTitle>
          <Badge variant={researching ? "secondary" : research.status === "complete" ? "default" : "destructive"}>
            {researching ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
            {statusLabel(research.status)}
          </Badge>
        </div>
        <CardDescription>
          {research.providers_used.length > 0
            ? `Providers: ${research.providers_used.join(", ")}`
            : "No providers ran yet"}
          {research.coverage != null ? ` · coverage ${formatCoverage(research.coverage)}` : ""}
          {research.updated_at ? ` · updated ${formatDate(research.updated_at)}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {researching ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Research in progress — sources and summary will appear when done.
          </div>
        ) : null}

        <div className="space-y-2">
          <h2 className="text-sm font-medium text-muted-foreground">Summary</h2>
          {research.summary_text ? (
            <div className="whitespace-pre-wrap text-sm leading-relaxed">{research.summary_text}</div>
          ) : research.status === "complete" ? (
            <p className="text-sm text-muted-foreground">
              Summary unavailable (Ollama was offline or failed). Sources are still available.
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">Waiting for research…</p>
          )}
        </div>

        {research.provider_errors ? (
          <div className="space-y-1">
            {Object.entries(research.provider_errors).map(([name, message]) => (
              <p key={name} className="text-xs text-muted-foreground">
                {name}: {message}
              </p>
            ))}
          </div>
        ) : null}

        <Separator />

        <div className="space-y-2">
          <h2 className="text-sm font-medium text-muted-foreground">
            Sources ({research.sources.length})
          </h2>
          <SourceList research={research} />
        </div>
      </CardContent>
    </Card>
  );
}

export function ResearchView() {
  const [runs, setRuns] = useState<Research[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const selected = runs.find((r) => r.id === selectedId) ?? null;

  const loadList = useCallback(async () => {
    try {
      const data = await listResearch();
      setRuns(data);
      setError(null);
      if (selectedId == null && data.length > 0) {
        setSelectedId(data[0].id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch; setState runs in a promise callback
    void loadList();
  }, [loadList]);

  // Poll the selected run while it is researching. getResearch also resumes a
  // stale run after a process restart, so statuses converge even if the
  // background worker was interrupted.
  useEffect(() => {
    if (!selected || selected.status !== "researching") return;
    const timer = setInterval(() => {
      getResearch(selected.id)
        .then((fresh) => {
          setRuns((prev) => prev.map((r) => (r.id === fresh.id ? fresh : r)));
        })
        .catch(() => {
          /* transient; next tick retries */
        });
    }, 2000);
    return () => clearInterval(timer);
  }, [selected]);

  return (
    <div className="space-y-6">
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState description={error} onRetry={() => void loadList()} />
      ) : runs.length === 0 ? (
        <EmptyState
          icon={Search}
          title="No research yet"
          description="Create an idea on the Ideas page and start research — summaries and cited sources appear here."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="text-base">Runs</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              {runs.map((run) => (
                <button
                  key={run.id}
                  type="button"
                  onClick={() => setSelectedId(run.id)}
                  className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                    selectedId === run.id
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                  }`}
                >
                  <span className="truncate">{run.topic ?? `Research #${run.id}`}</span>
                  <Badge
                    variant={run.status === "complete" ? "outline" : "secondary"}
                    className="shrink-0"
                  >
                    {statusLabel(run.status)}
                  </Badge>
                </button>
              ))}
            </CardContent>
          </Card>

          {selected ? (
            <ResearchDetail research={selected} />
          ) : (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                Select a run to see its summary and sources.
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
