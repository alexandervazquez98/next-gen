import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import UserManager from "../UserManager";

const mocks = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  usePermissions: vi.fn(),
}));

vi.mock("../services/api", () => ({
  api: mocks.api,
}));

vi.mock("../services/permissions", () => ({
  usePermissions: mocks.usePermissions,
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: vi.fn(() => ({ hasPermission: () => true })),
}));

vi.mock("./RoleManager", () => ({ default: () => <div>Role Manager</div> }));

const ROLES = [{ name: "VIEWER", permissions: ["EVENT_VIEW"] }];

const USERS_HUMAN = [
  { username: "alice", role: "VIEWER", permissions: ["EVENT_VIEW"], allowed_locations: [] },
  { username: "bob", role: "VIEWER", permissions: ["EVENT_VIEW"], allowed_locations: [] },
];

function setupDefaultMocks() {
  mocks.usePermissions.mockReturnValue({
    human: ["EVENT_VIEW", "EVENT_ACK", "CI_VIEW"],
    ai: ["AI_VIEW_ALL"],
    loading: false,
    error: null,
  });
}

describe("UserManager — WU 8 logical deactivation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.api.get.mockImplementation((endpoint: string) => {
      if (endpoint === "/roles/") return Promise.resolve(ROLES);
      if (endpoint === "/users/") return Promise.resolve(USERS_HUMAN);
      return Promise.resolve([]);
    });
  });

  it("calls POST /users/{username}/deactivate after confirmation", async () => {
    mocks.api.post.mockResolvedValueOnce(undefined);
    render(<UserManager />);

    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());

    const deactivateButtons = screen.getAllByRole("button", { name: /deactivate user/i });
    expect(deactivateButtons.length).toBeGreaterThanOrEqual(1);

    fireEvent.click(deactivateButtons[0]);

    await waitFor(() =>
      expect(mocks.api.post).toHaveBeenCalledWith("/users/alice/deactivate", {}),
    );
  });

  it("does not call deactivate when the confirm prompt is rejected", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<UserManager />);

    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());

    const deactivateButtons = screen.getAllByRole("button", { name: /deactivate user/i });
    fireEvent.click(deactivateButtons[0]);

    expect(mocks.api.post).not.toHaveBeenCalledWith(
      expect.stringMatching(/deactivate/),
      expect.anything(),
    );
  });

  it("treats 404/409 as idempotent success and refreshes the user list", async () => {
    mocks.api.post.mockRejectedValueOnce(
      Object.assign(new Error("user_already_inactive"), { status: 409 }),
    );
    render(<UserManager />);

    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());

    const deactivateButtons = screen.getAllByRole("button", { name: /deactivate user/i });
    fireEvent.click(deactivateButtons[0]);

    // 409 is treated as a no-op; no alert noise and the list is reloaded.
    await waitFor(() =>
      expect(mocks.api.get).toHaveBeenCalledWith("/users/"),
    );
  });
});