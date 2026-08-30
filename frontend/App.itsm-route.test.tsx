import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";

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

vi.mock("./context/AuthContext", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => authMock,
}));

vi.mock("./components/GraphCMDB", () => ({
  default: () => <div>Graph CMDB</div>,
}));
vi.mock("./components/AIAgentConsole", () => ({
  default: () => <div>AI Console</div>,
}));
vi.mock("./components/CIEditor", () => ({
  default: () => <div>CI Editor</div>,
}));
vi.mock("./components/AdminPage", () => ({
  default: () => <div>Administration</div>,
}));
vi.mock("./components/MonitoringConsole", () => ({
  default: () => <div>Monitoring</div>,
}));
vi.mock("./components/SystemDashboard", () => ({
  default: () => <div>System Dashboard</div>,
}));
vi.mock("./components/GlobalInventory", () => ({
  default: () => <div>Inventory</div>,
}));
vi.mock("./components/ChangePasswordPage", () => ({
  default: () => <div>Change Password</div>,
}));
vi.mock("./components/UserManager", () => ({
  default: () => <div>User Manager</div>,
}));
vi.mock("./components/AuditLogPage", () => ({
  default: () => <div>Audit Log</div>,
}));
vi.mock("./components/CIDetailModal", () => ({
  default: () => <div>CI Detail Modal</div>,
}));
vi.mock("./components/MetricAnalytics", () => ({
  default: () => <div>Metric Analytics</div>,
}));
vi.mock("./components/VisualRelationshipEditorPage", () => ({
  default: () => <div>Visual Editor</div>,
}));
vi.mock("./components/LoginPage", () => ({
  default: () => <div>Login Page</div>,
}));
vi.mock("./components/ItsmServiceCatalogPage", () => ({
  default: () => <div>Service Catalog Page</div>,
}));
vi.mock("./components/ItsmTicketFolioPage", () => ({
  default: () => <div>Service Management Page</div>,
}));

const renderApp = (initialPath = "/itsm/service-catalog") => {
  window.location.hash = `#${initialPath}`;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
};

describe("App routing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.hasPermission = vi.fn(() => true);
  });

  it("renders dedicated Service Catalog route", () => {
    renderApp("/itsm/service-catalog");

    expect(screen.getByText("Service Catalog Page")).toBeInTheDocument();
  });

  it("renders dedicated Service Management route", () => {
    renderApp("/itsm/tickets");

    expect(screen.getByText("Service Management Page")).toBeInTheDocument();
  });

  it("keeps existing inventory route intact", () => {
    renderApp("/inventory");

    expect(screen.getByText("Inventory")).toBeInTheDocument();
  });
});
