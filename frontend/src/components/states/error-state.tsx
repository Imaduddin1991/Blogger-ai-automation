"use client";

import { ServerOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type ErrorStateProps = {
  title?: string;
  description?: string;
  onRetry?: () => void;
};

export function ErrorState({
  title = "Something went wrong",
  description = "An unexpected error occurred while loading this page.",
  onRetry,
}: ErrorStateProps) {
  return (
    <Card className="border-destructive/40">
      <CardHeader className="items-center gap-2 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10">
          <ServerOff className="h-5 w-5 text-destructive" aria-hidden="true" />
        </div>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      {onRetry ? (
        <CardContent className="flex justify-center pb-6">
          <Button variant="outline" onClick={onRetry}>
            Try again
          </Button>
        </CardContent>
      ) : null}
    </Card>
  );
}
