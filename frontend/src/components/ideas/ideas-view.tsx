"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Lightbulb, Loader2, Plus, Search } from "lucide-react";

import {
  createArticleFromIdea,
  createIdea,
  getResearch,
  listIdeas,
  startResearch,
  statusLabel,
  type Idea,
  type Research,
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
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";

function IdeaCard({ idea }: { idea: Idea & { research?: Research } }) {
  const research = idea.research;
  const router = useRouter();
  const [researching, setResearching] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  const handleResearch = useCallback(async () => {
    setResearching(true);
    try {
      const start = await startResearch(idea.id);
      const r = await getResearch(start.id);
      idea.research = r;
    } finally {
      setResearching(false);
    }
    // refresh list so statuses update
    window.dispatchEvent(new Event("ideas-changed"));
  }, [idea]);

  const handleDraft = useCallback(async () => {
    setDrafting(true);
    setDraftError(null);
    try {
      await createArticleFromIdea(idea.id);
      router.push("/articles");
    } catch (e) {
      setDraftError(e instanceof Error ? e.message : String(e));
      setDrafting(false);
    }
  }, [idea.id, router]);

  const researchComplete = research?.status === "complete";

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="space-y-1">
          <CardTitle className="text-base">{idea.title}</CardTitle>
          {idea.prompt ? (
            <CardDescription className="line-clamp-2">{idea.prompt}</CardDescription>
          ) : null}
        </div>
        {research ? (
          <Badge variant={research.status === "complete" ? "default" : "secondary"}>
            {statusLabel(research.status)}
          </Badge>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-2">
        {draftError ? <p className="text-xs text-destructive">{draftError}</p> : null}
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">{idea.created_at}</p>
          <div className="flex items-center gap-2">
            {researchComplete ? (
              <Button size="sm" onClick={() => void handleDraft()} disabled={drafting}>
                {drafting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileText className="h-4 w-4" />
                )}
                Draft article
              </Button>
            ) : null}
            <Button size="sm" onClick={handleResearch} disabled={researching || research?.status === "researching"}>
              {researching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {research ? "Re-research" : "Research"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function IdeasView() {
  const [ideas, setIdeas] = useState<(Idea & { research?: Research })[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listIdeas();
      setIdeas((prev) => {
        const byId = new Map(prev.map((p) => [p.id, p]));
        return data.map((idea) => {
          const existing = byId.get(idea.id);
          return existing?.research ? { ...idea, research: existing.research } : idea;
        });
      });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const pollResearchStatuses = useCallback(async () => {
    const started = ideas.filter((i) => i.research?.status === "researching");
    if (started.length === 0) return;
    for (const idea of started) {
      const r = await getResearch(idea.research!.id);
      idea.research = r;
    }
    setIdeas([...ideas]);
    if (ideas.some((i) => i.research?.status === "researching")) return;
    if (timerRef.current) clearInterval(timerRef.current);
  }, [ideas]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch; setState runs in a promise callback
    void refresh();
    const onChange = () => void refresh();
    window.addEventListener("ideas-changed", onChange);
    return () => {
      window.removeEventListener("ideas-changed", onChange);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [refresh]);

  useEffect(() => {
    if (ideas.some((i) => i.research?.status === "researching")) {
      if (!timerRef.current) {
        timerRef.current = setInterval(() => void pollResearchStatuses(), 2000);
      }
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, [ideas, pollResearchStatuses]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = title.trim();
      if (!trimmed || submitting) return;
      setSubmitting(true);
      try {
        await createIdea(trimmed, prompt.trim() || undefined);
        setTitle("");
        setPrompt("");
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSubmitting(false);
      }
    },
    [title, prompt, submitting, refresh],
  );

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">New idea</CardTitle>
          <CardDescription>
            Enter a blog topic to start the research pipeline.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="idea-title">Topic</Label>
              <Input
                id="idea-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Why solar panels work"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="idea-prompt">
                Notes <span className="text-muted-foreground">(optional)</span>
              </Label>
              <textarea
                id="idea-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Angle, audience, or extra instructions for research…"
                rows={3}
                className="flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </div>
            <Button type="submit" disabled={submitting || !title.trim()}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Add idea
            </Button>
          </form>
        </CardContent>
      </Card>

      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState description={error} onRetry={() => void refresh()} />
      ) : ideas.length === 0 ? (
        <EmptyState
          icon={Lightbulb}
          title="No ideas yet"
          description="Add your first blog idea above — it will start the research pipeline."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {ideas.map((idea) => (
            <IdeaCard key={idea.id} idea={idea} />
          ))}
        </div>
      )}
    </div>
  );
}
