import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Button } from "../button";

describe("Button", () => {
  it("renders with children", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText("Click me")).toBeDefined();
  });

  it("handles click events", () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click</Button>);
    fireEvent.click(screen.getByText("Click"));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("applies variant classes", () => {
    render(<Button variant="destructive">Delete</Button>);
    const button = screen.getByText("Delete");
    expect(button.className).toContain("bg-destructive");
  });

  it("applies size classes", () => {
    render(<Button size="lg">Large</Button>);
    const button = screen.getByText("Large");
    expect(button.className).toContain("h-12");
  });

  it("is disabled when disabled prop is set", () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByText("Disabled").hasAttribute("disabled")).toBe(true);
  });
});
