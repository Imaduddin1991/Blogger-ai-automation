"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Info,
  Loader2,
  RotateCw,
  Save,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import {
  getArticle,
  listArticles,
  recheckArticle,
  retryArticle,
  approveArticle,
  statusLabel,
  updateArticle,
  type Article,
  type ArticleDetail,
  type CheckResult,
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
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { renderMarkdown } from "@/lib/markdown";
import { ArticleImagesPanel } from "@/components/articles/article-images-panel";
import { ArticlePublishPanel } from "@/components/articles/article-publish-panel";

const RETRYABLE = new Set(["draft", "drafting"]);

function StatusBadge({ article }: { article: Article }) {
  const running =
    article.status === "drafting" ||
    article.status === "researching" ||
    article.status === "images_searching";
  const variant =
    article.status === "published"
      ? "default"
      : article.status === "checked"
        ? "default"
        : article.status === "drafted" || article.status === "seo_done"
          ? "secondary"
          : article.status === "publish_failed"
            ? "destructive"
            : article.status === "publishing"
              ? "secondary"
              : "outline";
  return (
    <Badge
      variant={variant}
      className={`shrink-0 ${article.status === "published" ? "bg-emerald-600" : ""}`}
    >
      {running ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
      {statusLabel(article.status)}
    </Badge>
  );
}

function SeverityIcon({ check }: { check: CheckResult }) {
  if (check.passed) {
    return <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden="true" />;
  }
  if (check.severity === "error") {
    return <XCircle className="h-4 w-4 text-destructive" aria-hidden="true" />;
  }
  if (check.severity === "warning") {
    return <AlertTriangle className="h-4 w-4 text-amber-500" aria-hidden="true" />;
  }
  return <Info className="h-4 w-4 text-muted-foreground" aria-hidden="true" />;
}

function CheckRow({ check }: { check: CheckResult }) {
  return (
    <li className="flex items-start gap-2 py-1.5">
      <SeverityIcon check={check} />
      <div className="min-w-0 text-sm">
        <p className={check.passed ? "text-foreground" : "text-foreground"}>{check.message}</p>
        {Object.keys(check.details ?? {}).length > 0 ? (
          <p className="text-xs text-muted-foreground">{JSON.stringify(check.details)}</p>
        ) : null}
      </div>
    </li>
  );
}

function CheckPanel({ checks }: { checks: CheckResult[] }) {
  const groups = new Map<string, CheckResult[]>();
  for (const check of checks) {
    const group = groups.get(check.check_type) ?? [];
    group.push(check);
    groups.set(check.check_type, group);
  }
  if (groups.size === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No checks have run yet. Generate the article or run a recheck to see results.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {[...groups.entries()].map(([type, rows]) => {
        const failed = rows.filter((r) => !r.passed).length;
        return (
          <div key={type}>
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-sm font-medium capitalize">{type}</h3>
              <Badge variant={failed === 0 ? "outline" : "destructive"} className="shrink-0">
                {failed === 0 ? "Pass" : `${failed} to review`}
              </Badge>
            </div>
            <ul className="divide-y divide-border/60">
              {rows.map((check) => (
                <CheckRow key={check.id} check={check} />
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

type ArticleForm = {
  title: string;
  body: string;
  seo_title: string;
  meta_description: string;
  labels: string;
  slug: string;
};

function formFrom(article: ArticleDetail): ArticleForm {
  return {
    title: article.title,
    body: article.body ?? "",
    seo_title: article.seo_title ?? "",
    meta_description: article.meta_description ?? "",
    labels: (article.labels ?? []).join(", "),
    slug: article.slug ?? "",
  };
}

function ArticleDetailCard({
  article,
  onChange,
  onMessage,
}: {
  article: ArticleDetail;
  onChange: (updated: ArticleDetail) => void;
  onMessage: (message: string) => void;
}) {
  const [form, setForm] = useState<ArticleForm>(() => formFrom(article));
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [imagesBusy, setImagesBusy] = useState(false);
  const [bodyMode, setBodyMode] = useState<"edit" | "preview">("edit");
  const [prevId, setPrevId] = useState(article.id);
  const [prevStatus, setPrevStatus] = useState(article.status);

  if (prevId !== article.id || (prevStatus !== article.status && !article.running)) {
    setPrevId(article.id);
    setPrevStatus(article.status);
    setForm(formFrom(article));
  }

  const canRetry = RETRYABLE.has(article.status);
  const canRecheck = Boolean(article.body) && !article.running;

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const labels = form.labels
        .split(",")
        .map((l) => l.trim().toLowerCase())
        .filter(Boolean);
      const updated = await updateArticle(article.id, {
        title: form.title.trim() || article.title,
        body: form.body,
        seo_title: form.seo_title.trim(),
        meta_description: form.meta_description.trim(),
        labels,
        slug: form.slug.trim() || null,
      });
      onChange(updated);
      onMessage("Changes saved.");
    } catch (e) {
      onMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [article.id, article.title, form, onChange, onMessage]);

  const handleRecheck = useCallback(async () => {
    setBusy(true);
    try {
      const updated = await recheckArticle(article.id);
      onChange(updated);
      onMessage("Recheck queued — results will refresh shortly.");
    } catch (e) {
      onMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [article.id, onChange, onMessage]);

  const handleRetry = useCallback(async () => {
    setBusy(true);
    try {
      await retryArticle(article.id);
      onChange(await getArticle(article.id));
      onMessage("Generation queued again.");
    } catch (e) {
      onMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [article.id, onChange, onMessage]);

  const handleApprove = useCallback(async () => {
    setBusy(true);
    try {
      const updated = await approveArticle(article.id);
      onChange(updated);
      onMessage(
        updated.status === "approved"
          ? "Article approved — ready to schedule publishing in a later phase."
          : "Marked ready for review. Click Approve again to finalize.",
      );
    } catch (e) {
      onMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [article.id, onChange, onMessage]);

  const errors = article.generation_errors ?? null;
  const canApprove =
    (article.status === "checked" || article.status === "ready_for_review") &&
    !article.running &&
    !imagesBusy;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-lg">{article.title}</CardTitle>
            <div className="flex shrink-0 items-center gap-2">
              <StatusBadge article={article} />
            </div>
          </div>
          <CardDescription>
            {article.word_count > 0 ? `${article.word_count} words · ` : ""}
            {article.idea_title ? `from "${article.idea_title}" · ` : ""}
            updated {new Date(article.updated_at).toLocaleString()}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {errors ? (
            <div className="space-y-1 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {Object.entries(errors).map(([stage, message]) => (
                <p key={stage}>
                  <span className="font-medium capitalize">{stage}:</span> {message}
                </p>
              ))}
            </div>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="article-title">Title</Label>
            <Input
              id="article-title"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="article-body">Body (Markdown)</Label>
              <div className="flex items-center gap-1 rounded-md border border-input p-0.5">
                <button
                  type="button"
                  onClick={() => setBodyMode("edit")}
                  className={`rounded px-2 py-0.5 text-xs transition-colors ${
                    bodyMode === "edit"
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => setBodyMode("preview")}
                  className={`rounded px-2 py-0.5 text-xs transition-colors ${
                    bodyMode === "preview"
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  Preview
                </button>
              </div>
            </div>
            {bodyMode === "edit" ? (
              <textarea
                id="article-body"
                value={form.body}
                onChange={(e) => setForm({ ...form, body: e.target.value })}
                rows={14}
                className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs leading-relaxed shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            ) : (
              <div
                className="markdown-preview max-w-none rounded-md border border-input px-4 py-3"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(form.body || "") }}
              />
            )}
          </div>

          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              Editing content resets SEO + checks; run <strong>Recheck</strong> afterwards.
            </p>
            <Button onClick={() => void handleSave()} disabled={saving || article.running}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save
            </Button>
          </div>

          <Separator />

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="seo-title">SEO title</Label>
              <Input
                id="seo-title"
                value={form.seo_title}
                onChange={(e) => setForm({ ...form, seo_title: e.target.value })}
                maxLength={60}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="article-slug">Slug</Label>
              <Input
                id="article-slug"
                value={form.slug}
                onChange={(e) => setForm({ ...form, slug: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="article-labels">Labels (comma-separated)</Label>
              <Input
                id="article-labels"
                value={form.labels}
                onChange={(e) => setForm({ ...form, labels: e.target.value })}
              />
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="meta-description">Meta description</Label>
              <textarea
                id="meta-description"
                value={form.meta_description}
                onChange={(e) => setForm({ ...form, meta_description: e.target.value })}
                rows={3}
                maxLength={160}
                className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              onClick={() => void handleRecheck()}
              disabled={!canRecheck || busy || saving}
            >
              <RotateCw className="h-4 w-4" />
              Recheck
            </Button>
            <Button
              variant="outline"
              onClick={() => void handleRetry()}
              disabled={!canRetry || busy || saving}
            >
              <RotateCw className="h-4 w-4" />
              Retry generation
            </Button>
            <Button
              variant="default"
              onClick={() => void handleApprove()}
              disabled={!canApprove || busy || saving}
            >
              <ShieldCheck className="h-4 w-4" />
              {article.status === "ready_for_review" ? "Approve article" : "Mark ready for review"}
            </Button>
            {article.review_approved_at ? (
              <span className="text-xs text-muted-foreground">
                Approved {new Date(article.review_approved_at).toLocaleString()}
              </span>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Checks</CardTitle>
          <CardDescription>
            Advisory checks for SEO, quality, publisher-policy risk, and repetition. Not a
            guarantee of ranking, indexing, or approval.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <CheckPanel checks={article.check_results} />
        </CardContent>
      </Card>

      <ArticleImagesPanel
        articleId={article.id}
        articleStatus={article.status}
        onRunningChange={setImagesBusy}
      />

      <ArticlePublishPanel article={article} onChange={onChange} />
    </div>
  );
}

export function ArticlesView() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [selected, setSelected] = useState<ArticleDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadList = useCallback(async () => {
    try {
      const data = await listArticles();
      setArticles(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const selectArticle = useCallback(async (id: number) => {
    try {
      const detail = await getArticle(id);
      setSelected(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch; setState runs in a promise callback
    void loadList();
  }, [loadList]);

  useEffect(() => {
    const running = selected?.running ?? false;
    if (!running) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    if (!timerRef.current) {
      timerRef.current = setInterval(() => {
        if (selected) {
          getArticle(selected.id)
            .then((fresh) => {
              setSelected(fresh);
              setArticles((prev) =>
                prev.map((a) => (a.id === fresh.id ? fresh : a)),
              );
            })
            .catch(() => {
              /* transient; next tick retries */
            });
        }
      }, 2000);
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [selected]);

  const handleChange = useCallback((updated: ArticleDetail) => {
    setSelected(updated);
    setArticles((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
  }, []);

  return (
    <div className="space-y-6">
      {message ? (
        <p className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">{message}</p>
      ) : null}
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState description={error} onRetry={() => void loadList()} />
      ) : articles.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No articles yet"
          description="Create an idea, let research finish, then click “Draft article” on the Ideas page."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="text-base">Articles</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              {articles.map((article) => (
                <button
                  key={article.id}
                  type="button"
                  onClick={() => void selectArticle(article.id)}
                  className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                    selected?.id === article.id
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                  }`}
                >
                  <span className="truncate">{article.title}</span>
                  <StatusBadge article={article} />
                </button>
              ))}
            </CardContent>
          </Card>

          {selected ? (
            <ArticleDetailCard article={selected} onChange={handleChange} onMessage={setMessage} />
          ) : (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                Select an article to review, edit, and check it.
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
