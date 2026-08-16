export type Idea = {
  id: number;
  title: string;
  prompt: string | null;
  created_at: string;
  updated_at: string;
};

export type ResearchSource = {
  provider: string;
  title: string;
  url: string;
  snippet: string | null;
  relevance: number;
  license: string | null;
};

export type Research = {
  id: number;
  idea_id: number | null;
  topic: string | null;
  topic_key: string;
  summary_text: string | null;
  status: "researching" | "complete" | "error";
  coverage: number | null;
  providers_used: string[];
  provider_errors: Record<string, string> | null;
  sources: ResearchSource[];
  created_at: string;
  updated_at: string;
};

export type ResearchStart = {
  id: number;
  status: string;
  cached: boolean;
};

export type CheckResult = {
  id: number;
  check_type: "seo" | "quality" | "policy" | "repetition";
  passed: boolean;
  severity: "info" | "warning" | "error";
  message: string | null;
  details: Record<string, unknown> | null;
};

export type Article = {
  id: number;
  idea_id: number | null;
  blog_id: number | null;
  title: string;
  slug: string | null;
  seo_title: string | null;
  meta_description: string | null;
  labels: string[];
  word_count: number;
  status: string;
  generation_errors: Record<string, string> | null;
  review_approved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ArticleDetail = Article & {
  body: string | null;
  summary_text: string | null;
  idea_title: string | null;
  running: boolean;
  sources: ResearchSource[];
  check_results: CheckResult[];
};

export type ArticleStart = {
  id: number;
  status: string;
  cached: boolean;
};

export type ArticleUpdate = Partial<{
  title: string;
  body: string;
  seo_title: string;
  meta_description: string;
  labels: string[];
  slug: string | null;
}>;

export type Dashboard = {
  idea_count: number;
  research_count: number;
  article_count: number;
  publish_job_count: number;
};

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(String(detail), res.status);
  }
  return (await res.json()) as T;
}

export async function listIdeas(): Promise<Idea[]> {
  return request<Idea[]>("/ideas");
}

export async function createIdea(title: string, prompt?: string): Promise<Idea> {
  return request<Idea>("/ideas", {
    method: "POST",
    body: JSON.stringify({ title, prompt: prompt || null }),
  });
}

export async function startResearch(ideaId: number): Promise<ResearchStart> {
  return request<ResearchStart>(`/ideas/${ideaId}/research`, { method: "POST" });
}

export async function listResearch(): Promise<Research[]> {
  return request<Research[]>("/research");
}

export async function getResearch(id: number): Promise<Research> {
  return request<Research>(`/research/${id}`);
}

export async function getDashboard(): Promise<Dashboard> {
  return request<Dashboard>("/dashboard");
}

export async function listArticles(): Promise<Article[]> {
  return request<Article[]>("/articles");
}

export async function getArticle(id: number): Promise<ArticleDetail> {
  return request<ArticleDetail>(`/articles/${id}`);
}

export async function createArticleFromIdea(ideaId: number): Promise<ArticleStart> {
  return request<ArticleStart>(`/articles?idea_id=${ideaId}`, { method: "POST" });
}

export async function updateArticle(id: number, patch: ArticleUpdate): Promise<ArticleDetail> {
  return request<ArticleDetail>(`/articles/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function recheckArticle(id: number): Promise<ArticleDetail> {
  return request<ArticleDetail>(`/articles/${id}/recheck`, { method: "POST" });
}

export async function approveArticle(id: number): Promise<ArticleDetail> {
  return request<ArticleDetail>(`/articles/${id}/approve`, { method: "POST" });
}

export async function retryArticle(id: number): Promise<ArticleStart> {
  return request<ArticleStart>(`/articles/${id}/retry`, { method: "POST" });
}

export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatCoverage(coverage: number | null): string {
  return `${Math.round((coverage ?? 0) * 100)}%`;
}

export function statusLabel(status: string): string {
  switch (status) {
    case "researching":
      return "Researching…";
    case "complete":
      return "Complete";
    case "error":
      return "Error";
    case "researched":
      return "Researched";
    case "draft":
      return "Draft";
    case "drafting":
      return "Generating…";
    case "drafted":
      return "Drafted";
    case "seo_done":
      return "SEO done";
    case "checked":
      return "Checked";
    case "image_ready":
      return "Image ready";
    case "ready_for_review":
      return "Ready for review";
    case "approved":
      return "Approved";
    case "scheduled":
      return "Scheduled";
    case "publishing":
      return "Publishing…";
    case "published":
      return "Published";
    case "publish_failed":
      return "Publish failed";
    default:
      return status;
  }
}
