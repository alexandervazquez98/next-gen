import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AuditLogPage from "./AuditLogPage";

const mocks = vi.hoisted(() => ({
	useAuth: vi.fn(),
	api: { get: vi.fn() },
}));

vi.mock("../context/AuthContext", () => ({ useAuth: mocks.useAuth }));
vi.mock("../services/api", () => ({ api: mocks.api }));

const allow = (permissions: string[] = ["AUDIT_VIEW"]) => {
	mocks.useAuth.mockReturnValue({ user: { username: "admin", role: "ADMIN" }, hasPermission: (p: string) => permissions.includes(p) });
};

const baseResponse = {
	items: [
		{ id: 1, event_type: "LOGIN_SUCCESS", outcome: "SUCCESS", actor_username: "alice", actor_role: "USER", target_type: "auth", target_label: "alice", source: "auth", ip_address: "203.0.113.10", user_agent: "Playwright/1.0", context: { route: "/api/auth/token" }, created_at: "2026-06-07T12:00:00Z" },
	],
	total: 1,
	page: 1,
	page_size: 25,
};

const sampleWithMissing = {
	...baseResponse,
	items: [
		{ ...baseResponse.items[0], id: 2, actor_username: null, target_type: null, target_id: null, target_label: null, source: null, ip_address: null, user_agent: null, context: {} },
	],
};

const emptyResponse = { items: [], total: 0, page: 1, page_size: 25 };

describe("AuditLogPage", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		allow(["AUDIT_VIEW"]);
		mocks.api.get.mockResolvedValue(baseResponse);
	});

	it("denies access when permission missing", () => {
		allow([]);
		render(<AuditLogPage />);
		expect(screen.getByText(/access denied\. required: audit_view/i)).toBeInTheDocument();
		expect(mocks.api.get).not.toHaveBeenCalled();
	});

	it("shows table headers and placeholders", async () => {
		mocks.api.get.mockResolvedValueOnce(sampleWithMissing);
		render(<AuditLogPage />);
		await waitFor(() => expect(screen.getAllByText("Not captured").length).toBeGreaterThanOrEqual(2));
		expect(screen.getByRole("columnheader", { name: /^timestamp$/i })).toBeInTheDocument();
		expect(screen.getByRole("columnheader", { name: /target/i })).toBeInTheDocument();
		expect(screen.getByRole("columnheader", { name: /ip \/ context/i })).toBeInTheDocument();
	});

	it("calls /api/audit/events with filters", async () => {
		const user = userEvent.setup();
		render(<AuditLogPage />);
		await waitFor(() => expect(mocks.api.get).toHaveBeenCalledTimes(1));
		const actor = screen.getByRole("textbox", { name: /actor/i });
		await user.type(actor, "alice");
		await user.selectOptions(screen.getByLabelText(/event type/i), "LOGIN_SUCCESS");
		await user.selectOptions(screen.getByLabelText(/outcome/i), "FAILURE");
		await user.selectOptions(screen.getByLabelText(/page size/i), "50");
		await user.selectOptions(screen.getByLabelText(/sort/i), "created_at_asc");
		await user.type(screen.getByLabelText(/start time/i), "2026-06-07T10:00");
		await user.type(screen.getByLabelText(/end time/i), "2026-06-07T11:00");
		await user.click(screen.getByRole("button", { name: /apply filters/i }));
		await waitFor(() => expect(mocks.api.get).toHaveBeenCalledTimes(2));
		const lastUrl = (mocks.api.get.mock.calls.at(-1) as string[])[0];
		const params = new URLSearchParams(lastUrl.split("?")[1]);
		expect(params.get("actor")).toBe("alice");
		expect(params.get("event_type")).toBe("LOGIN_SUCCESS");
		expect(params.get("outcome")).toBe("FAILURE");
		expect(params.get("page_size")).toBe("50");
		expect(params.get("start_time")).toBeTruthy();
		expect(params.get("end_time")).toBeTruthy();
	});

	it("handles empty and 403 responses", async () => {
		const user = userEvent.setup();
		mocks.api.get.mockResolvedValueOnce(emptyResponse);
		render(<AuditLogPage />);
		await waitFor(() => expect(screen.getByText(/no audit events found/i)).toBeInTheDocument());
		mocks.api.get.mockRejectedValueOnce({ status: 403, message: "Forbidden" });
		await user.type(screen.getByRole("textbox", { name: /actor/i }), "ops");
		await user.click(screen.getByRole("button", { name: /apply filters/i }));
		await waitFor(() => expect(screen.getByText(/access denied by permission policy/i)).toBeInTheDocument());
	});
});
