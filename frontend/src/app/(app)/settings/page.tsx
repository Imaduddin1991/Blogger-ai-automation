"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ExternalLink,
  LinkIcon,
  Loader2,
  Unlink,
} from "lucide-react";

import {
  getBloggerStatus,
  connectBlogger,
  disconnectBlogger,
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
import { PageHeader } from "@/components/layout/page-header";
import { Skeleton } from "@/components/ui/skeleton";

export default function SettingsPage() {
  const [blogStatus, setBlogStatus] = useState<BloggerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const status = await getBloggerStatus();
      setBlogStatus(status);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch; setState runs in a promise callback
    void loadStatus();
  }, [loadStatus]);

  const handleConnect = useCallback(async () => {
    setBusy(true);
    setActionError(null);
    try {
      const { auth_url } = await connectBlogger();
      window.open(auth_url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const handleDisconnect = useCallback(async () => {
    if (!window.confirm("Disconnect this Blogger account? You can reconnect later.")) return;
    setBusy(true);
    setActionError(null);
    try {
      const status = await disconnectBlogger();
      setBlogStatus(status);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const statusDot = blogStatus?.connected
    ? "bg-emerald-500"
    : blogStatus?.status === "token_expired"
      ? "bg-amber-500"
      : "bg-muted-foreground/40";

  const statusText = blogStatus?.connected
    ? "Connected"
    : blogStatus?.status === "token_expired"
      ? "Token expired"
      : "Disconnected";

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Ollama connection, Blogger account, and defaults." />

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle className="text-base">Blogger Account</CardTitle>
            {!loading ? (
              <Badge variant={blogStatus?.connected ? "default" : "outline"} className="gap-1">
                <span className={`inline-block h-2 w-2 rounded-full ${statusDot}`} aria-hidden="true" />
                {statusText}
              </Badge>
            ) : null}
          </div>
          <CardDescription>
            Connect your Google account to publish articles to Blogger.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {actionError ? (
            <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive" role="alert">
              {actionError}
            </p>
          ) : null}

          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-1/3" />
            </div>
          ) : blogStatus?.connected ? (
            <div className="space-y-3">
              <div className="text-sm">
                <p className="font-medium">{blogStatus.blog_name}</p>
                {blogStatus.blog_url ? (
                  <a
                    href={blogStatus.blog_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-blue-600 hover:underline dark:text-blue-400"
                  >
                    {blogStatus.blog_url}
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                ) : null}
              </div>
              <Button
                variant="outline"
                onClick={() => void handleDisconnect()}
                disabled={busy}
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Unlink className="h-4 w-4" aria-hidden="true" />
                )}
                Disconnect
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {error ? (
                <p className="text-sm text-muted-foreground">{error}</p>
              ) : null}
              <Button
                onClick={() => void handleConnect()}
                disabled={busy}
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <LinkIcon className="h-4 w-4" aria-hidden="true" />
                )}
                Connect Blogger
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Ollama</CardTitle>
          <CardDescription>
            Local AI model configuration. Default: qwen2.5:1.5b
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Ollama configuration will be available here in a future update.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
