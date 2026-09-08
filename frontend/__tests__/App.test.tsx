/**
 * App.test.tsx — REQ-APL-004 responsive drawer fallback integration tests.
 *
 * Covers REQ-APL-004 scenarios at the App level (not just at hook level):
 *   S1. Initial render at narrow viewport (600 px) renders the <aside> as a
 *       full-width overlay drawer (100% width, absolute positioning).
 *   S2. Cross-boundary resize from wide (800 px) to narrow (600 px) swaps the
 *       panel into drawer mode within the 250 ms debounce.
 *   S3. Cross-boundary resize from narrow (600 px) back to wide (1024 px)
 *       restores the panel to fixed-sidebar mode within 250 ms.
 *
 * Also asserts that the drag handle is hidden in drawer mode and re-appears
 * in sidebar mode — a consequence of the conditional render at App.tsx.
 *
 * Notes:
 *   - The <aside> in App.tsx carries `data-testid="ai-chat-panel"` (minimal
 *     scoped test hook) so the test selector is robust against future ARIA
 *     role-mapping changes.
 *   - The AI chat toggle button in the header reads "SHOW AI" when the panel
 *     is closed and "HIDE AI" when open. We match by exact-text regex.
 *   - `window.innerWidth` is mocked via `Object.defineProperty` before each
 *     render so the App's `useState` initializer picks up the right viewport.
 *   - `localStorage.clear()` runs in `beforeEach` to ensure
 *     `useChatPreferences` initializes to the default 480 px width.
 */

import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

// --- Mocks ---

const authMock = {
  isAuthenticated: true,
  loading: false,
  user: {
    username: "admin",
    role: "ADMIN",
    permissions: [],
    allowed_locations: [],
    tier: "T1",
  },
  hasPermission: vi.fn(() => true),
  logout: vi.fn(),
};

vi.mock("../context/AuthContext", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => authMock,
}));

vi.mock("../components/GraphCMDB", () => ({ default: () => <div>Graph CMDB</div> }));
vi.mock("../components/AIAgentConsole", () => ({ default: () => <div>AI Console</div> }));
vi.mock("../components/CIEditor", () => ({ default: () => <div>CI Editor</div> }));
vi.mock("../components/AdminPage", () => ({ default: () => <div>Administration</div> }));
vi.mock("../components/MonitoringConsole", () => ({ default: () => <div>Monitoring</div> }));
vi.mock("../components/SystemDashboard", () => ({ default: () => <div>System Dashboard</div> }));
vi.mock("../components/GlobalInventory", () => ({ default: () => <div>Inventory</div> }));
vi.mock("../components/ChangePasswordPage", () => ({ default: () => <div>Change Password</div> }));
vi.mock("../components/UserManager", () => ({ default: () => <div>User Manager</div> }));
vi.mock("../components/AuditLogPage", () => ({ default: () => <div>Audit Log</div> }));
vi.mock("../components/CIDetailModal", () => ({ default: () => <div>CI Detail Modal</div> }));
vi.mock("../components/MetricAnalytics", () => ({ default: () => <div>Metric Analytics</div> }));
vi.mock("../components/VisualRelationshipEditorPage", () => ({
  default: () => <div>Visual Editor</div>,
}));
vi.mock("../components/LoginPage", () => ({ default: () => <div>Login Page</div> }));
vi.mock("../components/ItsmServiceCatalogPage", () => ({
  default: () => <div>Service Catalog Page</div>,
}));
vi.mock("../components/ItsmTicketFolioPage", () => ({
  default: () => <div>Service Management Page</div>,
}));

// --- Helpers ---

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", {
    value: width,
    writable: true,
    configurable: true,
  });
}

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

function openAIPanel() {
  const toggleButton = screen.getByRole("button", { name: /SHOW AI/i });
  fireEvent.click(toggleButton);
}

// --- Tests ---

describe("App — REQ-APL-004 responsive drawer fallback", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders <aside> in full-width overlay mode when initial viewport is 600px", () => {
    setViewportWidth(600);
    renderApp();
    openAIPanel();

    const aside = screen.getByTestId("ai-chat-panel");
    expect(aside).toHaveStyle({ width: "100%" });
    // Drawer-mode class flag — fixed + inset-0 + z-50 make the panel fill the viewport.
    expect(aside.className).toMatch(/fixed/);
    expect(aside.className).toMatch(/inset-0/);
    expect(aside.className).toMatch(/w-screen/);
    expect(aside.className).toMatch(/z-50/);
    // Drag handle is hidden in drawer mode (no resize at full viewport width).
    expect(screen.queryByTestId("ai-chat-resize-handle")).toBeNull();
  });

  it("renders <aside> in fixed-sidebar mode at default 480px when initial viewport is 1024px", () => {
    setViewportWidth(1024);
    renderApp();
    openAIPanel();

    const aside = screen.getByTestId("ai-chat-panel");
    expect(aside).toHaveStyle({ width: "480px" });
    // Sidebar-mode — no full-viewport overlay classes.
    expect(aside.className).not.toMatch(/w-screen/);
    // Drag handle is visible in sidebar mode.
    expect(screen.getByTestId("ai-chat-resize-handle")).toBeInTheDocument();
  });

  it("switches from sidebar to overlay mode when viewport crosses below 768px (debounced 250ms)", () => {
    setViewportWidth(1024);
    renderApp();
    openAIPanel();

    const aside = screen.getByTestId("ai-chat-panel");
    expect(aside).toHaveStyle({ width: "480px" });

    // Cross below threshold.
    setViewportWidth(600);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });

    // Before debounce elapses, still sidebar mode.
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(aside).toHaveStyle({ width: "480px" });

    // After debounce, switches to drawer mode.
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(aside).toHaveStyle({ width: "100%" });
    expect(aside.className).toMatch(/w-screen/);
    // Drag handle disappears in drawer mode.
    expect(screen.queryByTestId("ai-chat-resize-handle")).toBeNull();
  });

  it("switches from overlay back to sidebar mode when viewport crosses above 768px (debounced 250ms)", () => {
    setViewportWidth(600);
    renderApp();
    openAIPanel();

    const aside = screen.getByTestId("ai-chat-panel");
    expect(aside).toHaveStyle({ width: "100%" });

    // Cross back above threshold.
    setViewportWidth(1024);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });

    // Before debounce elapses, still drawer mode.
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(aside).toHaveStyle({ width: "100%" });

    // After debounce, switches back to sidebar mode at the persisted width.
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(aside).toHaveStyle({ width: "480px" });
    expect(aside.className).not.toMatch(/w-screen/);
    // Drag handle reappears in sidebar mode.
    expect(screen.getByTestId("ai-chat-resize-handle")).toBeInTheDocument();
  });
});
