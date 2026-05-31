import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
	createQueryWrapper,
	createTestQueryClient,
} from "../test/queryTestUtils";
import VisualRelationshipEditorPage from "./VisualRelationshipEditorPage";
import { queryKeys } from "../services/queryKeys";

const { mockApiGet, mockHasPermission } = vi.hoisted(() => ({
	mockApiGet: vi.fn(),
	mockHasPermission: vi.fn(),
}));

vi.mock("../services/api", () => ({
	api: {
		get: mockApiGet,
	},
}));

vi.mock("../context/AuthContext", () => ({
	useAuth: () => ({ hasPermission: mockHasPermission }),
}));

vi.mock("./VisualRelationshipEditor", () => ({
	default: ({
		nodes,
		links,
		mode,
		onMutated,
	}: {
		nodes: unknown[];
		links: unknown[];
		mode?: string;
		onMutated: () => Promise<void>;
	}) => (
		<div>
			<span>
				Visual editor workspace {nodes.length} nodes {links.length} links mode{" "}
				{mode}
			</span>
			<button type="button" onClick={() => void onMutated()}>
				Trigger mutation refresh
			</button>
		</div>
	),
}));

function QuerySeeder() {
	const queryClient = useQueryClient();
	queryClient.setQueryData(queryKeys.graphTopology(), { nodes: [], links: [] });
	return null;
}

const renderPage = (client = createTestQueryClient()) =>
	render(
		<MemoryRouter>
			<VisualRelationshipEditorPage />
			<QuerySeeder />
		</MemoryRouter>,
		{ wrapper: createQueryWrapper(client) },
	);

describe("VisualRelationshipEditorPage", () => {
	beforeEach(() => {
		mockApiGet.mockReset();
		mockHasPermission.mockReset();
		mockHasPermission.mockReturnValue(true);
	});

	it("loads nodes and links for the full-page visual editor", async () => {
		mockApiGet.mockImplementation((endpoint: string) => {
			if (endpoint === "/nodes") {
				return Promise.resolve([
					{
						id: "ci-a",
						label: "Router A",
						type: "INFRASTRUCTURE",
						status: "OK",
						metadata: {},
					},
				]);
			}
			if (endpoint === "/links") {
				return Promise.resolve([
					{ source: "ci-a", target: "ci-b", relationship: "CONNECTS_TO" },
				]);
			}
			return Promise.resolve([]);
		});

		renderPage();

		expect(
			screen.getByLabelText("Loading visual relationship editor"),
		).toBeInTheDocument();
		expect(
			await screen.findByText(
				"Visual editor workspace 1 nodes 1 links mode page",
			),
		).toBeInTheDocument();
		await waitFor(() => {
			expect(mockApiGet).toHaveBeenCalledWith(
				"/nodes",
				expect.objectContaining({ signal: expect.any(AbortSignal) }),
			);
			expect(mockApiGet).toHaveBeenCalledWith(
				"/links",
				expect.objectContaining({ signal: expect.any(AbortSignal) }),
			);
		});
	});

	it("invalidates graph resources after visual editor mutations", async () => {
		mockApiGet.mockImplementation((endpoint: string) => {
			if (endpoint === "/nodes") return Promise.resolve([]);
			if (endpoint === "/links") return Promise.resolve([]);
			return Promise.resolve([]);
		});

		const client = createTestQueryClient();
		const invalidateSpy = vi.spyOn(client, "invalidateQueries");
		renderPage(client);

		await screen.findByText(
			"Visual editor workspace 0 nodes 0 links mode page",
		);
		fireEvent.click(
			screen.getByRole("button", { name: "Trigger mutation refresh" }),
		);

		await waitFor(() => {
			expect(invalidateSpy).toHaveBeenCalledWith({
				queryKey: queryKeys.nodes(),
			});
			expect(invalidateSpy).toHaveBeenCalledWith({
				queryKey: queryKeys.links(),
			});
			expect(invalidateSpy).toHaveBeenCalledWith({
				queryKey: queryKeys.graphTopologyRoot(),
			});
		});
	});

	it("blocks direct access without CI edit permissions", () => {
		mockHasPermission.mockReturnValue(false);

		renderPage();

		expect(
			screen.getByLabelText("Visual relationship editor access denied"),
		).toBeInTheDocument();
		expect(screen.getByText("Access denied")).toBeInTheDocument();
		expect(mockApiGet).not.toHaveBeenCalled();
	});

	it("shows an error state when visual editor data cannot load", async () => {
		mockApiGet.mockRejectedValue(new Error("down"));

		renderPage();

		expect(
			await screen.findByText("Could not load visual editor data"),
		).toBeInTheDocument();
		expect(screen.getByRole("link", { name: "Back to admin" })).toHaveAttribute(
			"href",
			"/admin",
		);
	});
});
