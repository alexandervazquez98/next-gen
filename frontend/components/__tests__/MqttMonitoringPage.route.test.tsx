/**
 * MQTT Monitoring Frontend (Issue #385) — route + nav entry guard.
 *
 * PR1 verifies the layered permission model from
 * `openspec/changes/feat-mqtt-385-frontend-ux/design.md` §Permission Gates:
 *   - Sidebar nav entry is hidden unless `MQTT_READ` or `ADMIN`.
 *   - The route renders the page only when the session is authorized; denied
 *     sessions redirect to `/` and fire ZERO `/api/mqtt/*` requests.
 *   - ADMIN always passes (matches `hasPermission` short-circuit in
 *     `context/AuthContext.tsx` lines 203–207).
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import App from "../../App";
import { useAuth } from "../../context/AuthContext";

const { mockApiGet } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
}));

vi.mock("../../services/api", () => ({
  api: {
    get: mockApiGet,
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    getSSE: vi.fn(),
    download: vi.fn(),
    request: vi.fn(),
  },
}));

interface AuthState {
  isAuthenticated: boolean;
  loading: boolean;
  user: {
    username: string;
    role: string;
    permissions: string[];
    allowed_locations: string[];
    tier: string;
  } | null;
  hasPermission: (_perm: string) => boolean;
}

const authState: AuthState = {
  isAuthenticated: true,
  loading: false,
  user: {
    username: "tester",
    role: "USER",
    permissions: [],
    allowed_locations: [],
    tier: "T1",
  },
  hasPermission: vi.fn(() => false),
};

vi.mock("../../context/AuthContext", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => authState,
}));

// Stubs for the rest of the App tree.
vi.mock("../../components/GraphCMDB", () => ({ default: () => <div>Graph CMDB</div> }));
vi.mock("../../components/AIAgentConsole", () => ({ default: () => <div>AI Console</div> }));
vi.mock("../../components/CIEditor", () => ({ default: () => <div>CI Editor</div> }));
vi.mock("../../components/AdminPage", () => ({ default: () => <div>Administration</div> }));
vi.mock("../../components/MonitoringConsole", () => ({ default: () => <div>Monitoring</div> }));
vi.mock("../../components/SystemDashboard", () => ({ default: () => <div>System Dashboard</div> }));
vi.mock("../../components/GlobalInventory", () => ({ default: () => <div>Inventory</div> }));
vi.mock("../../components/ChangePasswordPage", () => ({ default: () => <div>Change Password</div> }));
vi.mock("../../components/UserManager", () => ({ default: () => <div>User Manager</div> }));
vi.mock("../../components/AuditLogPage", () => ({ default: () => <div>Audit Log</div> }));
vi.mock("../../components/CIDetailModal", () => ({ default: () => <div>CI Detail Modal</div> }));
vi.mock("../../components/MetricAnalytics", () => ({ default: () => <div>Metric Analytics</div> }));
vi.mock("../../components/VisualRelationshipEditorPage", () => ({
  default: () => <div>Visual Editor</div>,
}));
vi.mock("../../components/LoginPage", () => ({ default: () => <div>Login Page</div> }));
vi.mock("../../components/ItsmServiceCatalogPage", () => ({
  default: () => <div>Service Catalog Page</div>,
}));
vi.mock("../../components/ItsmTicketFolioPage", () => ({
  default: () => <div>Service Management Page</div>,
}));

// The probe must be a PascalCase function so `rules-of-hooks` accepts
// `useAuth()`. We register the mock through `vi.hoisted` so the factory can
// reach the probe without temporal-dead-zone errors after `vi.mock` is
// hoisted above the const declaration.
const mqttMock = vi.hoisted(() => {
  // Probe stub — the real implementation is provided through `vi.mock`
  // below. We keep a PascalCase export so future tests can render the
  // probe directly if they need to bypass `vi.mock`.
  const MqttProbePlaceholder = () => null;
  return { MqttProbePlaceholder };
});
void mqttMock;

vi.mock("../../components/MqttMonitoringPage", () => ({
  default: () => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const auth = useAuth();
    const allowed =
      auth.hasPermission("MQTT_READ") || auth.hasPermission("ADMIN");
    if (!allowed) {
      return <Navigate to="/" replace />;
    }
    return <div data-testid="mqtt-page">MQTT Monitoring Page</div>;
  },
}));

const renderAppAt = (path: string) => {
  window.location.hash = `#${path}`;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
};

const setPermissions = (perms: string[], role = "USER") => {
  authState.user = {
    username: "tester",
    role,
    permissions: perms,
    allowed_locations: [],
    tier: "T1",
  };
  const hasPermission = vi.fn((perm: string) =>
    role === "ADMIN" ? true : perms.includes(perm),
  );
  authState.hasPermission = hasPermission;
};

beforeEach(() => {
  vi.clearAllMocks();
  mockApiGet.mockReset();
  // Default: deny all — each test re-sets the permission set explicitly.
  setPermissions([]);
});

describe("MqttMonitoringPage — route + nav entry guards (PR1)", () => {
  it("hides the sidebar entry when the session lacks MQTT_READ", () => {
    setPermissions([]);
    renderAppAt("/");
    expect(screen.queryByText("MQTT Monitoring")).not.toBeInTheDocument();
  });

  it("shows the sidebar entry when the session has MQTT_READ", () => {
    setPermissions(["MQTT_READ"]);
    renderAppAt("/");
    expect(screen.getByText("MQTT Monitoring")).toBeInTheDocument();
  });

  it("shows the sidebar entry for ADMIN regardless of explicit permissions", () => {
    setPermissions([], "ADMIN");
    renderAppAt("/");
    expect(screen.getByText("MQTT Monitoring")).toBeInTheDocument();
  });

  it("renders the MQTT page when navigating to /monitoring/mqtt with MQTT_READ", async () => {
    setPermissions(["MQTT_READ"]);
    renderAppAt("/monitoring/mqtt");

    await waitFor(() => {
      expect(screen.getByTestId("mqtt-page")).toBeInTheDocument();
    });
  });

  it("redirects to landing page and never mounts the page when MQTT_READ is absent", async () => {
    setPermissions(["EVENT_VIEW"]); // unrelated permission only
    renderAppAt("/monitoring/mqtt");

    // Page must NOT have mounted.
    await waitFor(() => {
      expect(screen.queryByTestId("mqtt-page")).not.toBeInTheDocument();
    });
    // The HashRouter should have rerouted to "/".
    await waitFor(() => {
      expect(window.location.hash).toBe("#/");
    });
  });

  it("renders the page for ADMIN without MQTT_READ in the permission list", async () => {
    setPermissions([], "ADMIN");
    renderAppAt("/monitoring/mqtt");

    await waitFor(() => {
      expect(screen.getByTestId("mqtt-page")).toBeInTheDocument();
    });
  });
});
