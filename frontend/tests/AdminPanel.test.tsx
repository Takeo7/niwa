import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminPanel } from "../src/features/admin/AdminPanel";
import { renderWithProviders } from "./renderWithProviders";

function mockJson(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("AdminPanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("checks /auth/me before rendering the admin surface when auth is enabled", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(mockJson({ enabled: true }))
      .mockResolvedValueOnce(mockJson({ detail: "Authentication required" }, 401));
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(<AdminPanel />);

    expect(await screen.findByText("Login")).toBeTruthy();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/auth/me",
        expect.objectContaining({ credentials: "same-origin" }),
      );
    });
    expect(screen.queryByText("Admin")).toBeNull();
  });
});
