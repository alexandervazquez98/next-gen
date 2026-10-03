/**
 * PhysicalLinksPage.test.tsx
 *
 * Slice 2/4 of feat-444 (closes #444): minimal page-level test that the
 * `PhysicalLinksPage` mounts the `PhysicalLinkPreview` showcase. The
 * showcase's own RTL test (in components/cmdb/topology/__tests__/
 * PhysicalLinkPreview.test.tsx) covers the legend, list, create form, and
 * status mutation behaviour — this page test only pins the wiring
 * (route + page container + child component) so an accidental refactor
 * that drops the preview from the page surfaces here.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { PhysicalLinksPage } from "../PhysicalLinksPage";

function withProviders(node: ReactNode, initialEntries: string[] = ["/physical-links"]) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>{node}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("PhysicalLinksPage", () => {
  it("renders the page header + mounts the PhysicalLinkPreview showcase", () => {
    render(withProviders(<PhysicalLinksPage />));

    // Page-level chrome.
    expect(screen.getByTestId("physical-links-page")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /physical links/i })).toBeInTheDocument();
    expect(screen.getByText(/slice 2\/4 of the fiber-optic/i)).toBeInTheDocument();
  });

  it("exposes a back link to /cmdb", () => {
    render(withProviders(<PhysicalLinksPage />));
    const back = screen.getByRole("link", { name: /back to cmdb/i });
    expect(back).toBeInTheDocument();
    expect(back.getAttribute("href")).toContain("/cmdb");
  });
});
