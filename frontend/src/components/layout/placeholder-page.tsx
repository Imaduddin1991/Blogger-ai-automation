import type { LucideIcon } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type PlaceholderPageProps = {
  title: string;
  description: string;
  icon: LucideIcon;
  emptyTitle: string;
  emptyDescription: string;
};

export function PlaceholderPage({
  title,
  description,
  icon: Icon,
  emptyTitle,
  emptyDescription,
}: PlaceholderPageProps) {
  return (
    <div className="space-y-6">
      <PageHeader title={title} description={description} />
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">Preview</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </CardContent>
      </Card>
      <EmptyState
        icon={Icon}
        title={emptyTitle}
        description={emptyDescription}
      />
    </div>
  );
}
