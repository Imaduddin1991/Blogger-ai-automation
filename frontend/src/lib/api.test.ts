import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  formatCoverage,
  formatDate,
  getArticleImages,
  removeArticleImage,
  retryArticleImages,
  searchArticleImages,
  selectArticleImage,
  statusLabel,
} from "@/lib/api";

const okBody = {
  article_id: 1,
  status: "image_ready",
  running: false,
  images: [],
};

function stubFetch(ok: boolean, body: unknown = okBody, status = 200) {
  const spy = vi.fn(async () =>
    ok
      ? ({ ok: true, json: async () => body } as Response)
      : ({
          ok: false,
          status,
          statusText: "Conflict",
          json: async () => ({ detail: "A pipeline job for this article is already running." }),
        } as Response),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("statusLabel", () => {
  it("maps known statuses to friendly labels", () => {
    expect(statusLabel("researching")).toBe("Researching…");
    expect(statusLabel("complete")).toBe("Complete");
    expect(statusLabel("error")).toBe("Error");
    expect(statusLabel("researched")).toBe("Researched");
  });

  it("maps article pipeline statuses to friendly labels", () => {
    expect(statusLabel("draft")).toBe("Draft");
    expect(statusLabel("drafting")).toBe("Generating…");
    expect(statusLabel("drafted")).toBe("Drafted");
    expect(statusLabel("seo_done")).toBe("SEO done");
    expect(statusLabel("checked")).toBe("Checked");
  });

  it("maps image pipeline statuses to friendly labels", () => {
    expect(statusLabel("images_searching")).toBe("Searching for images…");
    expect(statusLabel("image_ready")).toBe("Image ready");
    expect(statusLabel("ready_for_review")).toBe("Ready for review");
    expect(statusLabel("approved")).toBe("Approved");
    expect(statusLabel("candidate")).toBe("Candidate");
    expect(statusLabel("suggested")).toBe("Suggested");
    expect(statusLabel("selected")).toBe("Selected");
    expect(statusLabel("rejected")).toBe("Rejected");
  });

  it("passes through unknown statuses", () => {
    expect(statusLabel("weird_state")).toBe("weird_state");
  });
});

describe("formatCoverage", () => {
  it("renders coverage as a percentage", () => {
    expect(formatCoverage(0.6)).toBe("60%");
    expect(formatCoverage(1)).toBe("100%");
    expect(formatCoverage(0)).toBe("0%");
  });

  it("renders 0% when coverage is missing", () => {
    expect(formatCoverage(null)).toBe("0%");
  });
});

describe("formatDate", () => {
  it("formats an ISO timestamp", () => {
    const out = formatDate("2026-08-14T12:00:00Z");
    expect(out).not.toBe("2026-08-14T12:00:00Z");
    expect(out.length).toBeGreaterThan(0);
  });

  it("returns the input unchanged when unparseable", () => {
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
});

describe("image API client", () => {
  it("GETs article images", async () => {
    const fetchMock = stubFetch(true);
    await expect(getArticleImages(1)).resolves.toEqual(okBody);
    expect(fetchMock).toHaveBeenCalledWith("/api/articles/1/images", expect.anything());
  });

  it("POSTs an image search", async () => {
    const fetchMock = stubFetch(true);
    await expect(searchArticleImages(1)).resolves.toEqual(okBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/articles/1/images/search",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("POSTs an image retry", async () => {
    const fetchMock = stubFetch(true);
    await expect(retryArticleImages(1)).resolves.toEqual(okBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/articles/1/images/retry",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("POSTs an image selection", async () => {
    const fetchMock = stubFetch(true);
    await expect(selectArticleImage(1, 42)).resolves.toEqual(okBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/articles/1/images/42/select",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("DELETEs an image", async () => {
    const fetchMock = stubFetch(true);
    await expect(removeArticleImage(1, 42)).resolves.toEqual(okBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/articles/1/images/42",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("surfaces the backend detail message on a 409", async () => {
    stubFetch(false);
    await expect(selectArticleImage(1, 42)).rejects.toThrow(ApiError);
    await expect(selectArticleImage(1, 42)).rejects.toThrow(
      "A pipeline job for this article is already running.",
    );
  });
});
