"use client";

import { ExternalLink } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
import { formatDate, statusLabel, type ImageRecord } from "@/lib/api";
import { safeUrl } from "@/lib/markdown";
import { ImageThumb } from "@/components/articles/image-card";

function formatBytes(bytes: number | null): string | null {
  if (bytes === null || bytes === undefined || bytes <= 0) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MetadataRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 text-sm">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-right">{value}</dd>
    </div>
  );
}

export function ImageDetailSheet({
  image,
  open,
  onOpenChange,
}: {
  image: ImageRecord | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const pageUrl = safeUrl(image?.page_url);
  const licenseUrl = safeUrl(image?.license_url);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto" side="right">
        {image ? (
          <>
            <SheetHeader>
              <SheetTitle>{image.caption ?? image.alt ?? "Image details"}</SheetTitle>
              <SheetDescription>
                Status: {statusLabel(image.status)}
                {image.provider ? ` · Source: ${image.provider}` : ""}
              </SheetDescription>
            </SheetHeader>

            <ImageThumb image={image} large className="aspect-video w-full" />

            <div className="space-y-4 px-4 pb-4">
              {image.alt ? (
                <p className="text-sm text-muted-foreground">
                  <strong className="text-foreground">Alt text:</strong> {image.alt}
                </p>
              ) : null}

              {image.rejection_reason ? (
                <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                  <strong>Rejected:</strong> {image.rejection_reason}
                </p>
              ) : null}

              {image.attribution_required ? (
                <p className="rounded-md bg-secondary p-3 text-sm">
                  <strong>Attribution required</strong> — must credit the author when publishing.
                  This reminder is shown until you publish.
                </p>
              ) : null}

              <dl className="space-y-2">
                {image.author ? (
                  <MetadataRow
                    label="Author"
                    value={image.attribution ?? image.author}
                  />
                ) : null}
                {image.license ? (
                  <MetadataRow label="License" value={image.license} />
                ) : null}
                {image.usage_notes ? (
                  <MetadataRow label="Usage notes" value={image.usage_notes} />
                ) : null}
                {image.width && image.height ? (
                  <MetadataRow label="Size" value={`${image.width} × ${image.height} px`} />
                ) : null}
                {image.file_size ? (
                  <MetadataRow label="File size" value={formatBytes(image.file_size) ?? "—"} />
                ) : null}
                {image.mime ? <MetadataRow label="Format" value={image.mime} /> : null}
                {image.relevance ? (
                  <MetadataRow
                    label="Relevance"
                    value={`${Math.round(image.relevance * 100)}%`}
                  />
                ) : null}
                {image.retrieved_at ? (
                  <MetadataRow label="Retrieved" value={formatDate(image.retrieved_at)} />
                ) : null}
              </dl>

              <Separator />

              <div className="flex flex-col gap-2">
                {pageUrl ? (
                  <a
                    href={pageUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-sm text-primary underline-offset-4 hover:underline"
                  >
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    View source page
                  </a>
                ) : null}
                {licenseUrl ? (
                  <a
                    href={licenseUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-sm text-primary underline-offset-4 hover:underline"
                  >
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    Read license terms
                  </a>
                ) : null}
              </div>
            </div>
          </>
        ) : (
          <SheetHeader>
            <SheetTitle>Image details</SheetTitle>
          </SheetHeader>
        )}
      </SheetContent>
    </Sheet>
  );
}
