import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GraphNode } from "../types";
import VisualRelationshipEditor from "./VisualRelationshipEditor";
import type { LinkData } from "./RelationshipManager";

const { mockApiPost, mockApiDelete } = vi.hoisted(() => ({
	mockApiPost: vi.fn(),
	mockApiDelete: vi.fn(),
}));

vi.mock("../services/api", () => ({
	api: {
		post: mockApiPost,
		delete: mockApiDelete,
	},
}));

const nodes: GraphNode[] = [
	{
		id: "ci-a",
		label: "Router A",
		type: "INFRASTRUCTURE",
		status: "ACTIVE",
		metadata: {},
		ip: "10.0.0.1",
	},
	{
		id: "ci-b",
		label: "Switch B",
		type: "INFRASTRUCTURE",
		status: "ACTIVE",
		metadata: {},
		ip: "10.0.0.2",
	},
];

const links: LinkData[] = [
	{
		source: "ci-a",
		source_label: "Router A",
		target: "ci-b",
		target_label: "Switch B",
		relationship: "CONNECTS_TO",
	},
];

const readOnlyLinks: LinkData[] = [
	{
		source: "ci-a",
		source_label: "Router A",
		target: "ci-b",
		target_label: "Switch B",
		relationship: "RUNS_ON",
	},
];

const appNode: GraphNode = {
	id: "app-1",
	label: "App",
	type: "APPLICATION",
	category: "Application",
	status: "ACTIVE",
	metadata: {},
};
const dbNode: GraphNode = {
	id: "db-1",
	label: "DB",
	type: "INFRASTRUCTURE",
	category: "Database",
	status: "ACTIVE",
	metadata: {},
};
const infraNode: GraphNode = {
	id: "infra-1",
	label: "Infra",
	type: "INFRASTRUCTURE",
	status: "ACTIVE",
	metadata: {},
};
const layeredNodes: GraphNode[] = [appNode, dbNode, infraNode];
const layeredLinks: LinkData[] = [
	{
		source: "app-1",
		source_label: "App",
		target: "db-1",
		target_label: "DB",
		relationship: "CONNECTS_TO",
	},
	{
		source: "app-1",
		source_label: "App",
		target: "infra-1",
		target_label: "Infra",
		relationship: "USES",
	},
];

describe("VisualRelationshipEditor", () => {
	const onMutated = vi.fn();

	beforeEach(() => {
		mockApiPost.mockReset();
		mockApiDelete.mockReset();
		onMutated.mockReset();
		mockApiPost.mockResolvedValue({});
		mockApiDelete.mockResolvedValue({});
	});

	it("selects source then target by clicking static CI nodes", () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "CI node Router A" }));
		expect(screen.getByText(/Source:/).parentElement).toHaveTextContent(
			"Router A",
		);

		fireEvent.click(screen.getByRole("button", { name: "CI node Switch B" }));
		expect(screen.getByText(/Target:/).parentElement).toHaveTextContent(
			"Switch B",
		);
	});

	it("populates CI form from clicked visual node", () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "CI node Router A" }));

		expect(screen.getByLabelText("CI ID")).toHaveValue("ci-a");
		expect(screen.getByLabelText("CI label")).toHaveValue("Router A");
		expect(screen.getByLabelText("CI type")).toHaveValue("INFRASTRUCTURE");
		expect(screen.getByLabelText("CI status")).toHaveValue("ACTIVE");
		expect(screen.getByRole("button", { name: "Save CI" })).toBeInTheDocument();
	});

	it("prevents create without required CI fields", () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "New CI" }));
		fireEvent.click(screen.getByRole("button", { name: "Create CI" }));

		expect(screen.getByText("CI ID is required.")).toBeInTheDocument();
		expect(mockApiPost).not.toHaveBeenCalled();
	});

	it("creates CI via existing node upsert API", async () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "New CI" }));
		fireEvent.change(screen.getByLabelText("CI ID"), {
			target: { value: "ci-c" },
		});
		fireEvent.change(screen.getByLabelText("CI label"), {
			target: { value: "Firewall C" },
		});
		fireEvent.change(screen.getByLabelText("CI type"), {
			target: { value: "INFRASTRUCTURE" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Create CI" }));

		await waitFor(() => {
			expect(mockApiPost).toHaveBeenCalledWith(
				"/nodes",
				expect.objectContaining({
					id: "ci-c",
					label: "Firewall C",
					type: "INFRASTRUCTURE",
					status: "OK",
					metadata: {},
				}),
			);
		});
		expect(onMutated).toHaveBeenCalledTimes(1);
	});

	it("updates selected CI via node upsert and preserves metadata", async () => {
		const nodesWithMetadata: GraphNode[] = [
			{ ...nodes[0], metadata: { rack: "R1" }, owner: "ops" },
			nodes[1],
		];
		render(
			<VisualRelationshipEditor
				nodes={nodesWithMetadata}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "CI node Router A" }));
		fireEvent.change(screen.getByLabelText("CI label"), {
			target: { value: "Router A Updated" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Save CI" }));

		await waitFor(() => {
			expect(mockApiPost).toHaveBeenCalledWith(
				"/nodes",
				expect.objectContaining({
					id: "ci-a",
					label: "Router A Updated",
					metadata: { rack: "R1" },
					owner: "ops",
				}),
			);
		});
	});

	it("preserves CI form state after save failure", async () => {
		mockApiPost.mockRejectedValueOnce(new Error("boom"));
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "New CI" }));
		fireEvent.change(screen.getByLabelText("CI ID"), {
			target: { value: "ci-c" },
		});
		fireEvent.change(screen.getByLabelText("CI label"), {
			target: { value: "Firewall C" },
		});
		fireEvent.change(screen.getByLabelText("CI type"), {
			target: { value: "INFRASTRUCTURE" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Create CI" }));

		expect(await screen.findByText("Could not save CI.")).toBeInTheDocument();
		expect(screen.getByLabelText("CI ID")).toHaveValue("ci-c");
		expect(screen.getByLabelText("CI label")).toHaveValue("Firewall C");
		expect(onMutated).not.toHaveBeenCalled();
	});

	it("deletes selected CI using existing node delete API", async () => {
		const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "CI node Router A" }));
		fireEvent.click(screen.getByRole("button", { name: "Delete CI" }));

		await waitFor(() =>
			expect(mockApiDelete).toHaveBeenCalledWith("/nodes/ci-a"),
		);
		expect(onMutated).toHaveBeenCalledTimes(1);
		confirmSpy.mockRestore();
	});

	it("does not allow delete without selected CI", () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		expect(screen.getByRole("button", { name: "Delete CI" })).toBeDisabled();
	});

	it("renders layer filters from category/type and selects all by default", () => {
		render(
			<VisualRelationshipEditor
				nodes={layeredNodes}
				links={layeredLinks}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		const appLayer = screen.getByRole("checkbox", {
			name: /Application layer \(1 CIs\)/,
		});
		const databaseLayer = screen.getByRole("checkbox", {
			name: /Database layer \(1 CIs\)/,
		});
		expect(
			screen.getByRole("checkbox", {
				name: /INFRASTRUCTURE layer \(1 CIs\)/,
			}),
		).toBeChecked();

		expect(appLayer).toBeChecked();
		expect(databaseLayer).toBeChecked();
		expect(
			screen.getByRole("button", { name: "CI node App" }),
		).toBeInTheDocument();
		expect(
			screen.getByRole("button", { name: "CI node DB" }),
		).toBeInTheDocument();
	});

	it("renders CI nodes as D3 SVG circles instead of large visual cards", () => {
		render(
			<VisualRelationshipEditor
				nodes={layeredNodes}
				links={layeredLinks}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		const appNodeButton = screen.getByRole("button", { name: "CI node App" });
		expect(appNodeButton).toHaveAttribute("title", "App · Application");
		expect(appNodeButton.querySelector("circle.node-circle")).toHaveAttribute(
			"r",
			"24",
		);
		expect(appNodeButton).not.toHaveClass("w-36", "rounded-2xl");
	});

	it("positions D3 nodes from CI coordinates", () => {
		render(
			<VisualRelationshipEditor
				nodes={[
					{ ...nodes[0], x: 10, y: 30 },
					{ ...nodes[1], x: 20, y: 40 },
				]}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		const routerTransform = screen
			.getByRole("button", { name: "CI node Router A" })
			.getAttribute("transform");
		const switchTransform = screen
			.getByRole("button", { name: "CI node Switch B" })
			.getAttribute("transform");
		expect(routerTransform).toMatch(/^translate\(/);
		expect(switchTransform).toMatch(/^translate\(/);
		expect(routerTransform).not.toBe(switchTransform);
	});

	it("uses CMDB lat/long projection and offsets duplicate coordinates", () => {
		const colocatedNodes = Array.from({ length: 6 }, (_, index) => ({
			...nodes[index % nodes.length],
			id: `ci-${index}`,
			label: `CI ${index}`,
			location: { lat: 32.5, long: -117 },
		}));
		render(
			<VisualRelationshipEditor
				nodes={colocatedNodes}
				links={[]}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		const transforms = colocatedNodes.map((node) =>
			screen
				.getByRole("button", { name: `CI node ${node.label}` })
				.getAttribute("transform"),
		);
		expect(transforms.every((transform) => transform?.startsWith("translate("))).toBe(true);
		expect(new Set(transforms).size).toBe(colocatedNodes.length);
	});

	it("filters nodes and shows an empty state when all layers are hidden", () => {
		render(
			<VisualRelationshipEditor
				nodes={layeredNodes}
				links={layeredLinks}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("checkbox", { name: /Database layer/ }));

		expect(
			screen.queryByRole("button", { name: "CI node DB" }),
		).not.toBeInTheDocument();
		expect(
			screen.getByRole("button", { name: "CI node App" }),
		).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: "None" }));

		expect(
			screen.queryByRole("button", { name: "CI node App" }),
		).not.toBeInTheDocument();
		expect(
			screen.getByText("No CIs match selected layers"),
		).toBeInTheDocument();
	});

	it("filters links whose endpoints are hidden", () => {
		render(
			<VisualRelationshipEditor
				nodes={layeredNodes}
				links={layeredLinks}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		expect(screen.getByText("App → DB")).toBeInTheDocument();
		fireEvent.click(screen.getByRole("checkbox", { name: /Database layer/ }));

		expect(screen.queryByText("App → DB")).not.toBeInTheDocument();
		expect(screen.getByText("App → Infra")).toBeInTheDocument();
	});

	it("clears hidden selected endpoints and preserves visible relationship creation", async () => {
		render(
			<VisualRelationshipEditor
				nodes={layeredNodes}
				links={[]}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "CI node App" }));
		fireEvent.click(screen.getByRole("button", { name: "CI node DB" }));
		expect(screen.getByText(/Target:/).parentElement).toHaveTextContent("DB");

		fireEvent.click(screen.getByRole("checkbox", { name: /Database layer/ }));

		expect(screen.getByText(/Target:/).parentElement).toHaveTextContent(
			"Select target",
		);
		expect(
			screen.getByRole("button", { name: "Create relationship" }),
		).toBeDisabled();
		expect(mockApiPost).not.toHaveBeenCalled();

		fireEvent.click(screen.getByRole("checkbox", { name: /Database layer/ }));
		fireEvent.click(screen.getByRole("button", { name: "CI node App" }));
		fireEvent.click(screen.getByRole("button", { name: "CI node DB" }));
		fireEvent.click(
			screen.getByRole("button", { name: "Create relationship" }),
		);

		await waitFor(() => {
			expect(mockApiPost).toHaveBeenCalledWith("/links", {
				source: "app-1",
				target: "db-1",
				relationship: "CONNECTS_TO",
			});
		});
	});

	it("preserves deselected and none layer choices across node refreshes", () => {
		const { rerender } = render(
			<VisualRelationshipEditor
				nodes={layeredNodes}
				links={layeredLinks}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("checkbox", { name: /Database layer/ }));
		rerender(
			<VisualRelationshipEditor
				nodes={[...layeredNodes]}
				links={layeredLinks}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		expect(
			screen.getByRole("checkbox", { name: /Database layer/ }),
		).not.toBeChecked();
		expect(
			screen.queryByRole("button", { name: "CI node DB" }),
		).not.toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: "None" }));
		rerender(
			<VisualRelationshipEditor
				nodes={[...layeredNodes]}
				links={layeredLinks}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		expect(
			screen.getByText("No CIs match selected layers"),
		).toBeInTheDocument();
		expect(
			screen.getByRole("checkbox", { name: /Application layer/ }),
		).not.toBeChecked();
		expect(
			screen.getByRole("checkbox", { name: /Database layer/ }),
		).not.toBeChecked();
		expect(
			screen.getByRole("checkbox", { name: /INFRASTRUCTURE layer/ }),
		).not.toBeChecked();
	});

	it("auto-selects newly discovered layers after node refresh", () => {
		const { rerender } = render(
			<VisualRelationshipEditor
				nodes={[layeredNodes[0]]}
				links={[]}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		rerender(
			<VisualRelationshipEditor
				nodes={[layeredNodes[0], layeredNodes[1]]}
				links={[]}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		expect(
			screen.getByRole("checkbox", { name: /Database layer \(1 CIs\)/ }),
		).toBeChecked();
		expect(
			screen.getByRole("button", { name: "CI node DB" }),
		).toBeInTheDocument();
	});

	it("prevents self-links", () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={[]}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "CI node Router A" }));
		fireEvent.click(screen.getByRole("button", { name: "CI node Router A" }));

		expect(
			screen.getByText("Source and target must be different CIs."),
		).toBeInTheDocument();
		expect(
			screen.getByRole("button", { name: "Create relationship" }),
		).toBeDisabled();
	});

	it("creates a link with a supported relationship type and refreshes", async () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={[]}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "CI node Router A" }));
		fireEvent.click(screen.getByRole("button", { name: "CI node Switch B" }));
		fireEvent.change(screen.getByLabelText("Relationship type"), {
			target: { value: "DEPENDS_ON" },
		});
		fireEvent.click(
			screen.getByRole("button", { name: "Create relationship" }),
		);

		await waitFor(() => {
			expect(mockApiPost).toHaveBeenCalledWith("/links", {
				source: "ci-a",
				target: "ci-b",
				relationship: "DEPENDS_ON",
			});
		});
		expect(onMutated).toHaveBeenCalledTimes(1);
	});

	it("keeps RUNS_ON visible and labeled read-only", () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={readOnlyLinks}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		expect(screen.getByText("Router A → Switch B")).toBeInTheDocument();
		expect(screen.getAllByText("RUNS_ON").length).toBeGreaterThan(0);
		expect(screen.getByText("Read-only")).toBeInTheDocument();
	});

	it("does not offer delete for RUNS_ON links", () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={readOnlyLinks}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		expect(
			screen.queryByRole("button", { name: "Delete" }),
		).not.toBeInTheDocument();
		expect(mockApiDelete).not.toHaveBeenCalled();
	});

	it("deletes an existing visual link and refreshes", async () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={links}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: "Delete" }));

		await waitFor(() =>
			expect(mockApiDelete).toHaveBeenCalledWith("/links", links[0]),
		);
		expect(onMutated).toHaveBeenCalledTimes(1);
	});

	it("does not offer legacy CONNECTED_TO relationship type", () => {
		render(
			<VisualRelationshipEditor
				nodes={nodes}
				links={[]}
				onClose={vi.fn()}
				onMutated={onMutated}
			/>,
		);

		expect(
			screen.queryByRole("option", { name: "CONNECTED_TO" }),
		).not.toBeInTheDocument();
		expect(
			screen.getByRole("option", { name: "CONNECTS_TO" }),
		).toBeInTheDocument();
	});
});
