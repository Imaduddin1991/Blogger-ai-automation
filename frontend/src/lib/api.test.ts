import { describe, expect, it } from "vitest";

import { formatCoverage, formatDate, statusLabel } from "@/lib/api";

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
