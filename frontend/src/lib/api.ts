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
  blogger_post_id: string | null;
  blogger_post_url: string | null;
  blogger_published_at: string | null;
  blogger_status: string | null;
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
  publish_success_count: number;
  publish_fail_count: number;
  scheduled_count: number;
};

export type ImageRecord = {
  id: number;
  article_id: number | null;
  provider: string;
  url: string;
  alt: string | null;
  caption: string | null;
  attribution: string | null;
  license: string | null;
  position: number;
  status: string;
  page_url: string | null;
  author: string | null;
  license_url: string | null;
  attribution_required: boolean;
  usage_notes: string | null;
  thumb_url: string | null;
  mime: string | null;
  width: number | null;
  height: number | null;
  file_size: number | null;
  relevance: number;
  retrieved_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type ArticleImages = {
  article_id: number;
  status: string;
  running: boolean;
  images: ImageRecord[];
};

export type PublishRead = {
  id: number;
  status: string;
  blogger_post_url: string | null;
  blogger_published_at: string | null;
};

export type BloggerStatus = {
  connected: boolean;
  blog_id: string | null;
  blog_url: string | null;
  blog_name: string | null;
  status: string;
  token_expires_at: string | null;
};

export type BloggerConnect = {
  auth_url: string;
};

export class ApiError extends Error {
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

export async function getArticleImages(articleId: number): Promise<ArticleImages> {
  return request<ArticleImages>(`/articles/${articleId}/images`);
}

export async function searchArticleImages(articleId: number): Promise<ArticleImages> {
  return request<ArticleImages>(`/articles/${articleId}/images/search`, { method: "POST" });
}

export async function retryArticleImages(articleId: number): Promise<ArticleImages> {
  return request<ArticleImages>(`/articles/${articleId}/images/retry`, { method: "POST" });
}

export async function selectArticleImage(
  articleId: number,
  imageId: number,
): Promise<ArticleImages> {
  return request<ArticleImages>(`/articles/${articleId}/images/${imageId}/select`, {
    method: "POST",
  });
}

export async function removeArticleImage(
  articleId: number,
  imageId: number,
): Promise<ArticleImages> {
  return request<ArticleImages>(`/articles/${articleId}/images/${imageId}`, { method: "DELETE" });
}

export async function publishArticle(
  articleId: number,
  asDraft: boolean = false,
): Promise<PublishRead> {
  return request<PublishRead>(`/articles/${articleId}/publish`, {
    method: "POST",
    body: JSON.stringify({ as_draft: asDraft }),
  });
}

export async function retryPublish(articleId: number): Promise<PublishRead> {
  return request<PublishRead>(`/articles/${articleId}/publish/retry`, {
    method: "POST",
  });
}

export async function deletePublishedPost(
  articleId: number,
): Promise<{ ok: boolean; article_id: number; status: string }> {
  return request(`/articles/${articleId}/publish`, { method: "DELETE" });
}

export async function getBloggerStatus(): Promise<BloggerStatus> {
  return request<BloggerStatus>("/blogger/status");
}

export async function connectBlogger(): Promise<BloggerConnect> {
  return request<BloggerConnect>("/blogger/connect", { method: "POST" });
}

export async function disconnectBlogger(): Promise<BloggerStatus> {
  return request<BloggerStatus>("/blogger/disconnect", { method: "POST" });
}

export async function refreshBlogger(): Promise<BloggerStatus> {
  return request<BloggerStatus>("/blogger/refresh", { method: "POST" });
}

// --- Publish log (Phase 6A) ------------------------------------------------

export type PublishLogEntry = {
  id: number;
  article_id: number | null;
  article_title: string | null;
  action: string;
  result: string;
  details: Record<string, unknown> | null;
  blogger_post_url: string | null;
  created_at: string;
};

export type PublishJobEntry = {
  id: number;
  article_id: number | null;
  article_title: string | null;
  run_at: string;
  status: string;
  error: string | null;
  retry_count: number;
  published_at: string | null;
  blogger_post_id: string | null;
};

export async function listPublishLog(): Promise<PublishLogEntry[]> {
  return request<PublishLogEntry[]>("/publish-log");
}

export async function getArticlePublishLog(articleId: number): Promise<PublishLogEntry[]> {
  return request<PublishLogEntry[]>(`/publish-log/article/${articleId}`);
}

export async function listPublishJobs(): Promise<PublishJobEntry[]> {
  return request<PublishJobEntry[]>("/publish-log/jobs");
}

// --- Schedule (Phase 6B) ------------------------------------------------

export type ScheduledArticle = {
  article_id: number;
  article_title: string | null;
  run_at: string;
  status: string;
  job_id: number;
};

export async function scheduleArticle(articleId: number, runAt: string): Promise<ScheduledArticle> {
  return request<ScheduledArticle>(`/articles/${articleId}/schedule`, {
    method: "POST",
    body: JSON.stringify({ run_at: runAt }),
  });
}

export async function cancelSchedule(articleId: number): Promise<{ ok: boolean; article_id: number }> {
  return request(`/articles/${articleId}/schedule`, { method: "DELETE" });
}

export async function listScheduled(): Promise<ScheduledArticle[]> {
  return request<ScheduledArticle[]>("/scheduled");
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
    case "images_searching":
      return "Searching for images…";
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
    case "candidate":
      return "Candidate";
    case "suggested":
      return "Suggested";
    case "selected":
      return "Selected";
    case "rejected":
      return "Rejected";
    default:
      return status;
  }
}
