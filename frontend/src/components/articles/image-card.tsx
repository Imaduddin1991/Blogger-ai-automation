"use client";

import { useState } from "react";
import { CheckCircle2, ExternalLink, ImageOff, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { statusLabel, type ImageRecord } from "@/lib/api";
import { safeUrl } from "@/lib/markdown";
import { cn } from "@/lib/utils";

function formatRelevance(relevance: number): string {
  return `${Math.round((relevance ?? 0) * 100)}%`;
}

export function ImageThumb({
  image,
  className,
  large,
}: {
  image: ImageRecord;
  className?: string;
  large?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const src = safeUrl(image.thumb_url ?? image.url);
  const [loaded, setLoaded] = useState(false);

  if (!src || failed) {
    return (
      <div
        className={cn(
          "flex items-center justify-center bg-muted text-muted-foreground",
          className,
        )}
        role="img"
        aria-label={image.caption ?? image.alt ?? "Image unavailable"}
      >
        <ImageOff className={large ? "h-8 w-8" : "h-5 w-5"} aria-hidden="true" />
      </div>
    );
  }

  return (
    <div className={cn("relative overflow-hidden bg-muted", className)}>
      {!loaded ? (
        <div className="absolute inset-0 animate-pulse bg-muted" aria-hidden="true" />
      ) : null}
      <img
        src={src}
        alt={image.alt ?? image.caption ?? ""}
        loading="lazy"
        referrerPolicy="no-referrer"
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
        className={cn("h-full w-full object-cover", loaded ? "opacity-100" : "opacity-0")}
      />
    </div>
  );
}

type ImageCardProps = {
  image: ImageRecord;
  disabled?: boolean;
  onSelect?: () => void;
  onRemove?: () => void;
  onOpen?: () => void;
};

export function ImageCard({ image, disabled, onSelect, onRemove, onOpen }: ImageCardProps) {
  const [confirming, setConfirming] = useState(false);
  const isSelected = image.status === "selected";
  const isRejected = image.status === "rejected";
  const isBusy = disabled === true;

  const handleRemoveClick = () => {
    if (!confirming) {
      setConfirming(true);
      window.setTimeout(() => setConfirming(false), 3000);
      return;
    }
    setConfirming(false);
    onRemove?.();
  };

  return (
    <Card className="group relative overflow-hidden" data-status={image.status}>
      <button
        type="button"
        onClick={onOpen}
        aria-label={`View details for ${image.caption ?? image.alt ?? "image"}`}
        className="block w-full cursor-pointer text-left focus-visible:outline-none"
      >
        <ImageThumb image={image} className="aspect-video w-full" />
      </button>

      <div className="space-y-1.5 p-3">
        <div className="flex items-start justify-between gap-2">
          <p className="line-clamp-2 min-w-0 flex-1 text-sm font-medium">
            {image.caption ?? image.alt ?? "Untitled image"}
          </p>
          {isSelected ? (
            <CheckCircle2
              className="h-4 w-4 shrink-0 text-emerald-500"
              data-testid="selected-check"
              aria-label="Selected"
            />
          ) : null}
        </div>

        {image.author ? (
          <p className="truncate text-xs text-muted-foreground">
            {image.attribution ?? image.author}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-1">
          <Badge variant={isSelected ? "default" : "outline"} className="shrink-0">
            {statusLabel(image.status)}
          </Badge>
          {image.license ? (
            <Badge variant="outline" className="shrink-0" title={image.license}>
              {image.license.length > 24 ? `${image.license.slice(0, 22)}…` : image.license}
            </Badge>
          ) : null}
          {image.attribution_required ? (
            <Badge variant="secondary" className="shrink-0">
              attribution
            </Badge>
          ) : null}
          {image.relevance > 0 ? (
            <span className="ml-auto text-xs text-muted-foreground">
              {formatRelevance(image.relevance)}
            </span>
          ) : null}
        </div>

        {isRejected ? (
          <p className="text-xs text-destructive">
            {image.rejection_reason ?? "Rejected — cannot be selected."}
          </p>
        ) : null}

        <div className="flex items-center gap-1.5 pt-1">
          {!isRejected && !isSelected && onSelect ? (
            <Button size="sm" variant="outline" disabled={isBusy} onClick={onSelect}>
              Select
            </Button>
          ) : null}
          {onRemove ? (
            <Button
              size="sm"
              variant={confirming ? "destructive" : "ghost"}
              disabled={isBusy}
              onClick={handleRemoveClick}
              aria-label={confirming ? `Confirm removing ${image.caption ?? "this image"}` : undefined}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              {confirming ? "Remove?" : "Remove"}
            </Button>
          ) : null}
          {onOpen ? (
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto"
              onClick={onOpen}
              aria-label={`Open details for ${image.caption ?? "this image"}`}
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
