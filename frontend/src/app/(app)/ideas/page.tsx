import type { Metadata } from "next";

import { IdeasView } from "@/components/ideas/ideas-view";

export const metadata: Metadata = {
  title: "Ideas",
  description: "Your blog ideas.",
};

export default function IdeasPage() {
  return <IdeasView />;
}
