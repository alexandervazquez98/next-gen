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
