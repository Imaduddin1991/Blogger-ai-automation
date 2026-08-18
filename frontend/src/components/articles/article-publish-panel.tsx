"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarClock, ExternalLink, Globe, Loader2, RotateCw, Save, Trash2, X } from "lucide-react";

import {
  getArticle,
  publishArticle,
  retryPublish,
  deletePublishedPost,
  getBloggerStatus,
  scheduleArticle,
  cancelSchedule,
  formatDate,
  type ArticleDetail,
  type BloggerStatus,
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
import { Input } from "@/components/ui/input";

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_MS = 120_000;

const PUBLISH_VISIBLE = new Set([
  "approved",
  "publishing",
  "published",
  "publish_failed",
  "scheduled",
]);

function hasPublishError(article: ArticleDetail): boolean {
  if (article.status !== "publish_failed") return false;
  const errors = article.generation_errors;
  if (!errors) return false;
  return "publish" in errors;
}

function PublishErrorDetail({ article }: { article: ArticleDetail }) {
  const msg = article.generation_errors?.publish;
  if (!msg) return null;
  return (
    <p className="text-sm text-destructive" role="alert">
      {msg}
    </p>
  );
}

export function ArticlePublishPanel({
  article,
  onChange,
}: {
  article: ArticleDetail;
  onChange: (updated: ArticleDetail) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blogStatus, setBlogStatus] = useState<BloggerStatus | null>(null);
  const [prevId, setPrevId] = useState(article.id);
  const pollDeadlineRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  if (prevId !== article.id) {
    setPrevId(article.id);
    setError(null);
    setBusy(false);
  }

  useEffect(() => {
    getBloggerStatus()
      .then(setBlogStatus)
      .catch(() => setBlogStatus(null));
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      pollDeadlineRef.current = null;
    };
  }, []);

  const pollForPublish = useCallback(
    (startArticle: ArticleDetail) => {
      if (timerRef.current) return;
      if (pollDeadlineRef.current === null) {
        pollDeadlineRef.current = Date.now() + POLL_MAX_MS;
      }
      timerRef.current = setInterval(async () => {
        if (Date.now() > (pollDeadlineRef.current ?? 0)) {
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
          return;
        }
        try {
          const fresh = await getArticle(startArticle.id);
          onChange(fresh);
          if (fresh.status !== "publishing" || !fresh.running) {
            if (timerRef.current) {
              clearInterval(timerRef.current);
              timerRef.current = null;
            }
            setBusy(false);
          }
        } catch {
          /* transient */
        }
      }, POLL_INTERVAL_MS);
    },
    [onChange],
  );

  useEffect(() => {
    if (article.status === "publishing" || article.running) {
      if (!timerRef.current) pollForPublish(article);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      pollDeadlineRef.current = null;
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [article, article.id, article.status, article.running, pollForPublish]);

  const handlePublish = useCallback(
    async (asDraft: boolean) => {
      setBusy(true);
      setError(null);
      try {
        await publishArticle(article.id, asDraft);
        const fresh = await getArticle(article.id);
        onChange(fresh);
        pollForPublish(fresh);
      } catch (e) {
        setBusy(false);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [article.id, onChange, pollForPublish],
  );

  const handleRetry = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await retryPublish(article.id);
      const fresh = await getArticle(article.id);
      onChange(fresh);
      pollForPublish(fresh);
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [article.id, onChange, pollForPublish]);

  const [scheduleDate, setScheduleDate] = useState("");

  const handleSchedule = useCallback(async () => {
    if (!scheduleDate) return;
    setBusy(true);
    setError(null);
    try {
      const runAt = new Date(scheduleDate).toISOString();
      await scheduleArticle(article.id, runAt);
      const fresh = await getArticle(article.id);
      onChange(fresh);
      setScheduleDate("");
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [article.id, onChange, scheduleDate]);

  const handleCancelSchedule = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await cancelSchedule(article.id);
      const fresh = await getArticle(article.id);
      onChange(fresh);
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [article.id, onChange]);

  const handleDelete = useCallback(async () => {
    if (!window.confirm("Delete this post from Blogger? This cannot be undone.")) return;
    setBusy(true);
    setError(null);
    try {
      await deletePublishedPost(article.id);
      const fresh = await getArticle(article.id);
      onChange(fresh);
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [article.id, onChange]);

  if (!PUBLISH_VISIBLE.has(article.status)) return null;

  const isPublishing = article.status === "publishing" || busy;
  const blogUrl = article.blogger_post_url;
  const blogPublished = article.blogger_published_at;

  return (
    <Card data-testid="publish-panel">
      <CardHeader className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">Publish</CardTitle>
          <div className="flex shrink-0 items-center gap-2">
            {isPublishing ? (
              <Badge variant="secondary" className="gap-1">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                Publishing…
              </Badge>
            ) : article.status === "published" ? (
              <Badge variant="default" className="gap-1 bg-emerald-600">
                Published
              </Badge>
            ) : null}
          </div>
        </div>
        <CardDescription>
          Publish this article to Blogger. Only approved articles can be published.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}

        {hasPublishError(article) ? <PublishErrorDetail article={article} /> : null}

        {blogUrl ? (
          <div className="space-y-1 text-sm">
            <a
              href={blogUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-600 hover:underline dark:text-blue-400"
            >
              <Globe className="h-3.5 w-3.5" aria-hidden="true" />
              View on Blogger
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
            {blogPublished ? (
              <p className="text-xs text-muted-foreground">
                Published {formatDate(blogPublished)}
              </p>
            ) : null}
          </div>
        ) : null}

        {article.status === "scheduled" ? (
          <div className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm dark:border-blue-800 dark:bg-blue-950">
            <div className="flex items-center gap-2">
              <CalendarClock className="h-4 w-4 text-blue-600 dark:text-blue-400" />
              <span>Scheduled for publishing</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="mt-2 gap-1"
              onClick={() => void handleCancelSchedule()}
              disabled={busy}
            >
              <X className="h-3.5 w-3.5" />
              Cancel schedule
            </Button>
          </div>
        ) : null}

        {article.status === "approved" ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                onClick={() => {
                  if (!window.confirm("Publish this article live to Blogger?")) return;
                  void handlePublish(false);
                }}
                disabled={isPublishing || !blogStatus?.connected}
              >
                <Globe className="h-4 w-4" aria-hidden="true" />
                Publish now
              </Button>
              <Button
                variant="outline"
                onClick={() => void handlePublish(true)}
                disabled={isPublishing || !blogStatus?.connected}
              >
                <Save className="h-4 w-4" aria-hidden="true" />
                Save as draft
              </Button>
              {blogStatus && !blogStatus.connected ? (
                <p className="text-xs text-muted-foreground">
                  Connect your Blogger account in Settings to publish.
                </p>
              ) : null}
            </div>
            <div className="flex items-center gap-2 border-t pt-3">
              <Input
                type="datetime-local"
                value={scheduleDate}
                onChange={(e) => setScheduleDate(e.target.value)}
                className="max-w-xs"
              />
              <Button
                variant="outline"
                onClick={() => void handleSchedule()}
                disabled={!scheduleDate || busy || !blogStatus?.connected}
              >
                <CalendarClock className="h-4 w-4" aria-hidden="true" />
                Schedule
              </Button>
            </div>
          </div>
        ) : article.status === "publish_failed" ? (
          <Button
            variant="outline"
            onClick={() => void handleRetry()}
            disabled={isPublishing || !blogStatus?.connected}
          >
            <RotateCw className="h-4 w-4" aria-hidden="true" />
            Retry publish
          </Button>
        ) : article.status === "published" && blogUrl ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              onClick={() => void handleRetry()}
              disabled={isPublishing || !blogStatus?.connected}
            >
              <RotateCw className="h-4 w-4" aria-hidden="true" />
              Update on Blogger
            </Button>
            <Button
              variant="outline"
              className="text-destructive hover:text-destructive"
              onClick={() => void handleDelete()}
              disabled={isPublishing}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              Delete from Blogger
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
