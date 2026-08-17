import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ArticlesView } from "@/components/articles/articles-view";
import { ArticleImagesPanel } from "@/components/articles/article-images-panel";
import type { Article, ArticleDetail, ArticleImages, ImageRecord } from "@/lib/api";

const api = vi.hoisted(() => ({
  listArticles: vi.fn(),
  getArticle: vi.fn(),
  updateArticle: vi.fn(),
  recheckArticle: vi.fn(),
  retryArticle: vi.fn(),
  approveArticle: vi.fn(),
  getArticleImages: vi.fn(),
  searchArticleImages: vi.fn(),
  retryArticleImages: vi.fn(),
  selectArticleImage: vi.fn(),
  removeArticleImage: vi.fn(),
  getBloggerStatus: vi.fn(),
  publishArticle: vi.fn(),
  retryPublish: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  ApiError: class extends Error {
    constructor(message: string, public status: number) {
      super(message);
      this.name = "ApiError";
    }
  },
  listArticles: api.listArticles,
  getArticle: api.getArticle,
  updateArticle: api.updateArticle,
  recheckArticle: api.recheckArticle,
  retryArticle: api.retryArticle,
  approveArticle: api.approveArticle,
  getArticleImages: api.getArticleImages,
  searchArticleImages: api.searchArticleImages,
  retryArticleImages: api.retryArticleImages,
  selectArticleImage: api.selectArticleImage,
  removeArticleImage: api.removeArticleImage,
  getBloggerStatus: api.getBloggerStatus,
  publishArticle: api.publishArticle,
  retryPublish: api.retryPublish,
  statusLabel: (s: string) =>
    s === "selected"
      ? "Selected"
      : s === "suggested"
        ? "Suggested"
        : s === "images_searching"
          ? "Searching…"
          : s,
  formatDate: (s: string) => s,
}));

function makeImage(overrides: Partial<ImageRecord> = {}): ImageRecord {
  return {
    id: 1,
    article_id: 1,
    provider: "commons",
    url: "https://upload.wikimedia.org/example.jpg",
    alt: "A cat",
    caption: "A cat",
    attribution: null,
    license: "CC BY-SA 4.0",
    position: 0,
    status: "suggested",
    page_url: "https://commons.wikimedia.org/wiki/File:Example.jpg",
    author: "Example Author",
    license_url: "https://creativecommons.org/licenses/by-sa/4.0/",
    attribution_required: false,
    usage_notes: null,
    thumb_url: "https://upload.wikimedia.org/thumb/example.jpg",
    mime: "image/jpeg",
    width: 800,
    height: 600,
    file_size: 12345,
    relevance: 0.85,
    retrieved_at: "2026-08-14T12:00:00Z",
    rejection_reason: null,
    created_at: "2026-08-14T12:00:00Z",
    updated_at: "2026-08-14T12:00:00Z",
    ...overrides,
  };
}

function makeImages(overrides: Partial<ArticleImages> = {}): ArticleImages {
  return {
    article_id: 1,
    status: "image_ready",
    running: false,
    images: [],
    ...overrides,
  };
}

function withImage(overrides: Partial<ImageRecord> = {}) {
  const image = makeImage(overrides);
  return { image, payload: makeImages({ images: [image] }) };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getBloggerStatus.mockResolvedValue({ connected: true, blog_id: "1", blog_url: "https://blog.example.com", blog_name: "Blog", status: "connected" });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ArticleImagesPanel rendering", () => {
  it("shows a loading skeleton before data arrives", () => {
    api.getArticleImages.mockReturnValue(new Promise(() => {}));
    render(<ArticleImagesPanel articleId={1} articleStatus="checked" />);
    expect(screen.getByLabelText("Loading images")).toBeInTheDocument();
  });

  it("renders the candidate list with caption, license, and author", async () => {
    const { payload } = withImage();
    api.getArticleImages.mockResolvedValue(payload);
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    expect(await screen.findByText("A cat")).toBeInTheDocument();
    expect(screen.getByText("Example Author")).toBeInTheDocument();
    expect(screen.getByText("CC BY-SA 4.0")).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
  });

  it("sorts by position then relevance", async () => {
    const low = makeImage({ id: 1, position: 0, relevance: 0.3, caption: "Low" });
    const high = makeImage({ id: 2, position: 0, relevance: 0.9, caption: "High" });
    const later = makeImage({ id: 3, position: 1, relevance: 0.9, caption: "Later" });
    api.getArticleImages.mockResolvedValue(
      makeImages({ images: [later, low, high] }),
    );
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    await screen.findByText("High");
    const cards = screen.getAllByRole("button", { name: /View details for/ });
    expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual([
      "View details for High",
      "View details for Low",
      "View details for Later",
    ]);
  });

  it("shows the empty state when image_ready with no images", async () => {
    api.getArticleImages.mockResolvedValue(makeImages({ status: "image_ready", images: [] }));
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    expect(await screen.findByText("No usable images found")).toBeInTheDocument();
  });

  it("shows the CTA when checked and not yet searched", async () => {
    api.getArticleImages.mockResolvedValue(makeImages({ status: "checked", images: [] }));
    render(<ArticleImagesPanel articleId={1} articleStatus="checked" />);
    expect(await screen.findByRole("button", { name: /Search images/ })).toBeInTheDocument();
  });

  it("shows the searching state for images_searching", async () => {
    api.getArticleImages.mockResolvedValue(makeImages({ status: "images_searching", running: true, images: [] }));
    render(<ArticleImagesPanel articleId={1} articleStatus="checked" />);
    expect(await screen.findByText("Searching…")).toBeInTheDocument();
    expect(screen.getByText(/Fetching candidates from Wikimedia Commons/)).toBeInTheDocument();
  });

  it("does NOT show searching for a concurrent non-image running job", async () => {
    // Article has a generic running job (e.g. recheck) but is still checked.
    api.getArticleImages.mockResolvedValue(makeImages({ status: "checked", running: true, images: [] }));
    render(<ArticleImagesPanel articleId={1} articleStatus="checked" />);
    await screen.findByRole("button", { name: /Search images/ });
    expect(screen.queryByText("Searching…")).not.toBeInTheDocument();
    expect(screen.queryByText(/Fetching candidates from Wikimedia Commons/)).not.toBeInTheDocument();
  });

  it("shows an error state with retry when the load fails", async () => {
    api.getArticleImages.mockRejectedValue(new Error("boom"));
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    expect(await screen.findByText("boom")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("ArticleImagesPanel actions", () => {
  it("queues a search from the CTA", async () => {
    api.getArticleImages.mockResolvedValue(makeImages({ status: "checked", images: [] }));
    api.searchArticleImages.mockResolvedValue(makeImages({ status: "checked", images: [] }));
    render(<ArticleImagesPanel articleId={7} articleStatus="checked" />);
    fireEvent.click(await screen.findByRole("button", { name: /Search images/ }));
    await waitFor(() => expect(api.searchArticleImages).toHaveBeenCalledWith(7));
    expect(screen.getByText(/Fetching candidates from Wikimedia Commons/)).toBeInTheDocument();
  });

  it("retries the search from the empty image_ready state", async () => {
    api.getArticleImages.mockResolvedValue(makeImages({ status: "image_ready", images: [] }));
    api.retryArticleImages.mockResolvedValue(makeImages({ status: "image_ready", images: [] }));
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    fireEvent.click(await screen.findByRole("button", { name: /Retry search/ }));
    await waitFor(() => expect(api.retryArticleImages).toHaveBeenCalledWith(1));
  });

  it("selects a suggested image and refetches", async () => {
    const { image, payload } = withImage();
    const selectedPayload = makeImages({
      images: [{ ...image, status: "selected" }],
    });
    api.getArticleImages.mockResolvedValue(payload);
    api.selectArticleImage.mockResolvedValue(selectedPayload);
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    fireEvent.click(await screen.findByRole("button", { name: /Select/ }));
    await waitFor(() => expect(api.selectArticleImage).toHaveBeenCalledWith(1, image.id));
    expect(await screen.findByTestId("selected-check")).toBeInTheDocument();
  });

  it("selection does not approve the article", async () => {
    const { payload } = withImage();
    api.getArticleImages.mockResolvedValue(payload);
    api.selectArticleImage.mockResolvedValue(payload);
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    fireEvent.click(await screen.findByRole("button", { name: /Select/ }));
    await waitFor(() => expect(api.selectArticleImage).toHaveBeenCalled());
    expect(api.approveArticle).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });

  it("removes an image after a confirm step", async () => {
    const { image, payload } = withImage();
    api.getArticleImages.mockResolvedValue(payload);
    api.removeArticleImage.mockResolvedValue(makeImages({ images: [] }));
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    const remove = await screen.findByRole("button", { name: "Remove" });
    fireEvent.click(remove);
    fireEvent.click(screen.getByRole("button", { name: /Confirm removing/ }));
    await waitFor(() => expect(api.removeArticleImage).toHaveBeenCalledWith(1, image.id));
  });

  it("disables the select action for rejected images and shows the reason", async () => {
    const { payload } = withImage({
      status: "rejected",
      rejection_reason: "Off-topic for this article",
    });
    api.getArticleImages.mockResolvedValue(payload);
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    expect(await screen.findByText(/Off-topic for this article/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Select/ })).not.toBeInTheDocument();
  });

  it("shows a selected badge and check for selected images", async () => {
    const { payload } = withImage({ status: "selected" });
    api.getArticleImages.mockResolvedValue(payload);
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    expect(await screen.findByText("Selected")).toBeInTheDocument();
    expect(screen.getByTestId("selected-check")).toBeInTheDocument();
  });

  it("shows a suggested badge for suggested images", async () => {
    const { payload } = withImage({ status: "suggested" });
    api.getArticleImages.mockResolvedValue(payload);
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    expect(await screen.findByText("Suggested")).toBeInTheDocument();
  });

  it("shows attribution-required marker and license", async () => {
    const { payload } = withImage({ attribution_required: true });
    api.getArticleImages.mockResolvedValue(payload);
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    await screen.findByText("A cat");
    expect(screen.getByText("attribution")).toBeInTheDocument();
  });
});

describe("ArticleImagesPanel error handling", () => {
  it("surfaces the backend 409 message verbatim on an edit race", async () => {
    api.getArticleImages.mockResolvedValue(makeImages({ status: "checked", images: [] }));
    api.searchArticleImages.mockRejectedValue(
      new (class extends Error {
        status = 409;
      })("A pipeline job for this article is already running."),
    );
    render(<ArticleImagesPanel articleId={1} articleStatus="checked" />);
    fireEvent.click(await screen.findByRole("button", { name: /Search images/ }));
    expect(
      await screen.findByText("A pipeline job for this article is already running."),
    ).toBeInTheDocument();
  });

  it("does not loop on a failed load (no automatic retry)", async () => {
    api.getArticleImages.mockRejectedValue(new Error("boom"));
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    await screen.findByText("boom");
    expect(api.getArticleImages).toHaveBeenCalledTimes(1);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
    expect(api.getArticleImages).toHaveBeenCalledTimes(1);
  });

  it("stops polling once the search completes", async () => {
    const searching = makeImages({ status: "images_searching", running: true, images: [] });
    const done = makeImages({ status: "image_ready", running: false, images: [] });
    api.getArticleImages
      .mockResolvedValueOnce(searching)
      .mockResolvedValueOnce(searching)
      .mockResolvedValue(done);
    render(<ArticleImagesPanel articleId={1} articleStatus="checked" />);
    expect(await screen.findByText("Searching…")).toBeInTheDocument();
    await waitFor(
      () => expect(api.getArticleImages.mock.calls.length).toBeGreaterThanOrEqual(3),
      { timeout: 7000 },
    );
    await waitFor(() => expect(screen.queryByText("Searching…")).not.toBeInTheDocument(), {
      timeout: 7000,
    });
  });
});

describe("ArticleImagesPanel polling bound", () => {
  it("caps the polling loop at ~120s and stops", async () => {
    vi.useFakeTimers();
    const searching = makeImages({ status: "images_searching", images: [] });
    api.getArticleImages.mockResolvedValue(searching);
    render(<ArticleImagesPanel articleId={1} articleStatus="checked" />);
    await act(async () => {
      await Promise.resolve();
    });
    const callsBefore = api.getArticleImages.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(200_000);
    });
    const callsAfter = api.getArticleImages.mock.calls.length;
    // 2s interval over 120s cap => ~60 polls max, well under 100; no infinite loop.
    expect(callsAfter - callsBefore).toBeLessThanOrEqual(100);
    expect(callsAfter - callsBefore).toBeGreaterThan(0);
    const callsStable = api.getArticleImages.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(20_000);
    });
    expect(api.getArticleImages.mock.calls.length).toBe(callsStable);
  });
});

describe("approval gate integration", () => {
  function makeArticle(overrides: Partial<Article> = {}): Article {
    return {
      id: 1,
      idea_id: null,
      blog_id: null,
      title: "Test article",
      slug: null,
      seo_title: null,
      meta_description: null,
      labels: [],
      word_count: 0,
      status: "checked",
      generation_errors: null,
      review_approved_at: null,
      created_at: "2026-08-14T12:00:00Z",
      updated_at: "2026-08-14T12:00:00Z",
      ...overrides,
    };
  }

  function makeDetail(overrides: Partial<ArticleDetail> = {}): ArticleDetail {
    return {
      id: 1,
      idea_id: null,
      blog_id: null,
      title: "Test article",
      slug: null,
      seo_title: null,
      meta_description: null,
      labels: [],
      word_count: 100,
      status: "checked",
      generation_errors: null,
      review_approved_at: null,
      created_at: "2026-08-14T12:00:00Z",
      updated_at: "2026-08-14T12:00:00Z",
      body: "Body",
      summary_text: null,
      idea_title: null,
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

  it("keeps the approve action disabled while the image panel reports a running job", async () => {
    const article = makeArticle();
    const detail = makeDetail({ status: "checked", running: false });
    api.listArticles.mockResolvedValue([article]);
    api.getArticle.mockResolvedValue(detail);
    // Image panel sees a concurrent image job => reports busy even though article.running is false.
    api.getArticleImages.mockResolvedValue(makeImages({ status: "images_searching", running: true, images: [] }));

    render(<ArticlesView />);
    fireEvent.click(await screen.findByRole("button", { name: /Test article/ }));
    await screen.findByRole("button", { name: "Mark ready for review" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Mark ready for review" })).toBeDisabled());
    expect(api.approveArticle).not.toHaveBeenCalled();
  });

  it("enables the approve action once the image job is no longer running", async () => {
    const article = makeArticle();
    const detail = makeDetail({ status: "checked", running: false });
    api.listArticles.mockResolvedValue([article]);
    api.getArticle.mockResolvedValue(detail);
    api.getArticleImages.mockResolvedValue(makeImages({ status: "image_ready", running: false, images: [] }));

    render(<ArticlesView />);
    fireEvent.click(await screen.findByRole("button", { name: /Test article/ }));
    const approve = await screen.findByRole("button", { name: "Mark ready for review" });
    expect(approve).toBeEnabled();
  });

  it("does not approve an article in the checked state via image selection", async () => {
    const article = makeArticle();
    const detail = makeDetail({ status: "checked", running: false });
    const { image, payload } = withImage();
    api.listArticles.mockResolvedValue([article]);
    api.getArticle.mockResolvedValue(detail);
    api.getArticleImages.mockResolvedValue(payload);
    api.selectArticleImage.mockResolvedValue(payload);

    render(<ArticlesView />);
    fireEvent.click(await screen.findByRole("button", { name: /Test article/ }));
    const select = await screen.findByRole("button", { name: /Select/ });
    fireEvent.click(select);
    await waitFor(() => expect(api.selectArticleImage).toHaveBeenCalledWith(1, image.id));
    expect(api.approveArticle).not.toHaveBeenCalled();
  });
});

describe("ArticleImagesPanel detail sheet", () => {
  it("opens details with license, source, and attribution, and closes on Escape", async () => {
    const { payload } = withImage({
      attribution_required: true,
      usage_notes: "Share alike required",
    });
    api.getArticleImages.mockResolvedValue(payload);
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    fireEvent.click(await screen.findByRole("button", { name: /View details for A cat/ }));
    expect(await screen.findByText(/Share alike required/)).toBeInTheDocument();
    expect(screen.getByText(/Attribution required/)).toBeInTheDocument();
    const sourceLink = screen.getByRole("link", { name: /View source page/ });
    expect(sourceLink).toHaveAttribute(
      "href",
      "https://commons.wikimedia.org/wiki/File:Example.jpg",
    );
    expect(sourceLink).toHaveAttribute("target", "_blank");
    expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByText(/Share alike required/)).not.toBeInTheDocument(),
    );
  });

  it("does not emit unsafe URLs from metadata", async () => {
    const { payload } = withImage({
      caption: "Unsafe",
      page_url: "javascript:alert(1)",
      license_url: "javascript:alert(2)",
    });
    api.getArticleImages.mockResolvedValue(payload);
    render(<ArticleImagesPanel articleId={1} articleStatus="image_ready" />);
    fireEvent.click(await screen.findByRole("button", { name: /View details for Unsafe/ }));
    await waitFor(() => expect(screen.queryByRole("link", { name: /View source page/ })).not.toBeInTheDocument());
    expect(screen.queryByRole("link", { name: /Read license terms/ })).not.toBeInTheDocument();
  });
});
