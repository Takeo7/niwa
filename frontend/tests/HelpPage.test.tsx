import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HelpPage } from "../src/features/help/HelpPage";
import { renderWithProviders } from "./renderWithProviders";

describe("HelpPage", () => {
  it("renders core section headings", () => {
    renderWithProviders(<HelpPage />);
    expect(screen.getByText("What Niwa does")).toBeTruthy();
    expect(screen.getByText("Quickstart")).toBeTruthy();
    expect(screen.getByText("Task states")).toBeTruthy();
  });

  it("renders at least three copyable bash code blocks", () => {
    const { container } = renderWithProviders(<HelpPage />);
    // Mantine renders <Code block> as a <pre> element with the
    // mantine-Code-root class. Inline <Code> is a <code>.
    const blocks = container.querySelectorAll("pre.mantine-Code-root");
    expect(blocks.length).toBeGreaterThanOrEqual(3);
  });
});
