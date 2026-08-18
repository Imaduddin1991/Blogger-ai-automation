import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ArticlePublishPanel } from "@/components/articles/article-publish-panel";
import type { ArticleDetail, BloggerStatus } from "@/lib/api";

const api = vi.hoisted(() => ({
  getArticle: vi.fn(),
  publishArticle: vi.fn(),
  retryPublish: vi.fn(),
  getBloggerStatus: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getArticle: api.getArticle,
  publishArticle: api.publishArticle,
  retryPublish: api.retryPublish,
  getBloggerStatus: api.getBloggerStatus,
  formatDate: (s: string) => s,
}));

function makeArticle(overrides: Partial<ArticleDetail> = {}): ArticleDetail {
  return {
    id: 1,
    idea_id: 1,
    blog_id: null,
    title: "Test Article",
    slug: "test-article",
    seo_title: "Test",
    meta_description: "Test",
    labels: [],
    word_count: 500,
    status: "approved",
    generation_errors: null,
    review_approved_at: null,
    created_at: "2026-08-14T12:00:00Z",
    updated_at: "2026-08-14T12:00:00Z",
    body: "Body",
    summary_text: null,
    idea_title: "Test Idea",
    running: false,
    sources: [],
    check_results: [],
    blogger_post_id: null,
    blogger_post_url: null,
    blogger_published_at: null,
    blogger_status: null,
    ...overrides,
  };
}

function makeBlogStatus(overrides: Partial<BloggerStatus> = {}): BloggerStatus {
  return {
    connected: true,
    blog_id: "123",
    blog_url: "https://myblog.blogspot.com",
    blog_name: "My Blog",
    status: "connected",
    token_expires_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getBloggerStatus.mockResolvedValue(makeBlogStatus());
  api.getArticle.mockImplementation(async (id: number) => makeArticle({ id }));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ArticlePublishPanel rendering", () => {
  it("renders nothing for draft status", () => {
    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "draft" })}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("publish-panel")).not.toBeInTheDocument();
  });

  it("renders nothing for checked status", () => {
    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "checked" })}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("publish-panel")).not.toBeInTheDocument();
  });

  it("renders for approved status", async () => {
    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "approved" })}
        onChange={vi.fn()}
      />,
    );
    expect(await screen.findByTestId("publish-panel")).toBeInTheDocument();
    expect(screen.getByText("Publish now")).toBeInTheDocument();
    expect(screen.getByText("Save as draft")).toBeInTheDocument();
  });

  it("shows blogger URL when published", async () => {
    render(
      <ArticlePublishPanel
        article={makeArticle({
          status: "published",
          blogger_post_url: "https://myblog.blogspot.com/2026/08/test.html",
        })}
        onChange={vi.fn()}
      />,
    );
    expect(await screen.findByText("View on Blogger")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View on Blogger/ })).toHaveAttribute(
      "href",
      "https://myblog.blogspot.com/2026/08/test.html",
    );
  });

  it("shows update button for published articles", async () => {
    render(
      <ArticlePublishPanel
        article={makeArticle({
          status: "published",
          blogger_post_url: "https://myblog.blogspot.com/2026/08/test.html",
        })}
        onChange={vi.fn()}
      />,
    );
    expect(await screen.findByText("Update on Blogger")).toBeInTheDocument();
  });

  it("shows retry button for publish_failed articles", async () => {
    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "publish_failed" })}
        onChange={vi.fn()}
      />,
    );
    expect(await screen.findByText("Retry publish")).toBeInTheDocument();
  });

  it("shows error message for publish_failed with error detail", async () => {
    render(
      <ArticlePublishPanel
        article={makeArticle({
          status: "publish_failed",
          generation_errors: { publish: "Token expired, re-authenticate" },
        })}
        onChange={vi.fn()}
      />,
    );
    expect(await screen.findByText("Token expired, re-authenticate")).toBeInTheDocument();
  });

  it("shows publishing badge when status is publishing", async () => {
    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "publishing", running: true })}
        onChange={vi.fn()}
      />,
    );
    expect(await screen.findByText("Publishing…")).toBeInTheDocument();
  });
});

describe("ArticlePublishPanel actions", () => {
  it("calls publishArticle with as_draft=false on Publish now", async () => {
    api.publishArticle.mockResolvedValue({ id: 1, status: "publishing", blogger_post_url: null, blogger_published_at: null });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "approved" })}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByText("Publish now"));
    await waitFor(() => expect(api.publishArticle).toHaveBeenCalledWith(1, false));

    vi.mocked(window.confirm).mockRestore();
  });

  it("calls publishArticle with as_draft=true on Save as draft", async () => {
    api.publishArticle.mockResolvedValue({ id: 1, status: "publishing", blogger_post_url: null, blogger_published_at: null });

    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "approved" })}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByText("Save as draft"));
    await waitFor(() => expect(api.publishArticle).toHaveBeenCalledWith(1, true));
  });

  it("calls retryPublish on Retry publish", async () => {
    api.retryPublish.mockResolvedValue({ id: 1, status: "publishing", blogger_post_url: null, blogger_published_at: null });

    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "publish_failed" })}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByText("Retry publish"));
    await waitFor(() => expect(api.retryPublish).toHaveBeenCalledWith(1));
  });

  it("calls retryPublish on Update on Blogger", async () => {
    api.retryPublish.mockResolvedValue({ id: 1, status: "publishing", blogger_post_url: null, blogger_published_at: null });

    render(
      <ArticlePublishPanel
        article={makeArticle({
          status: "published",
          blogger_post_url: "https://myblog.blogspot.com/2026/08/test.html",
        })}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByText("Update on Blogger"));
    await waitFor(() => expect(api.retryPublish).toHaveBeenCalledWith(1));
  });

  it("does not call publishArticle when confirm is cancelled", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);

    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "approved" })}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByText("Publish now"));
    await act(async () => {});
    expect(api.publishArticle).not.toHaveBeenCalled();

    vi.mocked(window.confirm).mockRestore();
  });

  it("calls onChange after successful publish", async () => {
    const onChange = vi.fn();
    const published = makeArticle({ status: "publishing", running: true });
    api.publishArticle.mockResolvedValue({ id: 1, status: "publishing", blogger_post_url: null, blogger_published_at: null });
    api.getArticle.mockResolvedValue(published);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "approved" })}
        onChange={onChange}
      />,
    );

    fireEvent.click(await screen.findByText("Publish now"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(published));

    vi.mocked(window.confirm).mockRestore();
  });

  it("displays error when publish fails", async () => {
    api.publishArticle.mockRejectedValue(new Error("Connection failed"));
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "approved" })}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByText("Publish now"));
    expect(await screen.findByText("Connection failed")).toBeInTheDocument();

    vi.mocked(window.confirm).mockRestore();
  });
});

describe("ArticlePublishPanel polling", () => {
  it("polls while status is publishing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const published = makeArticle({ status: "published", running: false });

    api.publishArticle.mockResolvedValue({ id: 1, status: "publishing", blogger_post_url: null, blogger_published_at: null });
    api.getArticle.mockResolvedValue(published);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const onChange = vi.fn();
    render(
      <ArticlePublishPanel article={makeArticle({ status: "approved" })} onChange={onChange} />,
    );

    fireEvent.click(await screen.findByText("Publish now"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(api.getArticle).toHaveBeenCalled();

    vi.mocked(window.confirm).mockRestore();
  });

  it("stops polling when status is no longer publishing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const published = makeArticle({ status: "published", running: false });

    api.getArticle.mockResolvedValue(published);

    render(
      <ArticlePublishPanel article={published} onChange={vi.fn()} />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(api.getArticle).not.toHaveBeenCalled();
  });
});

describe("ArticlePublishPanel connection awareness", () => {
  it("disables buttons when blogger is not connected", async () => {
    api.getBloggerStatus.mockResolvedValue(makeBlogStatus({ connected: false, status: "disconnected" }));

    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "approved" })}
        onChange={vi.fn()}
      />,
    );

    await screen.findByText("Publish now");
    expect(screen.getByRole("button", { name: /Publish now/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Save as draft/ })).toBeDisabled();
  });

  it("shows connection hint when not connected", async () => {
    api.getBloggerStatus.mockResolvedValue(makeBlogStatus({ connected: false, status: "disconnected" }));

    render(
      <ArticlePublishPanel
        article={makeArticle({ status: "approved" })}
        onChange={vi.fn()}
      />,
    );

    expect(await screen.findByText(/Connect your Blogger account in Settings/)).toBeInTheDocument();
  });
});

describe("ArticlePublishPanel article switching", () => {
  it("resets state when article changes", async () => {
    const article1 = makeArticle({ id: 1, status: "approved" });
    const article2 = makeArticle({ id: 2, status: "approved" });

    const { rerender } = render(
      <ArticlePublishPanel article={article1} onChange={vi.fn()} />,
    );

    await screen.findByText("Publish now");

    rerender(
      <ArticlePublishPanel article={article2} onChange={vi.fn()} />,
    );

    await screen.findByText("Publish now");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
