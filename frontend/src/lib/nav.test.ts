import { describe, expect, it } from "vitest";

import { isActivePath } from "./nav";

describe("isActivePath", () => {
  it("matches the exact path", () => {
    expect(isActivePath("/dashboard", "/dashboard")).toBe(true);
  });

  it("matches a nested child path", () => {
    expect(isActivePath("/articles/123", "/articles")).toBe(true);
  });

  it("does not match an unrelated path", () => {
    expect(isActivePath("/ideas", "/articles")).toBe(false);
  });

  it("does not match a sibling with a shared prefix", () => {
    expect(isActivePath("/article-review", "/article")).toBe(false);
  });
});
