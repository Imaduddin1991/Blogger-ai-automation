import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { EmptyState } from "./empty-state";
import { ErrorState } from "./error-state";
import { Lightbulb } from "lucide-react";

describe("EmptyState", () => {
  it("renders title and description", () => {
    render(
      <EmptyState
        icon={Lightbulb}
        title="No ideas yet"
        description="Your first idea will appear here."
      />,
    );
    expect(screen.getByText("No ideas yet")).toBeInTheDocument();
    expect(screen.getByText("Your first idea will appear here.")).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("renders default message and retry button that fires onRetry", () => {
    const onRetry = vi.fn();
    render(<ErrorState onRetry={onRetry} />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    screen.getByRole("button", { name: "Try again" }).click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders no retry button when onRetry is omitted", () => {
    render(<ErrorState />);
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });
});
