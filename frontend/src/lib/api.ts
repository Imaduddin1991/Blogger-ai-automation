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
    default:
      return status;
  }
}
