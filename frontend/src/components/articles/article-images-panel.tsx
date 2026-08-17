"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Images, Loader2, RotateCw, Search } from "lucide-react";

import {
  ApiError,
  getArticleImages,
  removeArticleImage,
  retryArticleImages,
  searchArticleImages,
  selectArticleImage,
  type ArticleImages,
  type ImageRecord,
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
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { ImageCard } from "@/components/articles/image-card";
import { ImageDetailSheet } from "@/components/articles/image-detail-sheet";

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_MS = 120_000;

// Article statuses from which images can be searched (backend-authoritative).
const SEARCHABLE = new Set(["checked", "image_ready"]);
// Statuses where images (once searched) are visible to the reviewer.
const IMAGE_VISIBLE = new Set(["image_ready", "ready_for_review", "approved"]);

function imageSort(a: ImageRecord, b: ImageRecord): number {
  if (a.position !== b.position) return a.position - b.position;
  return b.relevance - a.relevance;
}

export function ArticleImagesPanel({
  articleId,
  articleStatus,
  onRunningChange,
}: {
  articleId: number;
  articleStatus: string;
  onRunningChange?: (running: boolean) => void;
}) {
  const [data, setData] = useState<ArticleImages | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingSearch, setPendingSearch] = useState(false);
  const [detailImage, setDetailImage] = useState<ImageRecord | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const pollDeadlineRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const latestDataRef = useRef<ArticleImages | null>(null);

  const load = useCallback(
    async (showSpinner: boolean) => {
      if (showSpinner) setLoading(true);
      try {
        const fresh = await getArticleImages(articleId);
        latestDataRef.current = fresh;
        setData(fresh);
        setError(null);
        return fresh;
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        setError(message);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [articleId],
  );

  // Refresh silently while a search (or any pipeline job) is running, bounded
  // to ~120s. Distinguish "searching" ONLY from the article status, never from
  // the generic running flag, so a concurrent non-image job cannot paint the
  // panel as searching.
  useEffect(() => {
    const searching =
      data?.status === "images_searching" ||
      (pendingSearch && data?.status === "checked");
    if (!searching && !data?.running) return;

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
        setPendingSearch(false);
        return;
      }
      const fresh = await load(false);
      if (fresh && fresh.status !== "checked" && fresh.status !== "images_searching" && !fresh.running) {
        setPendingSearch(false);
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
      }
    }, POLL_INTERVAL_MS);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [data, pendingSearch, load]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch; setState runs in a promise callback
    void load(true);
  }, [articleId, load]);

  const resetPoll = () => {
    pollDeadlineRef.current = null;
  };

  const handleSearch = useCallback(
    async (retry: boolean) => {
      setBusy(true);
      setActionError(null);
      setPendingSearch(true);
      pollDeadlineRef.current = Date.now() + POLL_MAX_MS;
      try {
        const fresh = retry
          ? await retryArticleImages(articleId)
          : await searchArticleImages(articleId);
        latestDataRef.current = fresh;
        setData(fresh);
        setError(null);
      } catch (e) {
        setPendingSearch(false);
        if (e instanceof ApiError) {
          setActionError(e.message);
          if (e.status === 409) {
            await load(true);
          }
        } else {
          setActionError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setBusy(false);
      }
    },
    [articleId, load],
  );

  const handleSelect = useCallback(
    async (image: ImageRecord) => {
      setBusy(true);
      setActionError(null);
      try {
        const fresh = await selectArticleImage(articleId, image.id);
        latestDataRef.current = fresh;
        setData(fresh);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          setActionError(e.message);
          await load(true);
        } else {
          setActionError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setBusy(false);
      }
    },
    [articleId, load],
  );

  const handleRemove = useCallback(
    async (image: ImageRecord) => {
      setBusy(true);
      setActionError(null);
      try {
        const fresh = await removeArticleImage(articleId, image.id);
        latestDataRef.current = fresh;
        setData(fresh);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          setActionError(e.message);
          await load(true);
        } else {
          setActionError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setBusy(false);
      }
    },
    [articleId, load],
  );

  const openDetail = (image: ImageRecord) => {
    setDetailImage(image);
    setDetailOpen(true);
  };

  const status = data?.status ?? articleStatus;
  const searching = status === "images_searching" || (pendingSearch && status === "checked");
  const running = data?.running === true || busy;
  const canSearch = SEARCHABLE.has(status) && !searching && !running;

  useEffect(() => {
    onRunningChange?.(searching || running);
    return () => onRunningChange?.(false);
  }, [searching, running, onRunningChange]);

  if (loading && !data) {
    return (
      <Card aria-busy="true" aria-label="Loading images">
        <CardHeader>
          <CardTitle className="text-base">Images</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (error && !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Images</CardTitle>
        </CardHeader>
        <CardContent>
          <ErrorState
            description={error}
            onRetry={() => {
              resetPoll();
              void load(true);
            }}
          />
        </CardContent>
      </Card>
    );
  }

  const images = [...(data?.images ?? [])].sort(imageSort);

  return (
    <Card data-testid="images-panel">
      <CardHeader className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">Images</CardTitle>
          <div className="flex shrink-0 items-center gap-2">
            {running ? (
              <Badge variant="secondary" className="gap-1">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                {searching ? "Searching…" : "Busy…"}
              </Badge>
            ) : null}
          </div>
        </div>
        <CardDescription>
          Suggested images from Wikimedia Commons. Selecting an image never approves the article;
          you still approve it below.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {actionError ? (
          <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive" role="alert">
            {actionError}
          </p>
        ) : null}

        {searching ? (
          <div className="space-y-3" aria-busy="true">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="space-y-2">
                  <Skeleton className="aspect-video w-full" />
                  <Skeleton className="h-4 w-2/3" />
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Fetching candidates from Wikimedia Commons. This can take a minute or two.
            </p>
          </div>
        ) : status === "checked" && images.length === 0 ? (
          <EmptyState
            icon={Images}
            title="No image suggestions yet"
            description="Run a Commons search to fetch candidate images. Searching is optional — you can review and approve without images."
            action={
              <Button disabled={!canSearch || busy} onClick={() => void handleSearch(false)}>
                <Search className="h-4 w-4" aria-hidden="true" />
                Search images
              </Button>
            }
          />
        ) : status === "checked" ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                disabled={!canSearch || busy}
                onClick={() => void handleSearch(false)}
              >
                <RotateCw className="h-4 w-4" aria-hidden="true" />
                Re-search
              </Button>
              <p className="text-xs text-muted-foreground">
                Article is checked. Images from a previous search are still listed below.
              </p>
            </div>
            <ImageGridList
              images={images}
              busy={busy}
              running={running}
              onSelect={(img) => void handleSelect(img)}
              onRemove={(img) => void handleRemove(img)}
              onOpen={openDetail}
            />
          </div>
        ) : status === "image_ready" && images.length === 0 ? (
          <EmptyState
            icon={Images}
            title="No usable images found"
            description="The search returned no usable candidates (or all were removed). You can retry, or approve the article without images."
            action={
              <Button disabled={!canSearch || busy} onClick={() => void handleSearch(true)}>
                <RotateCw className="h-4 w-4" aria-hidden="true" />
                Retry search
              </Button>
            }
          />
        ) : IMAGE_VISIBLE.has(status) || images.length > 0 ? (
          <div className="space-y-3">
            {status === "image_ready" ? (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  disabled={!canSearch || busy}
                  onClick={() => void handleSearch(false)}
                >
                  <RotateCw className="h-4 w-4" aria-hidden="true" />
                  Re-search
                </Button>
              </div>
            ) : null}
            <ImageGridList
              images={images}
              busy={busy}
              running={running}
              onSelect={(img) => void handleSelect(img)}
              onRemove={(img) => void handleRemove(img)}
              onOpen={openDetail}
            />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Images are suggested after the article passes checks. Generate and check the article
            first, then run a Commons search here.
          </p>
        )}

        <ImageDetailSheet
          image={detailImage}
          open={detailOpen}
          onOpenChange={setDetailOpen}
        />
      </CardContent>
    </Card>
  );
}

function ImageGridList({
  images,
  busy,
  running,
  onSelect,
  onRemove,
  onOpen,
}: {
  images: ImageRecord[];
  busy: boolean;
  running: boolean;
  onSelect: (image: ImageRecord) => void;
  onRemove: (image: ImageRecord) => void;
  onOpen: (image: ImageRecord) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {images.map((image) => (
        <ImageCard
          key={image.id}
          image={image}
          disabled={busy || running}
          onSelect={image.status !== "rejected" ? () => onSelect(image) : undefined}
          onRemove={() => onRemove(image)}
          onOpen={() => onOpen(image)}
        />
      ))}
    </div>
  );
}
