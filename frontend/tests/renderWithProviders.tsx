import type { ReactElement, ReactNode } from "react";
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, type RenderResult } from "@testing-library/react";

interface Options {
  route?: string;
  routePattern?: string;
}

// Wraps a component in the same provider tree used in production:
// QueryClient (retry=false to fail fast in tests) + MemoryRouter +
// MantineProvider. If `routePattern` is given we mount through <Routes>
// so that hooks like `useParams` resolve; otherwise the element renders
// directly under the router.
export function renderWithProviders(
  ui: ReactElement,
  { route = "/", routePattern }: Options = {},
): RenderResult {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const body: ReactNode = routePattern ? (
    <Routes>
      <Route path={routePattern} element={ui} />
    </Routes>
  ) : (
    ui
  );

  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>{body}</MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}
